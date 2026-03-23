---
name: evaluate-coverage
version: 1.0.0
description: |
  Analyze test coverage for Tekton resources — identifies untested code paths, branches, error
  handlers, and edge cases. Maps tests to script logic to find gaps.

  TRIGGER when: tests are passing and you need to verify they're comprehensive, or when you want
  to identify which code paths still need test cases.

  DO NOT TRIGGER when: tests are failing (fix them first with fix-test), or for pre-generation
  planning (that's handled by risk-audit).
user_invocable: true
tags:
  - testing
  - coverage
  - quality-assurance
  - analysis
  - completeness
examples:
  - description: Analyze coverage for a specific task
    input: /evaluate-coverage tasks/git-clone/git-clone.yaml
  - description: Check coverage across entire catalog
    input: /evaluate-coverage ./catalog/
  - description: Identify untested branches in failing tests
    input: /evaluate-coverage tasks/complex-task/ --show-gaps
resources:
  - url: https://bats-core.readthedocs.io/en/stable/writing-tests.html
    description: Writing comprehensive BATS tests
  - url: https://en.wikipedia.org/wiki/Code_coverage
    description: Code coverage concepts and branch coverage
---

# Skill: Evaluate Test Coverage

Analyze how well generated tests cover the actual script logic. Think like a QA lead conducting a coverage audit — not just counting tests, but mapping them to code paths to find blind spots.

## When to Use This

Use this skill when:
- Tests are passing and you want to verify comprehensive coverage
- You suspect tests are superficial (pass too easily)
- You need to identify which branches/paths need additional tests

Don't use this skill when:
- Tests are failing (fix failures first with `/fix-test`)
- Tests haven't been generated (no tests to evaluate)
- You're planning what to test (use `/risk-audit` for pre-generation analysis)

## What Coverage Means

**Not just test count.** A file with 20 tests that all exercise the same happy path has worse coverage than a file with 5 tests that cover all branches.

**Real coverage** means:
- Every `if`/`elif`/`else` has tests for both TRUE and FALSE
- Every `case` pattern has a test
- Every error path (`exit 1`, `exit 2`, etc.) has a test that triggers it
- Every loop has tests for: first iteration, last iteration, empty input
- Every output string has an assertion verifying it

## Usage

```
/evaluate-coverage <path-to-test-file>
```

## Protocol

### Step 1: Find the Resource YAML

Test file is in `sanity-check/`, resource YAML is in parent directory:
```bash
# If test is at: catalog/tasks/my-task/0.1/sanity-check/my_task_unit-tests.bats
# Then YAML is at: catalog/tasks/my-task/0.1/my-task.yaml
```

Read the YAML to extract the embedded scripts.

### Step 2: Extract Code Paths from Script

**For bash scripts**, count and list:
- `if` conditions (including nested `if` inside `if`)
- `elif` conditions
- `else` branches
- `case` patterns (each pattern is a path)
- `for`/`while`/`until` loops (consider: empty iteration, first iteration, many iterations)
- `exit N` calls (each exit code is distinct)
- `echo`/`printf` output strings (should be asserted)
- Error handling (`set -e`, `trap`, `||` operators)

**For Python scripts**, count and list:
- `if`/`elif`/`else` branches
- `try`/`except`/`finally` blocks (each except clause)
- `for`/`while` loops
- `sys.exit(N)` calls
- `print()` statements
- `raise` statements (each exception type)

**Why enumerate?** You can't evaluate coverage without knowing what needs to be covered.

### Step 3: Map Tests to Code Paths

Read the test file. For each `@test` (BATS) or `def test_` (pytest):

**Ask:**
- What code path does this test exercise?
- What branch condition does it trigger?
- What assertions does it make?
- Does it cover the path FULLY or just touch it?

**Example mapping:**
```
Script line 23: if [ -z "$TOKEN" ]; then echo "ERROR: Missing token"; exit 1; fi

Test "error: missing token":
  - Sets TOKEN=""
  - Runs script
  - Asserts exit code 1
  - Asserts output contains "ERROR: Missing token"
  → FULLY COVERED (both exit and output verified)

Script line 45: if [ "$COUNT" -gt 10 ]; then echo "WARNING: High count"; fi

(no test)
  → NOT COVERED
```

### Step 4: Identify Coverage Gaps

Compare paths in script vs tests exercising them.

**Categories of gaps:**

**Completely untested branches:**
- `elif` condition with no corresponding test
- `case` pattern never triggered
- Error exit path never exercised

**Partially tested branches:**
- Branch is triggered but output not asserted
- Branch is triggered but exit code not checked
- Loop runs but edge cases (empty, single item) not tested

**Untested interactions:**
- Script sets variable in step 1, reads in step 2, but no test for empty value
- Script writes file then reads it, but no test for write failure
- Script calls command A, parses output with command B, but no test for invalid format

### Step 5: Rate Coverage Quality

Use this rubric:

**Excellent (>90% paths covered)**
- All branches have dedicated tests
- Both TRUE and FALSE sides of conditions tested
- All error paths verified (exit codes + messages)
- Edge cases covered (empty input, boundary values)
- All command outputs asserted

**Good (70-90%)**
- Main happy path fully tested
- Most branches covered
- Some edge cases covered
- Critical error paths tested

**Needs Improvement (50-70%)**
- Happy path covered but incomplete assertions
- Many branches untested
- Error paths not systematically tested
- Edge cases mostly missing

**Poor (<50%)**
- Only superficial happy path
- Most logic untested
- Tests pass trivially (no real assertions)
- Huge blind spots

### Step 6: Generate Recommendations

For each gap, provide:
- Which line/branch is untested
- What test case would cover it
- What assertions the test should make
- Why this path matters (error handling? common scenario? edge case?)

## Output Format

```
COVERAGE REPORT:
  Resource: Task my-task
  Script type: bash (67 lines)
  Total branches: 12
  Tests: 8
  Coverage ratio: 75% (9/12 branches)

COVERED PATHS:
  ✓ Line 15: if [ -z "$TOKEN" ]
    → Tested by "error: missing required token"
    → Verified: exit code 1, error message

  ✓ Line 23: if [ "$STATUS" == "success" ]
    → Tested by "success: pipeline completed"
    → Verified: exit code 0, result file content

  ✓ Line 30: else (failure path)
    → Tested by "failure: pipeline failed"
    → Verified: exit code 1, failure message

  ✓ Line 45: while [ $RETRY -lt 3 ]; do
    → Tested by "retry: attempts up to 3 times"
    → Verified: loop iterations, retry count

GAPS (3 paths untested):

  ✗ Line 38: elif [ "$RETRY" -gt 3 ]
    Impact: Retry limit exceeded handling is untested
    Recommendation: Add test that sets RETRY=4, verify error message:
                    "ERROR: Retry limit exceeded"
    Priority: HIGH (error path for production scenario)

  ✗ Line 52: case "$ACTION" in "delete")
    Impact: Delete action path completely untested
    Recommendation: Add test with ACTION="delete", verify:
                    - Deletion command called
                    - Success message output
    Priority: MEDIUM (valid production path)

  ✗ Line 67: exit 2 (invalid configuration)
    Impact: Configuration validation error untested
    Recommendation: Add test with malformed config, verify:
                    - Exit code 2 (not 0 or 1)
                    - Error message contains "Invalid configuration"
    Priority: HIGH (helps debug config issues)

COVERAGE QUALITY: Good (75%)
  Strengths: Main paths well-tested, error handling mostly covered
  Weaknesses: Some error branches missing, edge case coverage incomplete

RECOMMENDATIONS:
  1. Add 3 tests to cover identified gaps (would bring coverage to 100%)
  2. Consider edge cases:
     - Empty JSON input (script uses jq)
     - Very long input strings (truncation handling?)
     - Concurrent execution (file locking?)
  3. Verify assertions are precise (not just exit 0 checks)

NEXT STEPS:
  - Generate 3 additional test cases for gaps
  - Run full suite to verify no regressions
  - Consider flaky check if tests involve timing/ordering
```

## Evaluation Heuristics

Use these to assess quality:

**High-quality coverage indicators:**
- Every echo/print has a corresponding assertion
- Error paths have tests that trigger them AND verify both exit code and message
- Edge cases explicitly tested (empty input, boundary values)
- Loop tests cover: 0 iterations, 1 iteration, many iterations
- Mocks fail in error tests (not just success tests)

**Low-quality coverage indicators:**
- Tests only check exit code, not output
- No tests for `elif` or `else` branches
- Error paths untested
- All tests look similar (just changing one parameter)
- Tests pass even when script is completely commented out (trivially passing)

**Trivially passing test detection:**
Ask: "Would this test fail if I deleted the script logic?"
If answer is "no", the test is trivially passing.

## Common Coverage Patterns

**Pattern: High test count, low actual coverage**
→ Many tests exercising the same path with slight variations. Better to have fewer tests that each cover different branches.

**Pattern: 100% branch coverage but weak assertions**
→ Every path tested but only exit codes checked, not output. This catches syntax errors but not logic errors.

**Pattern: Happy path overcovered, error paths undercovered**
→ 5 tests for success scenarios, 0 tests for failures. Error handling is where bugs hide — prioritize covering those paths.

**Pattern: Loops tested once**
→ Loop has test with valid input, but no test for empty input (0 iterations) or edge behavior.
