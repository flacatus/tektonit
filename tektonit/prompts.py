"""Prompts for LLM-powered BATS test generation.

Generates BATS unit tests for bash/sh scripts embedded in Tekton resources.
No pytest — all testing is done via BATS.
"""

import re

# ──────────────────────────────────────────────────────────────────────────────
# BATS system prompt
# ──────────────────────────────────────────────────────────────────────────────

BATS_SYSTEM_PROMPT = """\
You are an expert test engineer. You write BATS (Bash Automated Testing System) \
unit tests for bash scripts embedded inside Tekton Tasks, StepActions, and Pipelines.

You test the ACTUAL LOGIC of the script — branches, loops, error handling, \
output, exit codes, result files. Every @test block exercises a real code path.

CRITICAL — PRECISION RULES:
1. EMBED THE EXACT SCRIPT VERBATIM. Copy every line character-for-character from the \
   YAML into the heredoc. Do NOT paraphrase, simplify, rewrite, or omit any line. \
   The test MUST run the real production script, not a summary of it.
2. MOCK THE EXACT COMMANDS the script calls. Read the script line by line and identify \
   every external command invocation with its exact flags and arguments. Each mock must \
   handle the exact invocation patterns from the script.
3. ASSERT ON EXACT STRINGS. When the script echoes "[ERROR]: foo bar", assert on \
   *"[ERROR]: foo bar"*, not *"error"* or *"ERROR"*. Copy the exact echo/printf strings.
4. SED-REPLACE EXACT PATTERNS. Search the script for the exact $(params.X), \
   $(results.X.path), $(step.results.X.path) patterns and replace each one precisely.
5. TRACE EVERY CODE PATH. Read each if/elif/else/case/for/while in the script. \
   For each branch, write a @test that forces the script into that specific path \
   by setting up the right mock responses and inputs.

REFERENCE IMPLEMENTATION (follow this pattern — note the suite organization):
```bats
#!/usr/bin/env bats

setup() {
  export TEST_TEMP_DIR=$(mktemp -d)
  export SCRIPT_FILE="$TEST_TEMP_DIR/script.sh"
  export TEKTON_STEPS_DIR="$TEST_TEMP_DIR/tekton/steps"
  mkdir -p "$TEKTON_STEPS_DIR"

  # Embed the script via heredoc
  cat << 'SCRIPT_EOF' > "$SCRIPT_FILE"
#!/bin/bash
set -e
# <actual script content pasted here>
SCRIPT_EOF

  # Replace Tekton paths with temp paths
  sed -i'' -e "s|/tekton/steps/|$TEKTON_STEPS_DIR/|g" "$SCRIPT_FILE"
  chmod +x "$SCRIPT_FILE"
}

teardown() {
  rm -rf "$TEST_TEMP_DIR"
}

# ── Suite: Happy Path ────────────────────────────────────

@test "happy path: no exitCode files found" {
  run "$SCRIPT_FILE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"[INFO]: Did not find any failed steps"* ]]
}

# ── Suite: Error Handling ────────────────────────────────

@test "error: one step failed" {
  mkdir -p "$TEKTON_STEPS_DIR/step-test"
  echo "1" > "$TEKTON_STEPS_DIR/step-test/exitCode"
  run "$SCRIPT_FILE"
  [ "$status" -eq 1 ]
  [[ "$output" == *"[ERROR]"* ]]
}

# ── Suite: Edge Cases ────────────────────────────────────

@test "edge: empty steps directory" {
  rm -rf "$TEKTON_STEPS_DIR"
  mkdir -p "$TEKTON_STEPS_DIR"
  run "$SCRIPT_FILE"
  [ "$status" -eq 0 ]
}
```

STRICT RULES:
- Output ONLY the .bats file. No markdown fences, no explanations, no prose.
- Start with #!/usr/bin/env bats
- Embed the FULL script in setup() via heredoc (cat << 'SCRIPT_EOF' > "$SCRIPT_FILE")
- Use sed to replace $(params.X) with concrete test values
- Use sed to replace $(results.X.path) / $(step.results.X.path) with temp file paths
- Use sed to replace hardcoded paths (/tekton/steps/, /workspace/) with temp paths
- Mock external commands (kubectl, oc, curl, jq, oras, git, rosa, gh, etc.) \
  by creating executable scripts in $MOCK_BIN prepended to PATH
- Tests must NOT need a Kubernetes cluster or real network
- Each @test must test ONE specific behavior of the script
- Test the actual logic: conditionals, loops, error exits, output messages, result files
- For scripts with env vars from fieldRef/secretKeyRef, export them in setup()
- For scripts with retry/wait loops, mock to succeed immediately to avoid slow tests

ASSERTION REQUIREMENTS — EVERY @test MUST have ALL of these that apply:
1. Exit code: [ "$status" -eq N ]
2. Output check: [[ "$output" == *"expected message"* ]] for EACH echo/printf in that path
3. Result files: [ -f "$RESULTS_DIR/name" ] AND content check: [ "$(cat ...)" = "expected" ]
4. JSON output: use `jq -r '.field'` to validate specific JSON fields, not just "file exists"
5. Negative checks: verify things that should NOT appear: [[ "$output" != *"error"* ]]
A test with ONLY an exit code check is INCOMPLETE. Aim for 3-5 assertions per @test.

MOCK COMMAND BEST PRACTICES:
- FIRST: read the script line by line and list every external command call with its exact \
  arguments. Then create a mock for EACH ONE that returns data matching what the script expects.
- Match on the EXACT invocation pattern. If the script calls `oras manifest fetch "$REF"`, \
  the mock must match `[[ "$1" == "manifest" && "$2" == "fetch" ]]`.
- If the script pipes command output through jq (e.g., `kubectl get ... -o json | jq '.items'`), \
  the mock must return VALID JSON that jq can parse, with the exact fields the jq expression reads.
- EVERY mock MUST end with a fallback `else` clause:
  ```
  else
    echo "" >&2
    exit 0
  fi
  ```
- Example — mock that precisely matches script invocations:
  If the script does:
    `MANIFESTS_ANNOTATIONS=$(oras manifest fetch "$REF" 2>> /dev/null | jq .annotations)`
    `oras pull "$REF"`
    `oras push "$REF" --annotation-file "$FILE" ./:media-type`
  Then the mock must handle all three:
  ```
  cat << 'EOF' > "$MOCK_BIN/oras"
  #!/bin/bash
  if [[ "$1" == "manifest" && "$2" == "fetch" ]]; then
    if [[ -f "$MOCK_DATA_DIR/manifest.json" ]]; then
      cat "$MOCK_DATA_DIR/manifest.json"
    else
      exit 1
    fi
  elif [[ "$1" == "pull" ]]; then
    echo "Pulled $2"
    exit 0
  elif [[ "$1" == "push" ]]; then
    if [[ "$MOCK_PUSH_FAIL" == "true" ]]; then
      exit 1
    fi
    echo "Pushed $2"
    exit 0
  else
    echo "" >&2
    exit 0
  fi
  EOF
  ```
- Store mock data in files under $MOCK_DATA_DIR (mkdir -p "$MOCK_DATA_DIR" in setup)
- Change mock data per-test by overwriting files in $MOCK_DATA_DIR or setting env vars
- Use "$MOCK_DATA_DIR" instead of env vars for complex JSON — avoids escaping issues
- For jq: no need to mock jq — it works on both macOS and Linux. Just feed it valid JSON.
- For scripts that pipe commands (cmd1 | cmd2 | cmd3), mock cmd1 to output what cmd2 expects

CROSS-PLATFORM PORTABILITY (macOS + Linux):
Tests MUST pass on both macOS (BSD) and Linux (GNU). These commands differ:
- `#!/bin/bash` shebang: ALWAYS change to `#!/usr/bin/env bash` in the embedded script \
  heredoc. macOS ships bash 3.2 at /bin/bash which lacks features like `&>>`, `|&`, \
  associative arrays. `#!/usr/bin/env bash` picks up the user's bash (usually 4+/5+).
- `&>>` (append stdout+stderr): NOT supported in bash 3.2. Replace with `>> file 2>&1`.
- `sed -i`: use `sed -i'' -e` (no space after -i)
- `date -d`: does NOT exist on macOS. If the script uses `date -d` or `date -u -d`, \
  you MUST create a `date` mock in $MOCK_BIN that handles all the date calls the script \
  makes and returns predictable values. Example:
  ```
  cat << 'EOF' > "$MOCK_BIN/date"
  #!/bin/bash
  if [[ "$*" == *"+%s"* ]]; then
    echo "1672531300"
  elif [[ "$*" == *"+%Y-%m-%dT"* ]]; then
    echo "2023-01-01T00:01:40Z"
  else
    /bin/date "$@"
  fi
  EOF
  chmod +x "$MOCK_BIN/date"
  ```
- `readlink -f`: does NOT exist on macOS. Mock it if the script uses it.
- `grep -P` (PCRE): does NOT exist on macOS. Mock if used.
- `stat` flags differ. Mock if the script uses stat.
- `mktemp` works the same on both — no mock needed.

BASH `|| true` vs `exit` BEHAVIOR:
When a script does `main || true`, the `|| true` only catches non-zero RETURN codes from \
the function (e.g., `set -e` aborting on a failed command). However, an explicit `exit 1` \
inside the function TERMINATES THE ENTIRE SHELL PROCESS — `|| true` cannot catch it. \
So if a function contains `exit 1`, calling it as `main || true` still exits with 1.

WHILE/UNTIL LOOPS:
Scripts with `while true`, `until`, or retry loops MUST be handled carefully:
- Mock the exit condition so the loop breaks on the FIRST iteration
- For kubectl polling loops, ensure the mock returns completed data immediately
- NEVER let a test hang — if a loop can run forever, the mock MUST break it
- If the script has `sleep` in a loop, always mock sleep as a no-op script in $MOCK_BIN

MOCK ROBUSTNESS:
- Every mock command MUST have a fallback for unmatched cases (e.g., `echo ""; exit 0`)
- All JSON mock data files MUST be valid JSON — verify with `jq empty` in setup if unsure
- Use `cat << 'EOF'` (single-quoted) to prevent variable expansion in heredocs
- Each @test MUST reset per-test state: overwrite mock data files, unset env vars
- Never assume state from a previous @test carries over — BATS runs each test in a subshell
  but setup()/teardown() re-run each time

TEST ORGANIZATION — CRITICAL FOR REVIEWABILITY:
Organize tests into clearly named SUITES using comment headers. Each suite groups \
related tests. This makes the file easy to review in a PR.

Structure:
```bats
# ── Suite: Happy Path ────────────────────────────────────

@test "happy path: processes all items successfully" { ... }
@test "happy path: writes correct result file" { ... }

# ── Suite: Error Handling ────────────────────────────────

@test "error: fails when required param is empty" { ... }
@test "error: exits 1 when kubectl returns error" { ... }

# ── Suite: Edge Cases ────────────────────────────────────

@test "edge: handles empty JSON response" { ... }
@test "edge: handles missing optional fields" { ... }
```

Rules:
- Name each @test with a CLEAR PREFIX matching its suite: "happy path:", "error:", \
  "edge:", "retry:", "result:", etc.
- Keep each @test FOCUSED — test ONE behavior, not five. Short tests are easier to review.
- Maximum 15-20 @test blocks per file. If the script has more code paths, prioritize \
  the most important ones (error handling > edge cases > minor variations).
- Each @test should be readable in isolation — a reviewer should understand what it \
  tests without reading the entire file.

TEST QUALITY CHECKLIST:
Before outputting, verify:
1. Every if/else/elif branch in the script has a corresponding @test
2. Every exit code path has a test verifying the correct exit status
3. Every echo/printf output is verified with [[ "$output" == *"expected"* ]]
4. All result files are verified for correct content
5. All external commands have both success AND failure @test cases
6. Mock JSON data is valid (no trailing commas, proper quoting)
7. No test can hang — all loops break, all sleeps are mocked
8. Tests are organized into named suites with comment headers
9. Each @test has a descriptive name with suite prefix
"""

# ──────────────────────────────────────────────────────────────────────────────
# BATS generation template
# ──────────────────────────────────────────────────────────────────────────────

BATS_GENERATE_TEMPLATE = """\
Generate BATS unit tests for the bash script(s) in this Tekton {kind}.

## Resource YAML
```yaml
{yaml_content}
```

## Resource Info
- Kind: {kind}
- Name: {name}
- File: {source_path}
- Scripts to test: {script_info}

## Script Analysis (auto-generated from static analysis)
{script_analysis}

## setup() must:
1. Create temp dir: `export TEST_TEMP_DIR=$(mktemp -d)`
2. Embed the script in a heredoc: `cat << 'SCRIPT_EOF' > "$SCRIPT_FILE"`
3. sed-replace $(params.X) with test values
4. sed-replace $(results.X.path) / $(step.results.X.path) with temp file paths
5. sed-replace hardcoded paths with temp paths
6. Create $MOCK_BIN dir, prepend to PATH
7. Create mock scripts for external commands with FALLBACK behavior for unmatched args
8. Export env vars the script needs
9. `chmod +x "$SCRIPT_FILE"`

## teardown() must:
1. `rm -rf "$TEST_TEMP_DIR"`

## Mock strategy
{mock_strategy}

## External commands to mock
{mock_commands}

## Environment variables to mock
{env_mock_section}

## Results to verify after execution
{result_verification}

## STEP 1: Extract and embed the script
Copy the ENTIRE script from the YAML `script:` field into the heredoc VERBATIM.
Do NOT skip lines, do NOT rewrite logic, do NOT simplify. Every line matters.
After embedding, use sed to replace these EXACT patterns found in the script:
{sed_replacements}

## STEP 2: Identify every external command call
Read through the embedded script line by line. For each line that calls an external command,
note the exact command name, subcommand, and flags. Create a mock for each one.

## STEP 3: Map every code path to a @test
{test_cases}

## STEP 4: Write precise assertions
For each @test, copy the EXACT echo/printf strings from the script into your assertions.
Example: if the script says `echo -e "[ERROR]: oras push failed after $attempt attempts."`
then assert: `[[ "$output" == *"[ERROR]: oras push failed after"* ]]`

## Reference example
Below is a REAL passing BATS test for a similar resource. Follow this exact pattern:
{few_shot_example}

## Edge cases
- Empty/missing required inputs
- External commands returning errors (non-zero exit)
- Malformed data (invalid JSON for jq, empty responses for curl/kubectl)
- Scripts with set -e: verify they abort on first failure
- Result files: verify content is written correctly

## STEP 5: Organize into named suites
Group tests into suites with comment headers. Use descriptive test names with suite prefixes.
Keep the file under 20 @test blocks total — focus on the most valuable test cases.

Output ONLY the .bats file. No markdown, no explanations.
"""

# ──────────────────────────────────────────────────────────────────────────────
# Propose prompt — for adding tests to existing BATS coverage
# ──────────────────────────────────────────────────────────────────────────────

PROPOSE_PROMPT_TEMPLATE = """\
I have existing BATS tests for a Tekton {kind} named "{name}". \
Review them and propose NEW tests that improve coverage of the script logic.

## Resource YAML
```yaml
{yaml_content}
```

## Existing Tests
```
{existing_tests}
```

## Instructions
1. Analyze what code paths the existing tests cover
2. Identify UNTESTED branches, loops, error paths, edge cases
3. Generate ONLY new @test blocks to APPEND
4. Do NOT duplicate existing tests
5. Focus on untested script logic, not YAML structure

Output ONLY the new @test blocks to append. No markdown, no explanations.
"""


def _detect_script_language(script: str) -> str:
    """Detect script language from shebang or content."""
    first_line = script.strip().split("\n")[0] if script.strip() else ""
    if "python" in first_line:
        return "python"
    return "bash"


def _detect_commands_in_script(script: str) -> list[str]:
    """Detect external commands used in a bash script that need mocking."""
    known_commands = [
        "kubectl", "oc", "curl", "git", "oras", "jq", "yq",
        "aws", "rosa", "gh", "docker", "podman", "skopeo",
        "pip", "npm", "make", "helm", "kustomize", "cosign",
        "tkn", "base64", "openssl", "wget", "shellcheck",
        "hadolint", "find", "date", "readlink", "sleep",
    ]
    found = []
    for cmd in known_commands:
        if re.search(rf"\b{cmd}\b", script):
            found.append(cmd)
    return found


def _detect_env_vars_in_resource(resource) -> list[dict]:
    """Detect environment variables defined in steps that need mocking."""
    env_vars = []
    for step in resource.steps:
        for env in step.env:
            entry = {"name": env.get("name", ""), "source": "direct"}
            value_from = env.get("valueFrom", {})
            if value_from.get("fieldRef"):
                entry["source"] = "fieldRef"
                entry["field"] = value_from["fieldRef"].get("fieldPath", "")
            elif value_from.get("secretKeyRef"):
                entry["source"] = "secretKeyRef"
                entry["secret"] = value_from["secretKeyRef"].get("name", "")
                entry["key"] = value_from["secretKeyRef"].get("key", "")
            elif env.get("value"):
                entry["source"] = "value"
                entry["value"] = env["value"]
            env_vars.append(entry)
    return env_vars


def _build_env_mock_section(resource) -> str:
    """Build environment variable mocking instructions."""
    env_vars = _detect_env_vars_in_resource(resource)
    if not env_vars:
        # Check for env vars referenced directly in scripts
        lines = []
        for _, script in resource.embedded_scripts:
            for match in re.findall(r'\$\{?([A-Z][A-Z0-9_]+)\}?', script):
                if match not in ("PATH", "HOME", "PWD", "SHELL", "USER", "TMPDIR",
                                 "BASH_COMMAND", "LINENO", "PIPESTATUS", "IFS",
                                 "FUNCNAME", "BASH_SOURCE", "OSTYPE", "HOSTNAME",
                                 "SCRIPT_EOF", "EOF", "MOCK_EOF"):
                    lines.append(f'- Export `{match}`: `export {match}="test-value"`')
        seen = set()
        unique = []
        for line in lines:
            if line not in seen:
                seen.add(line)
                unique.append(line)
        return "\n".join(unique) if unique else "- No environment variables to mock"

    lines = []
    for env in env_vars:
        name = env["name"]
        if env["source"] == "fieldRef":
            lines.append(f'- Export `{name}` (fieldRef: {env.get("field", "")}): '
                         f'`export {name}="test-value"`')
        elif env["source"] == "secretKeyRef":
            lines.append(f'- Export `{name}` (secret): `export {name}="mock-secret"`')
        elif env["source"] == "value":
            val = env.get("value", "")
            if "$(params." in val:
                lines.append(f'- Export `{name}`: `export {name}="test-param-value"`')
            else:
                lines.append(f'- Export `{name}`: already set to `"{val}"`')
        else:
            lines.append(f'- Export `{name}`: `export {name}="test-value"`')
    return "\n".join(lines)


def _build_result_verification(resource) -> str:
    """Build result verification instructions."""
    results = resource.results
    if not results:
        # Check for result references in scripts
        all_refs = set()
        for _, script in resource.embedded_scripts:
            all_refs.update(re.findall(r'\$\((?:step\.)?results\.([a-zA-Z0-9_-]+)\.path\)', script))
        if all_refs:
            lines = [f'- Verify result file `{r}` is written with expected content' for r in sorted(all_refs)]
            return "\n".join(lines)
        return "- No results to verify"

    lines = []
    for r in results:
        lines.append(f'- Verify `{r.name}`: `[ -f "$RESULTS_DIR/{r.name}" ]` and check content')
    return "\n".join(lines)


def _extract_exact_outputs(script: str) -> list[str]:
    """Extract exact echo/printf strings from script for precise assertion guidance."""
    outputs = []
    seen_prefixes = set()
    # Match echo with various flag combinations and quoting styles
    for match in re.finditer(r'echo\s+(?:-[en]+\s+)?"([^"]*)"', script):
        msg = match.group(1).strip()
        if not msg or len(msg) < 4:
            continue
        # Use first 30 chars as dedup key to avoid near-duplicates
        prefix = msg[:30]
        if prefix not in seen_prefixes:
            seen_prefixes.add(prefix)
            outputs.append(msg)
    return outputs


def _extract_exact_branches(script: str) -> list[str]:
    """Extract exact if/elif conditions from script for precise test case mapping."""
    branches = []
    for match in re.finditer(r'if\s+\[\[?\s*(.*?)\s*\]?\];?\s*then', script):
        cond = match.group(1).strip()[:100]
        branches.append(cond)
    for match in re.finditer(r'elif\s+\[\[?\s*(.*?)\s*\]?\];?\s*then', script):
        cond = match.group(1).strip()[:100]
        branches.append(cond)
    return branches


def _build_test_cases(resource, scripts: list[tuple[str, str]]) -> str:
    """Build test case descriptions based on actual script analysis."""
    cases = []
    for step_name, script in scripts:
        if _detect_script_language(script) != "bash":
            continue

        cases.append(f"\n#### Step: {step_name}")

        # Extract exact branches for precise test case mapping
        branches = _extract_exact_branches(script)
        if branches:
            cases.append("Exact branches found in script (write a @test for EACH):")
            for i, cond in enumerate(branches, 1):
                cases.append(f"  {i}. `{cond}` → test TRUE path AND FALSE path")

        # Extract exact output strings for assertion guidance
        outputs = _extract_exact_outputs(script)
        if outputs:
            cases.append("Exact output strings to assert on (copy these into assertions):")
            for msg in outputs[:15]:  # cap at 15
                # Show a prefix suitable for assertion matching
                prefix = msg.split("$")[0].rstrip() if "$" in msg else msg
                if prefix:
                    cases.append(f'  - `[[ "$output" == *"{prefix}"* ]]`')

        if "while " in script or "for " in script:
            cases.append("- Test loop with 0, 1, and multiple iterations")
        if "while true" in script or "until " in script or "while !" in script:
            cases.append(
                "- CRITICAL: Mock the loop exit condition so it breaks on FIRST iteration. "
                "Mock sleep as no-op. Never let a test hang."
            )
        if "exit " in script:
            # Extract exact exit codes
            exit_codes = set(re.findall(r'exit\s+(\d+)', script))
            if exit_codes:
                cases.append(f"- Test each exit code: {', '.join(sorted(exit_codes))}")
            else:
                cases.append("- Test each exit code path")
        if "jq " in script:
            cases.append("- Test JSON parsing: valid JSON, empty input, missing keys")
        if "curl " in script:
            cases.append("- Test HTTP mock: success (200), failure (500), empty body")
        if "kubectl " in script or "oc " in script:
            cases.append("- Test k8s mock: success with data, empty results, command failure")
        if "set -e" in script or "set -euo pipefail" in script:
            cases.append("- Verify script aborts on command failure (set -e)")
        if "trap " in script:
            cases.append("- Verify trap handler runs on error/exit")
        if "$(results." in script or "$(step.results." in script:
            cases.append("- Verify result files written with correct content")
        if "SNAPSHOT" in script:
            cases.append("- Test SNAPSHOT JSON: valid, empty components array, missing component")
        if "retry" in script.lower() or "attempt" in script.lower():
            cases.append("- Test retry: succeed on first try, fail all retries")

        cases.append("- Test happy path (all inputs valid, commands succeed)")
        cases.append("- Test with missing/empty required inputs")

    return "\n".join(cases) if cases else "- Test the main execution path\n- Test error handling"


def _mock_strategy_for_kind(resource) -> str:
    """Return resource-type-specific mock strategy."""
    kind = resource.kind

    if kind == "StepAction":
        return """\
StepActions have a SINGLE script:
- Embed the full script via heredoc in setup()
- Mock all external CLI tools in $MOCK_BIN
- sed-replace $(params.X) and $(results.X.path) with temp paths
- Export env vars the script reads
- Test as standalone executable"""

    elif kind == "Task":
        steps_info = []
        for s in resource.steps:
            if s.script:
                steps_info.append(f"  - Step '{s.name}': inline script → TEST THIS")
            elif s.ref:
                steps_info.append(f"  - Step '{s.name}': uses ref → SKIP (tested separately)")
        steps_str = "\n".join(steps_info) if steps_info else "  - No inline scripts"

        return f"""\
Tasks have MULTIPLE steps — test each inline script independently:
{steps_str}

Per step:
- Embed that step's script in its own setup()
- Create temp /workspace/ dirs to simulate shared workspaces
- Create temp files for volume mounts (secrets, configmaps)
- Mock env vars from fieldRef/secretKeyRef
- Each step gets its own @test blocks"""

    elif kind in ("Pipeline", "PipelineRun"):
        return """\
Pipelines/PipelineRuns are mostly declarative. Only test inline scripts \
if present in taskSpec blocks."""

    return "- Mock external commands in $MOCK_BIN"


def _build_script_analysis(bash_scripts: list[tuple[str, str]]) -> str:
    """Run static analysis on scripts and format for the prompt."""
    from tektonit.script_analyzer import analyze_script

    parts = []
    for step_name, script in bash_scripts:
        analysis = analyze_script(script)
        parts.append(f"### Step: {step_name}")
        parts.append(analysis.to_prompt_section())
    return "\n\n".join(parts) if parts else "No detailed analysis available."


def _find_few_shot_example(resource) -> str:
    """Find a real passing BATS test from the catalog to use as few-shot example.

    Looks for existing sanity-check/*.bats files near the resource,
    walking up the directory tree to find one from a sibling resource.
    """
    from pathlib import Path

    source = Path(resource.source_path)

    # Search strategy: look for .bats files in nearby sanity-check/ dirs
    # 1. Same resource type directory (e.g., stepactions/*/0.1/sanity-check/)
    # 2. Same top-level category (e.g., stepactions/)
    search_roots = [
        source.parent.parent.parent,  # e.g., stepactions/
        source.parent.parent.parent.parent,  # e.g., catalog root
    ]

    for root in search_roots:
        if not root.exists():
            continue
        for bats_file in sorted(root.rglob("sanity-check/*.bats")):
            # Don't use the resource's own test as example
            if bats_file.parent.parent == source.parent:
                continue
            content = bats_file.read_text()
            # Only use tests that look complete (have setup, teardown, @test)
            if "setup()" in content and "teardown()" in content and "@test" in content:
                # Truncate if too long (keep first 150 lines)
                lines = content.splitlines()
                if len(lines) > 150:
                    content = "\n".join(lines[:150]) + "\n# ... (truncated)"
                return f"```bats\n{content}\n```"

    return "(No reference example available in the catalog — follow the system prompt patterns)"


def _build_sed_replacements(resource, bash_scripts: list[tuple[str, str]]) -> str:
    """Extract exact $(params.X), $(results.X.path) patterns from scripts for sed instructions."""
    params_found = set()
    results_found = set()
    step_results_found = set()
    paths_found = set()

    for _, script in bash_scripts:
        # Extract exact param references
        for m in re.findall(r'\$\(params\.([a-zA-Z0-9_-]+)\)', script):
            params_found.add(m)
        # Extract exact result references
        for m in re.findall(r'\$\(results\.([a-zA-Z0-9_-]+)\.path\)', script):
            results_found.add(m)
        # Extract exact step.result references
        for m in re.findall(r'\$\(step\.results\.([a-zA-Z0-9_-]+)\.path\)', script):
            step_results_found.add(m)
        # Extract hardcoded paths
        if '/tekton/steps/' in script:
            paths_found.add('/tekton/steps/')
        if '/workspace/' in script:
            paths_found.add('/workspace/')
        for m in re.findall(r'(/[a-z]+/[a-z-]+/)', script):
            if m not in ('/usr/bin/', '/usr/local/', '/dev/null/'):
                paths_found.add(m)

    lines = []
    for p in sorted(params_found):
        # Suggest a realistic test value based on param name
        if 'url' in p.lower() or 'ref' in p.lower() or 'oci' in p.lower():
            val = "quay.io/test/repo:tag"
        elif 'path' in p.lower() or 'dir' in p.lower():
            val = "$TEST_TEMP_DIR/workdir"
        elif 'name' in p.lower():
            val = "test-resource-name"
        elif 'pass' in p.lower() or 'bool' in p.lower():
            val = "true"
        else:
            val = f"test-{p}-value"
        lines.append(f'- `sed -i\'\' -e "s|$(params.{p})|{val}|g" "$SCRIPT_FILE"`')
    for r in sorted(results_found):
        lines.append(f'- `sed -i\'\' -e "s|$(results.{r}.path)|$RESULTS_DIR/{r}|g" "$SCRIPT_FILE"`')
    for r in sorted(step_results_found):
        lines.append(f'- `sed -i\'\' -e "s|$(step.results.{r}.path)|$RESULTS_DIR/{r}|g" "$SCRIPT_FILE"`')
    for p in sorted(paths_found):
        lines.append(f'- `sed -i\'\' -e "s|{p}|$TEST_TEMP_DIR{p}|g" "$SCRIPT_FILE"`')

    if not lines:
        return "- No Tekton variable substitutions needed"
    return "\n".join(lines)


def build_bats_prompt(resource, yaml_content: str) -> str:
    """Build BATS generation prompt for bash scripts in a Tekton resource."""
    scripts = resource.embedded_scripts
    bash_scripts = [(name, s) for name, s in scripts if _detect_script_language(s) == "bash"]

    script_info = ", ".join(f"'{name}'" for name, _ in bash_scripts)

    all_commands = set()
    for _, script in bash_scripts:
        all_commands.update(_detect_commands_in_script(script))

    # Commands that differ between macOS and Linux — always mock
    platform_sensitive = {"date", "readlink", "stat", "sleep"}

    if all_commands:
        lines = []
        for cmd in sorted(all_commands):
            if cmd in platform_sensitive:
                lines.append(
                    f"- `{cmd}`: MUST mock (differs between macOS/Linux) — "
                    f"create $MOCK_BIN/{cmd} returning predictable values"
                )
            else:
                lines.append(
                    f"- `{cmd}`: create $MOCK_BIN/{cmd} that echoes predictable output"
                )
        mock_commands = "\n".join(lines)
    else:
        mock_commands = "- No external commands to mock"

    return BATS_GENERATE_TEMPLATE.format(
        kind=resource.kind,
        name=resource.name,
        source_path=resource.source_path,
        yaml_content=yaml_content,
        script_info=script_info,
        mock_commands=mock_commands,
        mock_strategy=_mock_strategy_for_kind(resource),
        test_cases=_build_test_cases(resource, bash_scripts),
        env_mock_section=_build_env_mock_section(resource),
        result_verification=_build_result_verification(resource),
        script_analysis=_build_script_analysis(bash_scripts),
        few_shot_example=_find_few_shot_example(resource),
        sed_replacements=_build_sed_replacements(resource, bash_scripts),
    )


def build_propose_prompt(resource, yaml_content: str, existing_tests: str) -> str:
    """Build the proposal prompt for adding BATS tests to existing coverage."""
    return PROPOSE_PROMPT_TEMPLATE.format(
        kind=resource.kind,
        name=resource.name,
        yaml_content=yaml_content,
        existing_tests=existing_tests,
    )


def has_bash_scripts(resource) -> bool:
    """Check if a resource has any bash scripts to test."""
    return any(_detect_script_language(s) == "bash" for _, s in resource.embedded_scripts)


def has_python_scripts(resource) -> bool:
    """Check if a resource has any Python scripts to test."""
    return any(_detect_script_language(s) == "python" for _, s in resource.embedded_scripts)


def has_testable_scripts(resource) -> bool:
    """Check if a resource has any scripts (bash or python) to test."""
    return any(
        _detect_script_language(s) in ("bash", "python")
        for _, s in resource.embedded_scripts
    )


def get_script_languages(resource) -> set[str]:
    """Return set of script languages found in a resource."""
    return {
        _detect_script_language(s)
        for _, s in resource.embedded_scripts
        if _detect_script_language(s) in ("bash", "python")
    }


# ──────────────────────────────────────────────────────────────────────────────
# PYTEST system prompt
# ──────────────────────────────────────────────────────────────────────────────

PYTEST_SYSTEM_PROMPT = """\
You are an expert test engineer. You write pytest unit tests for Python scripts \
embedded inside Tekton Tasks, StepActions, and Pipelines.

You test the ACTUAL LOGIC of the script — functions, branches, loops, error handling, \
output, exit codes, result files. Every test exercises a real code path.

CRITICAL — PRECISION RULES:
1. EMBED THE EXACT SCRIPT VERBATIM. Copy the Python script character-for-character \
   from the YAML. Do NOT rewrite or simplify any logic.
2. MOCK THE EXACT CALLS the script makes. Use unittest.mock.patch to mock external \
   calls (urllib, subprocess, http requests, etc.).
3. ASSERT ON EXACT STRINGS. When the script prints "Error: foo", assert on "Error: foo".
4. REPLACE TEKTON VARIABLES. The script may contain $(params.X) or $(results.X.path) — \
   these are literal strings in the Python source. Replace them with test values \
   before executing.
5. TRACE EVERY CODE PATH. Every if/elif/else/try/except branch needs a test.

REFERENCE IMPLEMENTATION:
```python
import os
import sys
import tempfile
import textwrap
from unittest.mock import patch, MagicMock
import pytest


@pytest.fixture
def script_env(tmp_path):
    \"\"\"Create the script file with Tekton variables replaced.\"\"\"
    # Embed the EXACT script from the YAML
    script_content = textwrap.dedent('''\\
        #!/usr/libexec/platform-python
        import os
        import sys
        # ... exact script content ...
    ''')

    # Replace Tekton variable placeholders
    script_content = script_content.replace('$(params.MY_PARAM)', 'test-value')
    script_content = script_content.replace('$(results.my-result.path)', str(tmp_path / 'my-result'))

    script_file = tmp_path / "script.py"
    script_file.write_text(script_content)

    # Set up environment variables the script needs
    env = os.environ.copy()
    env["MY_VAR"] = "test-value"

    return script_file, env, tmp_path


def run_script(script_file, env, args=None):
    \"\"\"Run the script as a subprocess and return (returncode, stdout, stderr).\"\"\"
    import subprocess
    cmd = [sys.executable, str(script_file)] + (args or [])
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
    return result.returncode, result.stdout, result.stderr


class TestHappyPath:
    def test_success(self, script_env):
        script_file, env, tmp_path = script_env
        returncode, stdout, stderr = run_script(script_file, env)
        assert returncode == 0
        assert "expected output" in stdout

    def test_result_file_written(self, script_env):
        script_file, env, tmp_path = script_env
        run_script(script_file, env)
        result_file = tmp_path / "my-result"
        assert result_file.exists()
        assert result_file.read_text().strip() == "expected-content"


class TestErrorPaths:
    def test_missing_env_var(self, script_env):
        script_file, env, tmp_path = script_env
        del env["MY_VAR"]
        returncode, stdout, stderr = run_script(script_file, env)
        assert returncode == 1
        assert "Error:" in stdout or "Error:" in stderr
```

STRICT RULES:
- Output ONLY the .py test file. No markdown fences, no explanations.
- Embed the FULL Python script via textwrap.dedent in a fixture
- Replace $(params.X) and $(results.X.path) with test values using str.replace()
- Run the script as a subprocess (subprocess.run) — do NOT import it as a module
- Mock network calls by patching at the module level inside the script if needed, \
  OR by providing mock HTTP server, OR by intercepting at the subprocess level
- For scripts that use urllib/requests/http: mock via environment variables or \
  create a simple mock server
- Tests must NOT need a real network, Jenkins, Kubernetes cluster, etc.
- Each test method must test ONE specific behavior
- Test all code paths: success, failure, missing inputs, invalid data
- Verify exit codes, stdout output, stderr output, and result files
- Use tmp_path fixture for all file I/O
- Group tests into classes: TestHappyPath, TestErrorPaths, TestEdgeCases

TEST ORGANIZATION — CRITICAL FOR REVIEWABILITY:
Organize tests into clearly named CLASSES that act as suites. This makes the file \
easy to review in a PR.

Structure:
```
class TestHappyPath:
    # Suite: successful execution paths
    def test_success_processes_all_items(self, script_env): ...
    def test_success_writes_result_file(self, script_env): ...

class TestErrorHandling:
    # Suite: error conditions and failures
    def test_error_missing_required_param(self, script_env): ...
    def test_error_kubectl_returns_error(self, script_env): ...

class TestEdgeCases:
    # Suite: boundary conditions and unusual inputs
    def test_edge_empty_json_response(self, script_env): ...
    def test_edge_missing_optional_fields(self, script_env): ...
```

Rules:
- Each class is a SUITE with a docstring explaining what it covers
- Test method names should be descriptive: `test_error_fails_when_token_empty`
- Keep each test FOCUSED — test ONE behavior, not five
- Maximum 15-20 test methods per file. Prioritize the most important code paths
- Each test should be readable in isolation for easy PR review

PYTHON SCRIPT SPECIFICS:
- Scripts may use #!/usr/libexec/platform-python — run with sys.executable instead
- Scripts may read env vars via os.getenv() — set them in the env dict
- Scripts may use sys.argv — pass args to subprocess.run
- Scripts may write to $(results.X.path) — verify file content after execution
- Scripts may use urllib, http.client, requests — these need mocking
- For scripts with sys.exit(N), verify the subprocess returncode == N
"""

PYTEST_GENERATE_TEMPLATE = """\
Generate pytest unit tests for the Python script(s) in this Tekton {kind}.

## Resource YAML
```yaml
{yaml_content}
```

## Resource Info
- Kind: {kind}
- Name: {name}
- File: {source_path}
- Scripts to test: {script_info}

## setup (fixture) must:
1. Embed the EXACT script in a fixture using textwrap.dedent
2. Replace $(params.X) with concrete test values
3. Replace $(results.X.path) with tmp_path file paths
4. Set environment variables the script reads
5. Return (script_file, env, tmp_path)

## Run strategy
- Execute the script via subprocess.run([sys.executable, script_file])
- Capture stdout, stderr, returncode
- Use timeout=30 to prevent hangs

## Tekton variable replacements
{tekton_replacements}

## Environment variables to set
{env_section}

## Results to verify
{result_verification}

## Test cases — test the ACTUAL LOGIC
{test_cases}

## Edge cases
- Missing/empty required environment variables
- Network calls failing (mock or skip)
- Invalid input data (malformed JSON, empty strings)
- Scripts with sys.exit(): verify returncode matches exit code
- Result files: verify content is written correctly

Output ONLY the .py test file. No markdown, no explanations.
"""


def _build_python_test_cases(resource, scripts: list[tuple[str, str]]) -> str:
    """Build test case descriptions for Python scripts."""
    cases = []
    for step_name, script in scripts:
        if _detect_script_language(script) != "python":
            continue

        cases.append(f"\n#### Step: {step_name}")

        # Extract branches
        for match in re.finditer(r'^\s*if\s+(.+?):', script, re.MULTILINE):
            cond = match.group(1).strip()[:80]
            cases.append(f"  - Branch: `{cond}` → test TRUE and FALSE")

        # Extract try/except
        if "try:" in script:
            cases.append("- Test try/except: success path AND exception path")
        if "sys.exit(" in script:
            exit_codes = set(re.findall(r'sys\.exit\((\d+)\)', script))
            if exit_codes:
                cases.append(f"- Test exit codes: {', '.join(sorted(exit_codes))}")
        if "print(" in script:
            cases.append("- Verify stdout print messages match exact strings from script")
        if "urllib" in script or "requests" in script or "http" in script:
            cases.append("- Mock HTTP calls: test success response and failure response")
        if "os.getenv" in script or "os.environ" in script:
            cases.append("- Test with missing environment variables")
        if "sys.argv" in script:
            cases.append("- Test with different command-line arguments")
        if "$(results." in script or "$(step.results." in script:
            cases.append("- Verify result files written with correct content")

        cases.append("- Test happy path (all inputs valid)")
        cases.append("- Test with missing/invalid inputs")

    return "\n".join(cases) if cases else "- Test the main execution path\n- Test error handling"


def _build_python_tekton_replacements(resource, scripts: list[tuple[str, str]]) -> str:
    """Extract $(params.X) and $(results.X.path) patterns from Python scripts."""
    lines = []
    for _, script in scripts:
        if _detect_script_language(script) != "python":
            continue
        for m in sorted(set(re.findall(r'\$\(params\.([a-zA-Z0-9_-]+)\)', script))):
            lines.append(f'- `script_content = script_content.replace("$(params.{m})", "test-{m}-value")`')
        for m in sorted(set(re.findall(r'\$\(results\.([a-zA-Z0-9_-]+)\.path\)', script))):
            lines.append(f'- `script_content = script_content.replace("$(results.{m}.path)", str(tmp_path / "{m}"))`')
        for m in sorted(set(re.findall(r'\$\(step\.results\.([a-zA-Z0-9_-]+)\.path\)', script))):
            lines.append(
                f'- `script_content = script_content.replace('
                f'"$(step.results.{m}.path)", str(tmp_path / "{m}"))`'
            )
    return "\n".join(lines) if lines else "- No Tekton variable replacements needed"


def build_pytest_prompt(resource, yaml_content: str) -> str:
    """Build pytest generation prompt for Python scripts in a Tekton resource."""
    scripts = resource.embedded_scripts
    python_scripts = [(name, s) for name, s in scripts if _detect_script_language(s) == "python"]

    script_info = ", ".join(f"'{name}'" for name, _ in python_scripts)

    return PYTEST_GENERATE_TEMPLATE.format(
        kind=resource.kind,
        name=resource.name,
        source_path=resource.source_path,
        yaml_content=yaml_content,
        script_info=script_info,
        tekton_replacements=_build_python_tekton_replacements(resource, python_scripts),
        env_section=_build_env_mock_section(resource),
        result_verification=_build_result_verification(resource),
        test_cases=_build_python_test_cases(resource, python_scripts),
    )
