---
name: diagnose-failure
description: Diagnose why generated tests are failing — classify and recommend fix strategy
user_invocable: true
---

# Skill: Diagnose Test Failure

Analyze failing test output and classify the root cause. Think like a human debugging a test.

## Usage
```
/diagnose-failure <path-to-test-file>
```

## Protocol

### Step 1: Run the test
```bash
# For BATS
bats <path-to-bats-file>

# For pytest
python -m pytest <path-to-py-file> -v --tb=short
```

### Step 2: Read the test file and the resource YAML
- Find the resource YAML: look in the parent of `sanity-check/` for `*.yaml`
- Read both files completely

### Step 3: Classify the failure

For each failing test, determine the failure type:

| Type | Symptoms | Root Cause |
|---|---|---|
| `mock_mismatch` | "command not found", wrong output | Mock doesn't match script's invocation pattern |
| `assertion_mismatch` | Test runs but assertion fails | Assertion string ≠ script's actual output |
| `syntax_error` | Parse error, unexpected token | Broken bash/python syntax in test |
| `timeout` | Test hangs, killed after N seconds | Unmocked sleep/loop, real network call |
| `import_error` | ModuleNotFoundError | Missing python dependency |
| `script_bug` | Script itself exits wrong | Bug in original script, not test |
| `mock_data_invalid` | jq parse error, JSON syntax | Mock JSON has invalid syntax or missing fields |
| `path_not_replaced` | "$(params.X)" in error | Tekton variable not sed-replaced |
| `env_missing` | Unbound variable, KeyError | Environment variable not exported |
| `cross_platform` | Works on Linux, fails on macOS | &>>, date -d, grep -P, readlink -f |

### Step 4: Recommend fix strategy

Based on failure type, recommend:

- **mock_mismatch** → "Re-read script lines N-M. The script calls `<cmd>` with `<args>`. Create/fix the mock to handle this exact invocation."
- **assertion_mismatch** → "Script echoes `<exact string>` on line N. Change assertion to match this exact string."
- **timeout** → "Mock `sleep` as no-op. Add mock exit condition for the `while` loop on line N."
- **script_bug** → "This looks like a bug in the original script, not the test. Add `# CODE_ISSUE:` marker."

### Step 5: Report

```
DIAGNOSIS:
  File: <path>
  Failures: <count>

  1. Test: "<test name>"
     Type: mock_mismatch
     Details: Script calls `kubectl get pods -o json` (line 42) but mock only handles `kubectl get pods`
     Fix: Add `-o json` matching to kubectl mock, return JSON with `items` array

  2. Test: "<test name>"
     Type: assertion_mismatch
     Details: Script echoes "[INFO]: Found 3 vulnerabilities" but test asserts *"Found vulnerabilities"*
     Fix: Change assertion to *"[INFO]: Found 3 vulnerabilities"*

RECOMMENDED STRATEGY: targeted_fix (failures are specific, not systemic)
```

If most failures share the same root cause → "systemic issue, rewrite mocks"
If failures are varied → "targeted fix, address each individually"
If failures persist after 3+ fixes → "full regeneration recommended"
