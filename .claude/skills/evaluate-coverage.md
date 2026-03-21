---
name: evaluate-coverage
description: Analyze test coverage for a Tekton resource — find untested code paths
user_invocable: true
---

# Skill: Evaluate Test Coverage

Analyze how well generated tests cover the actual script logic. Think like a QA lead doing a coverage audit.

## Usage
```
/evaluate-coverage <path-to-test-file>
```

## Protocol

### Step 1: Find the resource YAML
Look in the parent of `sanity-check/` for `*.yaml`. Read it.

### Step 2: Extract all code paths from the script

For bash scripts, count and list:
- `if` conditions (including nested)
- `elif` conditions
- `else` branches
- `case` patterns
- `for`/`while`/`until` loops
- `exit N` calls (each exit code)
- `echo`/`printf` output strings
- Error handling (`set -e`, `trap`)

For Python scripts, count and list:
- `if`/`elif`/`else` branches
- `try`/`except`/`finally` blocks
- `sys.exit(N)` calls
- `print()` statements
- `raise` statements

### Step 3: Map tests to code paths

Read the test file. For each `@test` (BATS) or `def test_` (pytest):
- What code path does it exercise?
- What assertions does it make?
- Does it cover the branch FULLY (both sides)?

### Step 4: Identify gaps

```
COVERAGE REPORT:
  Resource: <kind> <name>
  Script branches: 12
  Tests: 8
  Coverage ratio: 67%

  COVERED:
  ✓ Line 15: if [ -z "$TOKEN" ] — tested by "test_missing_token"
  ✓ Line 23: if [ "$STATUS" == "success" ] — tested by "test_success_path"
  ✓ Line 30: else (failure) — tested by "test_failure_path"

  GAPS:
  ✗ Line 45: elif [ "$RETRY" -gt 3 ] — NO TEST
  ✗ Line 52: case "$ACTION" in "delete") — NO TEST for "delete" action
  ✗ Line 67: exit 2 — NO TEST (only exit 0 and exit 1 are tested)
  ✗ Line 78: echo "[WARN]: Fallback to default" — output not asserted anywhere

  RECOMMENDATIONS:
  1. Add test for retry limit exceeded (line 45)
  2. Add test for "delete" action in case statement (line 52)
  3. Add test that triggers exit 2 (line 67)
  4. Add assertion for fallback warning message (line 78)
```

### Step 5: Rate the coverage

- **Excellent** (>90%): All branches tested, edge cases covered
- **Good** (70-90%): Main paths covered, some edge cases missing
- **Needs improvement** (50-70%): Major branches untested
- **Poor** (<50%): Most logic untested, test is superficial
