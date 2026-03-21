"""LLM-powered test generator for Tekton resources.

Generates BATS tests for bash scripts and pytest tests for Python scripts.
Includes:
- Autonomous fix loop with progressive strategy
- Failure diagnosis and reflection before fixing
- Multi-agent separation (generator vs evaluator vs fixer)
- Flaky test detection
- Coverage analysis
- Episodic memory integration
- Code bug detection
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path

from tektonit.llm import LLMProvider, LLMResponse
from tektonit.parser import TektonResource
from tektonit.prompts import (
    BATS_SYSTEM_PROMPT,
    PYTEST_SYSTEM_PROMPT,
    build_bats_prompt,
    build_propose_prompt,
    build_pytest_prompt,
    get_script_languages,
    has_testable_scripts,
)

log = logging.getLogger("tektonit")

SANITY_CHECK_DIR = "sanity-check"
DEFAULT_MAX_FIX_ATTEMPTS = 10
FLAKY_CHECK_RUNS = 2  # extra runs to detect flakiness


# -- Failure classification --------------------------------------------------

# Failure types for diagnosis
FAILURE_MOCK_MISMATCH = "mock_mismatch"
FAILURE_ASSERTION_MISMATCH = "assertion_mismatch"
FAILURE_SYNTAX_ERROR = "syntax_error"
FAILURE_TIMEOUT = "timeout"
FAILURE_IMPORT_ERROR = "import_error"
FAILURE_SCRIPT_BUG = "script_bug"
FAILURE_RUNTIME_ERROR = "runtime_error"
FAILURE_UNKNOWN = "unknown"


def _diagnose_failure(test_output: str, language: str) -> dict:
    """Classify a test failure into a category with actionable diagnosis.

    Returns dict with:
      - type: failure category string
      - summary: one-line human-readable summary
      - details: list of relevant error lines
      - fix_hint: suggested fix direction for the LLM
    """
    lines = test_output.splitlines()
    error_lines = [
        line
        for line in lines
        if any(
            m in line
            for m in (
                "not ok",
                "FAILED",
                "ERROR",
                "Error",
                "assert",
                "AssertionError",
                "command not found",
                "No such file",
                "syntax error",
                "SyntaxError",
                "ImportError",
                "ModuleNotFoundError",
                "TIMEOUT",
                "Permission denied",
                "unexpected",
                "mock",
            )
        )
    ]

    output_lower = test_output.lower()

    # Timeout
    if "timeout" in output_lower:
        return {
            "type": FAILURE_TIMEOUT,
            "summary": "Tests timed out — likely an infinite loop or unmocked sleep",
            "details": error_lines[:5],
            "fix_hint": (
                "A test is hanging. Check for: unmocked sleep commands, "
                "while/until loops without mock exit conditions, "
                "network calls hitting real endpoints. "
                "Mock sleep as no-op, ensure loop exit conditions trigger immediately."
            ),
        }

    # Import / module errors
    if "importerror" in output_lower or "modulenotfounderror" in output_lower:
        return {
            "type": FAILURE_IMPORT_ERROR,
            "summary": "Import error — missing module or wrong import path",
            "details": error_lines[:5],
            "fix_hint": (
                "A module import is failing. Check if the test uses modules "
                "not available in the test environment. Use only stdlib imports "
                "or mock the missing module."
            ),
        }

    # Syntax errors
    if "syntaxerror" in output_lower or "syntax error" in output_lower:
        return {
            "type": FAILURE_SYNTAX_ERROR,
            "summary": "Syntax error in test or script",
            "details": error_lines[:5],
            "fix_hint": (
                "Fix the syntax error. Check for: unmatched quotes, "
                "missing parentheses, invalid bash/python syntax, "
                "heredoc terminator issues."
            ),
        }

    # Command not found (mock missing)
    if "command not found" in output_lower or "no such file" in output_lower:
        return {
            "type": FAILURE_MOCK_MISMATCH,
            "summary": "External command not mocked or mock script not found",
            "details": error_lines[:5],
            "fix_hint": (
                "An external command is being called but has no mock. "
                "Read the script line by line and create a mock for EVERY "
                "external command. Ensure $MOCK_BIN is prepended to PATH. "
                "Check chmod +x on mock scripts."
            ),
        }

    # Assertion mismatches
    if language == "bash":
        assertion_markers = ["[[ ", "[ ", "expected", "got", "not ok"]
    else:
        assertion_markers = ["assert", "AssertionError", "!=", "expected", "got"]

    assertion_failures = [line for line in error_lines if any(m in line for m in assertion_markers)]
    if assertion_failures:
        return {
            "type": FAILURE_ASSERTION_MISMATCH,
            "summary": "Assertions don't match actual output",
            "details": assertion_failures[:10],
            "fix_hint": (
                "The test assertions don't match what the script actually outputs. "
                "Read the EXACT echo/printf/print statements in the script and "
                "copy the exact strings into assertions. Check: "
                "1) Mock return values match what the script expects to parse "
                "2) Exit codes match the actual script behavior "
                "3) Output strings are copied character-for-character from the script"
            ),
        }

    # Runtime errors
    if "error" in output_lower or "exception" in output_lower:
        return {
            "type": FAILURE_RUNTIME_ERROR,
            "summary": "Runtime error during test execution",
            "details": error_lines[:10],
            "fix_hint": (
                "A runtime error occurred. Examine the traceback/error output "
                "carefully. Common causes: missing environment variables, "
                "file paths that don't exist, wrong mock data format, "
                "JSON parsing errors from invalid mock data."
            ),
        }

    return {
        "type": FAILURE_UNKNOWN,
        "summary": "Unclassified test failure",
        "details": error_lines[:10],
        "fix_hint": "Analyze the test output carefully and fix the root cause.",
    }


# -- Episodic memory helpers -------------------------------------------------


def _extract_script_features(resource: TektonResource, language: str) -> list[str]:
    """Extract key features from scripts for episodic memory matching."""
    features = []
    for _, script in resource.embedded_scripts:
        if "jq " in script:
            features.append("jq")
        if "curl " in script:
            features.append("curl")
        if "kubectl " in script or "oc " in script:
            features.append("kubectl")
        if "oras " in script:
            features.append("oras")
        if "git " in script:
            features.append("git")
        if "while " in script or "until " in script:
            features.append("loop")
        if "urllib" in script or "requests" in script:
            features.append("http")
        if "json" in script.lower():
            features.append("json")
        if "base64" in script:
            features.append("base64")
        if "retry" in script.lower() or "attempt" in script.lower():
            features.append("retry")
    return list(set(features))


def _build_memory_context(state_store, resource: TektonResource, language: str) -> str:
    """Build episodic memory context to inject into prompts."""
    if state_store is None:
        return ""

    features = _extract_script_features(resource, language)
    patterns = state_store.get_relevant_patterns(language, features)

    if not patterns:
        return ""

    lines = ["\n## LESSONS FROM PAST FAILURES (episodic memory)"]
    lines.append("The agent has encountered these issues before. AVOID repeating them:")
    for p in patterns[:5]:
        lines.append(f"- [{p.failure_type}] {p.description} → Fix: {p.fix_that_worked} (seen {p.occurrences}x)")
    return "\n".join(lines)


def _build_pr_feedback_context(state_store, resource: TektonResource) -> str:
    """Build PR feedback context to inject into prompts."""
    if state_store is None:
        return ""

    feedback = state_store.get_pr_feedback(resource.kind)
    if not feedback:
        return ""

    lines = ["\n## FEEDBACK FROM PR REVIEWS"]
    lines.append("Previous PR reviews flagged these issues. Address them proactively:")
    for fb in feedback[:3]:
        lines.append(f"- {fb.feedback_text}")
    return "\n".join(lines)


def _record_learned_pattern(
    state_store,
    language: str,
    features: list[str],
    diagnosis: dict,
    fix_worked: bool,
    fix_description: str,
):
    """Record a failure pattern in episodic memory."""
    if state_store is None or not fix_worked:
        return

    # Build a pattern key from language + most relevant feature
    feature_key = features[0] if features else "general"
    pattern_key = f"{language}:{feature_key}:{diagnosis['type']}"

    state_store.record_failure_pattern(
        pattern_key=pattern_key,
        failure_type=diagnosis["type"],
        description=diagnosis["summary"],
        fix_that_worked=fix_description,
    )


# -- System prompts for different roles --------------------------------------

# The evaluator is skeptical — it looks for problems the generator missed
EVALUATOR_SYSTEM_PROMPT_BATS = """\
You are a SKEPTICAL test reviewer. Your job is to find problems in BATS test files.

You are NOT the author — you are reviewing someone else's work. Be critical.

Check for these categories of bugs (in priority order):

1. MOCK GAPS: Commands in the script that have no mock, or mocks that don't match
   the actual invocation pattern (wrong args, wrong subcommand).
2. ASSERTION DRIFT: Assertions that don't match the script's actual echo/printf output.
   The assertion must use the EXACT string from the script, not a paraphrase.
3. MISSING BRANCHES: if/elif/else/case branches in the script that have no @test.
4. HANGING RISKS: Loops without mock exit conditions, unmocked sleep/date commands.
5. MOCK DATA BUGS: Invalid JSON in mock data, missing jq fields the script reads.
6. PATH/ENV GAPS: Tekton vars not sed-replaced, env vars not exported.

Output a structured diagnosis:
```
ISSUES FOUND:
1. [CATEGORY] Description of issue + exact line reference
2. [CATEGORY] ...

SEVERITY: critical|moderate|minor
```

If no issues found, output: `NO ISSUES FOUND`
"""

EVALUATOR_SYSTEM_PROMPT_PYTEST = """\
You are a SKEPTICAL test reviewer. Your job is to find problems in pytest test files.

You are NOT the author — you are reviewing someone else's work. Be critical.

Check for these categories of bugs (in priority order):

1. MOCK GAPS: External calls (urllib, subprocess, http) not properly mocked.
2. ASSERTION DRIFT: Assertions that don't match the script's actual print() output.
3. MISSING BRANCHES: if/elif/else/try/except branches with no test.
4. SUBPROCESS ISSUES: Script not run via subprocess.run, or missing timeout.
5. ENV GAPS: Missing environment variables, Tekton vars not replaced.
6. FIXTURE BUGS: Script content not properly embedded, wrong replacements.

Output a structured diagnosis:
```
ISSUES FOUND:
1. [CATEGORY] Description of issue
2. [CATEGORY] ...

SEVERITY: critical|moderate|minor
```

If no issues found, output: `NO ISSUES FOUND`
"""


# -- Code extraction ---------------------------------------------------------


def _extract_code(text: str, language: str = "bats") -> str:
    """Extract code from LLM response, stripping markdown fences if present."""
    if language == "python":
        return _extract_python_code(text)
    return _extract_bats_code(text)


def _extract_bats_code(text: str) -> str:
    """Extract BATS code from LLM response."""
    for lang in ("bats", "bash", "sh", ""):
        pattern = re.compile(rf"```{lang}\s*\n(.*?)```", re.DOTALL)
        matches = pattern.findall(text)
        if matches:
            return max(matches, key=len).strip()

    stripped = text.strip()
    if stripped.startswith("#!/"):
        return stripped

    shebang_match = re.search(r"(#!/usr/bin/env bats\n.*)", text, re.DOTALL)
    if shebang_match:
        return shebang_match.group(1).strip()

    return stripped


def _extract_python_code(text: str) -> str:
    """Extract Python test code from LLM response."""
    for lang in ("python", "py", ""):
        pattern = re.compile(rf"```{lang}\s*\n(.*?)```", re.DOTALL)
        matches = pattern.findall(text)
        if matches:
            return max(matches, key=len).strip()

    stripped = text.strip()
    # Python test files typically start with imports
    if stripped.startswith(("import ", "from ", '"""', "#!/")):
        return stripped

    # Find first import line
    import_match = re.search(r"((?:import |from ).*)", text, re.DOTALL)
    if import_match:
        return import_match.group(1).strip()

    return stripped


# -- Syntax validation -------------------------------------------------------


def _validate_bats_syntax(code: str) -> tuple[bool, str]:
    """Validate BATS file has valid bash syntax and structure."""
    errors = []

    if not code.strip().startswith("#!/"):
        errors.append("Missing shebang (#!/usr/bin/env bats)")

    test_count = len(re.findall(r"@test\s+\"", code))
    if test_count == 0:
        errors.append("No @test blocks found")

    if "setup()" not in code:
        errors.append("Missing setup() function")
    if "teardown()" not in code:
        errors.append("Missing teardown() function")

    open_braces = code.count("{")
    close_braces = code.count("}")
    if abs(open_braces - close_braces) > 2:
        errors.append(f"Unbalanced braces: {open_braces} open, {close_braces} close")

    try:
        bash_code = re.sub(r"@test\s+\"[^\"]*\"\s*\{", "___bats_test() {", code)
        result = subprocess.run(
            ["bash", "-n"],
            input=bash_code,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "___bats_test" not in stderr:
                errors.append(f"Bash syntax error: {stderr}")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    if errors:
        return False, "; ".join(errors)
    return True, ""


def _validate_pytest_syntax(code: str) -> tuple[bool, str]:
    """Validate Python test file has valid syntax and structure."""
    errors = []

    if "def test_" not in code and "class Test" not in code:
        errors.append("No test functions or classes found")

    if "import" not in code:
        errors.append("No import statements found")

    try:
        compile(code, "<test>", "exec")
    except SyntaxError as e:
        errors.append(f"Python syntax error: {e}")

    if errors:
        return False, "; ".join(errors)
    return True, ""


def validate_syntax(code: str, language: str) -> tuple[bool, str]:
    """Validate test file syntax based on language."""
    if language == "python":
        return _validate_pytest_syntax(code)
    return _validate_bats_syntax(code)


# -- Cross-platform fixes ---------------------------------------------------


def _fix_cross_platform(code: str) -> str:
    """Fix known cross-platform issues that break on macOS bash 3.2."""
    code = re.sub(r"&>>\s*(\S+)", r">> \1 2>&1", code)

    lines = code.split("\n")
    in_heredoc = False
    for i, line in enumerate(lines):
        if "SCRIPT_EOF" in line and "<<" in line:
            in_heredoc = True
            continue
        if line.strip() == "SCRIPT_EOF":
            in_heredoc = False
            continue
        if in_heredoc and line.strip() == "#!/bin/bash":
            lines[i] = line.replace("#!/bin/bash", "#!/usr/bin/env bash")
    code = "\n".join(lines)

    return code


# -- Test runners ------------------------------------------------------------


def _run_bats(test_file: str, timeout: int = 120) -> tuple[bool, str]:
    """Run a BATS test file and return (passed, output)."""
    try:
        result = subprocess.run(
            ["bats", test_file],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT: test exceeded timeout (possible infinite loop)"
    except FileNotFoundError:
        return False, "bats not installed"


def _run_pytest(test_file: str, timeout: int = 120) -> tuple[bool, str]:
    """Run a pytest test file and return (passed, output)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file, "-v", "--tb=short", "--no-header"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT: test exceeded timeout"
    except FileNotFoundError:
        return False, "pytest not installed"


def run_tests(test_file: str, language: str, timeout: int = 120) -> tuple[bool, str]:
    """Run tests based on language."""
    if language == "python":
        return _run_pytest(test_file, timeout)
    return _run_bats(test_file, timeout)


# -- Flaky test detection ----------------------------------------------------


def _check_flaky(test_file: str, language: str, runs: int = FLAKY_CHECK_RUNS) -> tuple[bool, str]:
    """Run tests multiple times to detect flakiness.

    Returns (is_stable, flaky_output).
    If all runs pass, returns (True, "").
    If any run fails, returns (False, output_of_failing_run).
    """
    for i in range(runs):
        passed, output = run_tests(test_file, language)
        if not passed:
            log.warning("    Flaky detection: run %d/%d FAILED", i + 1, runs)
            return False, output
    return True, ""


# -- Coverage analysis -------------------------------------------------------


def _count_script_branches(resource: TektonResource, language: str) -> int:
    """Count the number of branches in the resource's scripts."""
    count = 0
    for _, script in resource.embedded_scripts:
        if language == "python":
            count += len(re.findall(r"^\s*if\s+", script, re.MULTILINE))
            count += len(re.findall(r"^\s*elif\s+", script, re.MULTILINE))
            count += len(re.findall(r"^\s*else\s*:", script, re.MULTILINE))
            count += len(re.findall(r"^\s*except\s+", script, re.MULTILINE))
        else:
            count += len(re.findall(r"\bif\s+\[", script))
            count += len(re.findall(r"\belif\s+\[", script))
            count += len(re.findall(r"\belse\b", script))
            count += len(re.findall(r"\bcase\s+", script))
    return max(count, 1)


def _count_test_blocks(code: str, language: str) -> int:
    """Count the number of test blocks in the generated code."""
    if language == "python":
        return len(re.findall(r"def test_", code))
    return len(re.findall(r'@test\s+"', code))


def _analyze_coverage(code: str, resource: TektonResource, language: str) -> dict:
    """Analyze test coverage ratio.

    Returns dict with:
      - branch_count: number of branches in script
      - test_count: number of tests generated
      - ratio: tests/branches
      - sufficient: bool
    """
    branches = _count_script_branches(resource, language)
    tests = _count_test_blocks(code, language)
    ratio = tests / branches if branches > 0 else 1.0

    return {
        "branch_count": branches,
        "test_count": tests,
        "ratio": ratio,
        "sufficient": ratio >= 0.5 and tests >= 3,
    }


def _request_more_tests(
    resource: TektonResource,
    code: str,
    coverage: dict,
    language: str,
    provider: LLMProvider,
) -> str:
    """Ask LLM to add more tests to improve coverage."""
    yaml_content = Path(resource.source_path).read_text()
    sys_prompt = PYTEST_SYSTEM_PROMPT if language == "python" else BATS_SYSTEM_PROMPT
    ext = "py" if language == "python" else "bats"

    prompt = f"""\
The following tests for Tekton {resource.kind} "{resource.name}" have LOW COVERAGE.

Coverage: {coverage["test_count"]} tests for {coverage["branch_count"]} branches \
(ratio: {coverage["ratio"]:.1%}).

## Resource YAML
```yaml
{yaml_content}
```

## Current tests
```{ext}
{code}
```

## Instructions
1. Identify UNTESTED branches/paths in the script that have no test
2. Add NEW test blocks to cover them
3. Return the COMPLETE file with BOTH existing AND new tests
4. Do NOT remove or modify existing tests — only ADD new ones
5. Each new test must have precise assertions (exact output strings, exit codes)

Output ONLY the complete .{ext} file.
"""
    try:
        response = provider.generate(sys_prompt, prompt)
        new_code = _extract_code(response.content, language)
        new_tests = _count_test_blocks(new_code, language)
        if new_tests > coverage["test_count"]:
            return new_code
    except Exception as e:
        log.warning("Coverage improvement failed: %s", e)
    return code


# -- Self-review (evaluator agent) -------------------------------------------


def _evaluate_tests(
    code: str,
    resource: TektonResource,
    language: str,
    provider: LLMProvider,
) -> tuple[str, bool]:
    """Evaluate tests using the EVALUATOR role (different persona from generator).

    Returns (evaluation_text, has_critical_issues).
    """
    yaml_content = Path(resource.source_path).read_text()
    ext = "py" if language == "python" else "bats"
    eval_prompt = EVALUATOR_SYSTEM_PROMPT_PYTEST if language == "python" else EVALUATOR_SYSTEM_PROMPT_BATS

    prompt = f"""\
Review this test file for a Tekton {resource.kind} "{resource.name}".

## Resource YAML
```yaml
{yaml_content}
```

## Test file to review
```{ext}
{code}
```

Find ALL issues. Be thorough and skeptical.
"""
    try:
        response = provider.generate(eval_prompt, prompt)
        text = response.content
        has_critical = "critical" in text.lower() and "no issues" not in text.lower()
        return text, has_critical
    except Exception as e:
        log.warning("Evaluation failed (non-fatal): %s", e)
        return "", False


def _fix_from_evaluation(
    code: str,
    resource: TektonResource,
    evaluation: str,
    language: str,
    provider: LLMProvider,
) -> str:
    """Fix tests based on evaluator feedback (different from runtime fix)."""
    yaml_content = Path(resource.source_path).read_text()
    sys_prompt = PYTEST_SYSTEM_PROMPT if language == "python" else BATS_SYSTEM_PROMPT
    ext = "py" if language == "python" else "bats"

    prompt = f"""\
A code reviewer found issues in these tests. Fix ALL of them.

## Resource YAML
```yaml
{yaml_content}
```

## Current tests
```{ext}
{code}
```

## Reviewer feedback
{evaluation}

## Instructions
- Fix EVERY issue the reviewer identified
- Do NOT introduce new problems
- Return the COMPLETE fixed .{ext} file

Output ONLY the fixed file.
"""
    try:
        response = provider.generate(sys_prompt, prompt)
        fixed = _extract_code(response.content, language)
        valid, _ = validate_syntax(fixed, language)
        if valid:
            return fixed
    except Exception as e:
        log.warning("Fix from evaluation failed: %s", e)
    return code


# -- Fix loop ----------------------------------------------------------------


def _fix_with_llm(
    resource: TektonResource,
    test_code: str,
    test_output: str,
    language: str,
    provider: LLMProvider,
    diagnosis: dict | None = None,
    memory_context: str = "",
) -> str | None:
    """Ask LLM to fix failing tests with diagnosis context. Returns fixed code or None."""
    yaml_content = Path(resource.source_path).read_text()
    sys_prompt = PYTEST_SYSTEM_PROMPT if language == "python" else BATS_SYSTEM_PROMPT

    fail_lines = [
        line
        for line in test_output.splitlines()
        if any(marker in line for marker in ("not ok", "FAILED", "ERROR", "# ", "AssertionError", "assert "))
    ]

    # Build diagnosis section
    diagnosis_section = ""
    if diagnosis:
        diagnosis_section = f"""
## Failure Diagnosis (automated analysis)
- **Type**: {diagnosis["type"]}
- **Summary**: {diagnosis["summary"]}
- **Fix direction**: {diagnosis["fix_hint"]}
"""

    ext = "py" if language == "python" else "bats"
    fix_prompt = f"""\
The following tests for Tekton {resource.kind} "{resource.name}" are FAILING.
Fix them so they pass. Return the COMPLETE corrected .{ext} file.

## Resource YAML
```yaml
{yaml_content}
```

## Current tests (FAILING)
```{ext}
{test_code}
```

## Test output (errors)
```
{chr(10).join(fail_lines) if fail_lines else test_output[-3000:]}
```
{diagnosis_section}
{memory_context}
## Instructions
- Analyze the error output carefully
- Fix the ROOT CAUSE — do not just silence errors
- The tests must exercise the REAL script logic, not be trivially passing
- Return the COMPLETE fixed file — not just changed parts
- If the error is in the ORIGINAL SCRIPT (not the test), note it in a comment \
  at the top: # CODE_ISSUE: <description>

Output ONLY the fixed .{ext} file. No markdown, no explanations.
"""
    try:
        response = provider.generate(sys_prompt, fix_prompt)
        code = _extract_code(response.content, language)
        valid, err = validate_syntax(code, language)
        if not valid:
            log.warning("LLM fix has syntax issues: %s", err)
        return code
    except Exception as e:
        log.error("LLM fix attempt failed: %s", e)
        return None


def _regenerate_with_different_approach(
    resource: TektonResource,
    test_output: str,
    language: str,
    provider: LLMProvider,
    memory_context: str = "",
) -> str | None:
    """Full regeneration with a different approach (used in progressive fix strategy).

    Instead of fixing the existing code, start fresh with additional context
    about what went wrong.
    """
    yaml_content = Path(resource.source_path).read_text()
    sys_prompt = PYTEST_SYSTEM_PROMPT if language == "python" else BATS_SYSTEM_PROMPT
    ext = "py" if language == "python" else "bats"

    prompt = f"""\
Previous test generation for Tekton {resource.kind} "{resource.name}" FAILED \
after multiple fix attempts. Generate COMPLETELY NEW tests from scratch.

## Resource YAML
```yaml
{yaml_content}
```

## What went wrong in previous attempts
```
{test_output[-2000:]}
```

## CRITICAL — learn from the failures above:
1. Study the error output to understand what mocking strategy failed
2. Use a DIFFERENT mocking approach than whatever caused the errors
3. Start simple — get basic happy-path tests passing first
4. Add error-path tests only after happy path works
5. Double-check every mock matches the script's EXACT command invocations
6. Double-check every assertion matches the script's EXACT output strings
{memory_context}

Output ONLY the .{ext} file. No markdown, no explanations.
"""
    try:
        response = provider.generate(sys_prompt, prompt)
        code = _extract_code(response.content, language)
        valid, _ = validate_syntax(code, language)
        if valid:
            return code
    except Exception as e:
        log.error("Regeneration failed: %s", e)
    return None


def _rewrite_mocks(
    resource: TektonResource,
    test_code: str,
    test_output: str,
    language: str,
    provider: LLMProvider,
) -> str | None:
    """Rewrite ALL mocks from scratch while keeping test structure."""
    yaml_content = Path(resource.source_path).read_text()
    sys_prompt = PYTEST_SYSTEM_PROMPT if language == "python" else BATS_SYSTEM_PROMPT
    ext = "py" if language == "python" else "bats"

    prompt = f"""\
The tests for Tekton {resource.kind} "{resource.name}" keep failing due to \
mock issues. REWRITE ALL MOCKS from scratch while keeping the test structure.

## Resource YAML
```yaml
{yaml_content}
```

## Current tests (mock issues)
```{ext}
{test_code}
```

## Error output
```
{test_output[-2000:]}
```

## Instructions
1. Keep ALL @test blocks / test functions as-is
2. COMPLETELY REWRITE the setup/mocking:
   - Re-read the script line by line
   - List every external command call with exact arguments
   - Create fresh mocks matching the EXACT invocation patterns
   - Ensure mock return data has the EXACT fields the script reads
3. For BATS: rebuild all mock scripts in $MOCK_BIN from scratch
4. For pytest: rebuild all fixtures, mock servers, patching from scratch
5. Return the COMPLETE file

Output ONLY the fixed .{ext} file.
"""
    try:
        response = provider.generate(sys_prompt, prompt)
        code = _extract_code(response.content, language)
        valid, _ = validate_syntax(code, language)
        if valid:
            return code
    except Exception as e:
        log.error("Mock rewrite failed: %s", e)
    return None


def _detect_code_issue(test_code: str, test_output: str) -> str | None:
    """Check if the LLM flagged a code issue (not a test issue).

    Returns description of the code issue, or None.
    """
    # Check if the LLM added a CODE_ISSUE marker
    for line in test_code.splitlines()[:10]:
        if "CODE_ISSUE:" in line:
            return line.split("CODE_ISSUE:", 1)[1].strip()

    # Heuristic: if test output shows the script itself errors consistently
    # on the same line across multiple runs, it's likely a code bug
    return None


# -- Generation pipeline -----------------------------------------------------


def generate_bats_test(
    resource: TektonResource,
    provider: LLMProvider,
    extra_context: str = "",
) -> tuple[str, LLMResponse]:
    """Generate BATS tests for bash scripts in a Tekton resource."""
    yaml_content = Path(resource.source_path).read_text()
    user_prompt = build_bats_prompt(resource, yaml_content)
    if extra_context:
        user_prompt += extra_context
    response = provider.generate(BATS_SYSTEM_PROMPT, user_prompt)
    code = _extract_bats_code(response.content)

    valid, err = _validate_bats_syntax(code)
    if not valid:
        log.warning("Generated BATS has syntax issues: %s", err)

    code = _fix_cross_platform(code)

    return code, response


def generate_pytest_test(
    resource: TektonResource,
    provider: LLMProvider,
    extra_context: str = "",
) -> tuple[str, LLMResponse]:
    """Generate pytest tests for Python scripts in a Tekton resource."""
    yaml_content = Path(resource.source_path).read_text()
    user_prompt = build_pytest_prompt(resource, yaml_content)
    if extra_context:
        user_prompt += extra_context
    response = provider.generate(PYTEST_SYSTEM_PROMPT, user_prompt)
    code = _extract_python_code(response.content)

    valid, err = _validate_pytest_syntax(code)
    if not valid:
        log.warning("Generated pytest has syntax issues: %s", err)

    return code, response


def generate_test(
    resource: TektonResource,
    provider: LLMProvider,
    language: str,
    extra_context: str = "",
) -> tuple[str, LLMResponse]:
    """Generate tests based on script language."""
    if language == "python":
        return generate_pytest_test(resource, provider, extra_context)
    return generate_bats_test(resource, provider, extra_context)


# -- Autonomous pipeline: generate → evaluate → run → fix → detect ----------


def generate_and_fix(
    resource: TektonResource,
    provider: LLMProvider,
    language: str,
    max_fix_attempts: int = DEFAULT_MAX_FIX_ATTEMPTS,
    output_dir: Path | None = None,
    state_store=None,
) -> dict:
    """Full autonomous pipeline with all 8 intelligence capabilities.

    Pipeline:
      1. Query episodic memory + PR feedback for context
      2. Generate tests
      3. Evaluate with skeptical evaluator (multi-agent)
      4. Fix evaluator issues
      5. Analyze coverage, request more tests if low
      6. Run tests
      7. Progressive fix loop (targeted → rewrite mocks → full regen)
      8. Flaky detection (run 2 extra times)
      9. Record learned patterns to episodic memory

    Returns a result dict with:
      - test_code: final test content
      - test_file: path to the test file
      - passed: whether tests pass
      - fix_attempts: number of fix attempts made
      - code_issue: description if a code bug was detected
      - language, test_type, test_output, usage
      - coverage: coverage analysis dict
      - flaky: whether flakiness was detected
    """
    sc_dir = output_dir or _sanity_check_dir(resource)
    sc_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize_name(resource.name)

    ext = "py" if language == "python" else "bats"
    test_type = "pytest" if language == "python" else "bats"
    test_file = sc_dir / f"{safe_name}_unit-tests.{ext}"

    features = _extract_script_features(resource, language)

    # ── Step 1: Build context from episodic memory + PR feedback ──
    memory_context = _build_memory_context(state_store, resource, language)
    pr_context = _build_pr_feedback_context(state_store, resource)
    extra_context = memory_context + pr_context

    # ── Step 2: Generate ──
    log.info("  [gen] %s/%s (%s)", resource.kind, resource.name, test_type)
    try:
        code, response = generate_test(resource, provider, language, extra_context)
    except Exception as e:
        log.error("    Generation failed: %s", e)
        return {
            "resource": resource.name,
            "kind": resource.kind,
            "status": "generation_error",
            "error": str(e),
            "language": language,
            "test_type": test_type,
        }

    tokens = response.usage or {}
    log.info(
        "    Generated (%d input + %d output tokens)",
        tokens.get("input_tokens", 0),
        tokens.get("output_tokens", 0),
    )

    # ── Step 3: Evaluate with skeptical evaluator (multi-agent separation) ──
    log.info("    [eval] Running evaluator review...")
    evaluation, has_critical = _evaluate_tests(code, resource, language, provider)
    if has_critical:
        log.info("    [eval] Critical issues found, fixing before run...")
        code = _fix_from_evaluation(code, resource, evaluation, language, provider)

    # ── Step 4: Coverage analysis ──
    coverage = _analyze_coverage(code, resource, language)
    log.info(
        "    [cov] %d tests for %d branches (%.0f%%)",
        coverage["test_count"],
        coverage["branch_count"],
        coverage["ratio"] * 100,
    )
    if not coverage["sufficient"]:
        log.info("    [cov] Low coverage, requesting more tests...")
        code = _request_more_tests(resource, code, coverage, language, provider)
        coverage = _analyze_coverage(code, resource, language)

    # Apply cross-platform fixes for BATS
    if language == "bash":
        code = _fix_cross_platform(code)

    test_file.write_text(code)

    # ── Step 5: Run tests ──
    passed, output = run_tests(str(test_file), language)
    log.info("    Initial run: %s", "PASS" if passed else "FAIL")

    # ── Step 6: Progressive fix loop ──
    attempt = 0
    last_diagnosis = None
    while not passed and attempt < max_fix_attempts:
        attempt += 1

        # Diagnose the failure (reflection step)
        diagnosis = _diagnose_failure(output, language)
        last_diagnosis = diagnosis
        log.info(
            "    Fix attempt %d/%d [%s: %s]",
            attempt,
            max_fix_attempts,
            diagnosis["type"],
            diagnosis["summary"],
        )

        fixed = None

        # Progressive strategy: escalate approach based on attempt number
        if attempt <= 3:
            # Phase 1: Targeted fix with diagnosis context
            fixed = _fix_with_llm(
                resource,
                code,
                output,
                language,
                provider,
                diagnosis=diagnosis,
                memory_context=memory_context,
            )
        elif attempt <= 6:
            # Phase 2: Rewrite all mocks from scratch
            log.info("    [escalate] Rewriting mocks from scratch...")
            fixed = _rewrite_mocks(resource, code, output, language, provider)
        elif attempt <= 9:
            # Phase 3: Full regeneration with failure context
            log.info("    [escalate] Full regeneration with failure context...")
            fixed = _regenerate_with_different_approach(
                resource,
                output,
                language,
                provider,
                memory_context,
            )
        else:
            # Phase 4: Last attempt — one more targeted fix
            fixed = _fix_with_llm(
                resource,
                code,
                output,
                language,
                provider,
                diagnosis=diagnosis,
                memory_context=memory_context,
            )

        if fixed:
            code_issue = _detect_code_issue(fixed, output)
            if code_issue:
                log.warning("    LLM detected code issue: %s", code_issue)
                code = fixed
                if language == "bash":
                    code = _fix_cross_platform(code)
                test_file.write_text(code)
                return {
                    "resource": resource.name,
                    "kind": resource.kind,
                    "status": "code_issue",
                    "code_issue": code_issue,
                    "test_code": code,
                    "test_file": str(test_file),
                    "passed": False,
                    "fix_attempts": attempt,
                    "language": language,
                    "test_type": test_type,
                    "test_output": output,
                    "usage": tokens,
                    "coverage": coverage,
                }

            code = fixed
            if language == "bash":
                code = _fix_cross_platform(code)
            test_file.write_text(code)
            passed, output = run_tests(str(test_file), language)
            if passed:
                log.info("    Fixed on attempt %d", attempt)
                # Record successful fix pattern in episodic memory
                _record_learned_pattern(
                    state_store,
                    language,
                    features,
                    diagnosis,
                    fix_worked=True,
                    fix_description=f"Fixed {diagnosis['type']} on attempt {attempt}",
                )
        else:
            break

    if not passed:
        fail_count = output.count("not ok") + output.count("FAILED")
        log.warning("    Still failing (%d failures) after %d fix attempts", fail_count, attempt)
        # Record failure pattern so future generations can learn
        if last_diagnosis:
            _record_learned_pattern(
                state_store,
                language,
                features,
                last_diagnosis,
                fix_worked=False,
                fix_description=f"Failed after {attempt} attempts: {last_diagnosis['summary']}",
            )

    # ── Step 7: Flaky detection ──
    flaky = False
    if passed:
        log.info("    [flaky] Running %d stability checks...", FLAKY_CHECK_RUNS)
        is_stable, flaky_output = _check_flaky(str(test_file), language)
        if not is_stable:
            flaky = True
            log.warning("    [flaky] Tests are flaky! Attempting fix...")
            # Try to fix flakiness with one more LLM call
            diagnosis = _diagnose_failure(flaky_output, language)
            fixed = _fix_with_llm(
                resource,
                code,
                flaky_output,
                language,
                provider,
                diagnosis=diagnosis,
            )
            if fixed:
                code = fixed
                if language == "bash":
                    code = _fix_cross_platform(code)
                test_file.write_text(code)
                # Verify fix resolved flakiness
                passed, output = run_tests(str(test_file), language)
                if passed:
                    is_stable, _ = _check_flaky(str(test_file), language)
                    flaky = not is_stable
            if flaky:
                log.warning("    [flaky] Could not resolve flakiness")

    # Final coverage update
    coverage = _analyze_coverage(code, resource, language)

    return {
        "resource": resource.name,
        "kind": resource.kind,
        "status": "passed" if passed else "tests_failing",
        "test_code": code,
        "test_file": str(test_file),
        "passed": passed,
        "fix_attempts": attempt,
        "language": language,
        "test_type": test_type,
        "test_output": output,
        "usage": tokens,
        "coverage": coverage,
        "flaky": flaky,
    }


# -- Existing test discovery -------------------------------------------------


def _sanity_check_dir(resource: TektonResource) -> Path:
    """Get the sanity-check/ directory next to the resource YAML."""
    return Path(resource.source_path).parent / SANITY_CHECK_DIR


def _sanitize_name(name: str) -> str:
    return name.replace("-", "_").replace(".", "_").replace("/", "_")


def find_existing_tests(resource: TektonResource) -> Path | None:
    """Find existing test file (BATS or pytest) in the resource's sanity-check/ directory."""
    sc_dir = _sanity_check_dir(resource)
    if not sc_dir.exists():
        return None
    for f in sc_dir.iterdir():
        if f.suffix in (".bats", ".py"):
            return f
    return None


# Keep backward compat
find_existing_bats = find_existing_tests


def propose_tests(
    resource: TektonResource,
    existing_test_path: Path,
    provider: LLMProvider,
) -> tuple[str, LLMResponse]:
    """Propose additional tests for a resource that already has tests."""
    yaml_content = Path(resource.source_path).read_text()
    existing_tests = existing_test_path.read_text()
    user_prompt = build_propose_prompt(resource, yaml_content, existing_tests)
    response = provider.generate(BATS_SYSTEM_PROMPT, user_prompt)
    code = _extract_code(response.content)
    return code, response


# -- Batch generation --------------------------------------------------------


def generate_all_tests(
    resources: list[TektonResource],
    provider: LLMProvider,
    callback=None,
    max_fix_attempts: int = DEFAULT_MAX_FIX_ATTEMPTS,
    state_store=None,
) -> list[dict]:
    """Generate tests for all resources with scripts, in-place.

    Handles both bash (BATS) and Python (pytest) scripts.
    Runs the autonomous fix loop for each resource.
    """
    results = []

    for i, resource in enumerate(resources):
        if not has_testable_scripts(resource):
            continue

        if callback:
            callback("start", index=i, total=len(resources), resource=resource)

        languages = get_script_languages(resource)
        existing = find_existing_tests(resource)

        for language in sorted(languages):
            try:
                if existing:
                    code, response = propose_tests(resource, existing, provider)
                    sc_dir = _sanity_check_dir(resource)
                    safe_name = _sanitize_name(resource.name)
                    ext = "py" if language == "python" else "bats"
                    out_path = sc_dir / f"{safe_name}_unit-tests_proposed.{ext}"
                    sc_dir.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(code)
                    result = {
                        "resource": resource.name,
                        "kind": resource.kind,
                        "source": resource.source_path,
                        "test_type": "pytest" if language == "python" else "bats",
                        "mode": "propose",
                        "output": str(out_path),
                        "provider": provider.name(),
                        "usage": response.usage,
                        "language": language,
                    }
                else:
                    result = generate_and_fix(
                        resource,
                        provider,
                        language,
                        max_fix_attempts=max_fix_attempts,
                        state_store=state_store,
                    )
                    result["mode"] = "generate"
                    result["source"] = resource.source_path
                    result["output"] = result.get("test_file", "")
                    result["provider"] = provider.name()

                results.append(result)

                if callback:
                    callback("done", index=i, total=len(resources), resource=resource, result=result)

            except Exception as e:
                result = {
                    "resource": resource.name,
                    "kind": resource.kind,
                    "source": resource.source_path,
                    "test_type": "pytest" if language == "python" else "bats",
                    "mode": "error",
                    "error": str(e),
                    "language": language,
                }
                results.append(result)
                if callback:
                    callback("error", resource=resource, error=e)

    return results
