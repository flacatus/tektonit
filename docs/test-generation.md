# Test Generation Deep Dive

## What gets tested

tektonit generates tests for **embedded scripts** in Tekton resources. An embedded script is any inline bash or Python code in a step's `script` field:

```yaml
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: check-pods
spec:
  params:
    - name: namespace
      type: string
  results:
    - name: pod-count
  steps:
    - name: check
      image: registry.access.redhat.com/ubi9/ubi-minimal
      script: |
        #!/usr/bin/env bash
        set -euo pipefail
        # This script is what gets tested
        PODS=$(kubectl get pods -n "$(params.namespace)" -o json)
        COUNT=$(echo "$PODS" | jq '.items | length')
        echo "[INFO]: Found $COUNT pods"
        echo -n "$COUNT" > "$(results.pod-count.path)"
```

Resources without embedded scripts (e.g., pipelines with only `taskRef` references) are skipped.

## How tests are structured

### BATS test anatomy

Every generated BATS test file follows this structure:

```bash
#!/usr/bin/env bats

# ── Setup ──────────────────────────────────────────────

setup() {
    # 1. Create mock binary directory
    export MOCK_BIN="$BATS_TEST_TMPDIR/mock_bin"
    mkdir -p "$MOCK_BIN"
    export PATH="$MOCK_BIN:$PATH"

    # 2. Create mocks for every external command
    cat > "$MOCK_BIN/kubectl" << 'MOCK_EOF'
#!/usr/bin/env bash
if [[ "$*" == *"get pods"* ]]; then
    echo '{"items": [{"metadata": {"name": "pod-1"}}]}'
elif [[ "$*" == *"apply"* ]]; then
    echo "resource/name configured"
fi
MOCK_EOF
    chmod +x "$MOCK_BIN/kubectl"

    # 3. Create result file directories
    export RESULTS_DIR="$BATS_TEST_TMPDIR/results"
    mkdir -p "$RESULTS_DIR"

    # 4. Extract the script from YAML and stub Tekton variables
    cat > "$BATS_TEST_TMPDIR/script.sh" << 'SCRIPT_EOF'
#!/usr/bin/env bash
set -euo pipefail
PODS=$(kubectl get pods -n "$(params.namespace)" -o json)
COUNT=$(echo "$PODS" | jq '.items | length')
echo "[INFO]: Found $COUNT pods"
echo -n "$COUNT" > "$(results.pod-count.path)"
SCRIPT_EOF

    # 5. Replace Tekton variable placeholders
    sed -i'' -e 's|$(params.namespace)|test-ns|g' "$BATS_TEST_TMPDIR/script.sh"
    sed -i'' -e "s|\\$(results.pod-count.path)|$RESULTS_DIR/pod-count|g" "$BATS_TEST_TMPDIR/script.sh"
    chmod +x "$BATS_TEST_TMPDIR/script.sh"
}

# ── Teardown ───────────────────────────────────────────

teardown() {
    rm -rf "$MOCK_BIN"
}

# ── Tests ──────────────────────────────────────────────

@test "success path: counts pods correctly" {
    run "$BATS_TEST_TMPDIR/script.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"[INFO]: Found 1 pods"* ]]
    [ "$(cat "$RESULTS_DIR/pod-count")" = "1" ]
}

@test "fails when kubectl returns error" {
    cat > "$MOCK_BIN/kubectl" << 'EOF'
#!/usr/bin/env bash
echo "error: connection refused" >&2
exit 1
EOF
    chmod +x "$MOCK_BIN/kubectl"

    run "$BATS_TEST_TMPDIR/script.sh"
    [ "$status" -ne 0 ]
}

@test "handles empty pod list" {
    cat > "$MOCK_BIN/kubectl" << 'EOF'
#!/usr/bin/env bash
echo '{"items": []}'
EOF
    chmod +x "$MOCK_BIN/kubectl"

    run "$BATS_TEST_TMPDIR/script.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"[INFO]: Found 0 pods"* ]]
    [ "$(cat "$RESULTS_DIR/pod-count")" = "0" ]
}
```

### Key principles

1. **Script is embedded verbatim** — The actual script from the YAML is copied into a heredoc. No summarization or rewriting.

2. **Tekton variables are stubbed with sed** — `$(params.X)` becomes a test value, `$(results.X.path)` becomes a temp file path.

3. **Every external command gets a mock** — Mocks are shell scripts in `$MOCK_BIN` that match on argument patterns and return predetermined output.

4. **Assertions use exact strings** — Output assertions match the exact `echo`/`printf` strings from the script, character for character.

5. **Cross-platform compatible** — Uses `sed -i'' -e` (works on macOS and Linux), `#!/usr/bin/env bash` (portable shebang), no `&>>` (bash 4+ only).

## Mock patterns

### Command mocking (BATS)

Mocks are scripts placed in `$MOCK_BIN` which is prepended to `$PATH`:

```bash
# Simple mock — always returns same output
cat > "$MOCK_BIN/jq" << 'EOF'
#!/usr/bin/env bash
echo "value"
EOF
chmod +x "$MOCK_BIN/jq"

# Argument-matching mock — different output based on args
cat > "$MOCK_BIN/curl" << 'EOF'
#!/usr/bin/env bash
if [[ "$*" == *"/api/v1/advisories"* ]]; then
    echo '{"id": "RHSA-2024:0001"}'
elif [[ "$*" == *"/api/v1/status"* ]]; then
    echo '{"status": "active"}'
else
    echo "unexpected curl call: $*" >&2
    exit 1
fi
EOF
chmod +x "$MOCK_BIN/curl"

# Failure mock — simulates command failure
cat > "$MOCK_BIN/oras" << 'EOF'
#!/usr/bin/env bash
echo "Error: authentication required" >&2
exit 1
EOF
chmod +x "$MOCK_BIN/oras"
```

### Per-test mock overrides

Override mocks in specific tests to test error paths:

```bash
@test "handles API timeout" {
    cat > "$MOCK_BIN/curl" << 'EOF'
#!/usr/bin/env bash
echo "curl: (28) Connection timed out" >&2
exit 28
EOF
    chmod +x "$MOCK_BIN/curl"

    run "$BATS_TEST_TMPDIR/script.sh"
    [ "$status" -ne 0 ]
    [[ "$output" == *"[ERROR]: API request failed"* ]]
}
```

### Mocking common commands

| Command | Mock strategy |
|---|---|
| `kubectl` | Match on subcommand + resource type, return JSON |
| `curl` | Match on URL pattern, return response body |
| `jq` | Usually pass-through or return extracted value |
| `oras` | Match on subcommand (push/pull/manifest) |
| `git` | Match on subcommand (clone/push/tag) |
| `cosign` | Return success/failure with appropriate output |
| `sleep` | No-op (prevent hangs) |
| `date` | Return fixed timestamp |

## Tekton variable substitution

Tekton variables in scripts are replaced with test values:

| Variable pattern | Replacement |
|---|---|
| `$(params.name)` | A sensible test value based on param name |
| `$(params.name[*])` | Array expansion |
| `$(results.name.path)` | `$RESULTS_DIR/name` (temp file) |
| `$(workspaces.name.path)` | `$BATS_TEST_TMPDIR/workspace-name` |
| `$(workspaces.name.bound)` | `true` |
| `$(context.task.name)` | `test-task` |
| `$(context.taskRun.name)` | `test-taskrun` |

## Coverage targets

The agent aims for comprehensive coverage:

- **Every `if`/`elif`/`else` branch** gets at least one test
- **Every `case` pattern** gets a test
- **Every `exit N`** code gets a test that triggers it
- **Every `echo`/`printf` output** gets an assertion
- **Error paths** — missing inputs, command failures, invalid data
- **Edge cases** — empty strings, empty JSON, missing files

The coverage analyzer counts branches vs tests and requests additional tests if the ratio is below 50%.

## Code issue detection

Sometimes the test reveals a bug in the original Tekton script, not in the test itself. The agent detects this when:

- The same assertion fails after 3+ fix attempts on different approaches
- The script logic is demonstrably incorrect (unreachable code, wrong variable)
- JSON parsing fails on data the script itself generates

When detected, the agent marks the test with:
```bash
# CODE_ISSUE: Variable $TOKEN is used but never set when auth mode is "none"
```

And reports it separately so the catalog maintainer can fix the original script.
