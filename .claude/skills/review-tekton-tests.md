---
name: review-tekton-tests
description: Review generated tests for correctness, coverage, and stability
user_invocable: true
---

# Skill: Review Tekton Tests

Act as the skeptical reviewer — find problems in generated tests before they ship.

## Usage
```
/review-tekton-tests <catalog-path>
```

## Protocol

### Step 1: Find all generated tests
```bash
find <catalog-path> -name "*.bats" -path "*/sanity-check/*"
find <catalog-path> -name "*.py" -path "*/sanity-check/*"
```

### Step 2: Run all tests
```bash
# BATS
find <catalog-path> -name "*.bats" -path "*/sanity-check/*" -exec bats {} \;

# pytest
find <catalog-path> -name "*.py" -path "*/sanity-check/*" -exec python -m pytest {} -v \;
```

### Step 3: For each test file, review with the failure-analyst mindset

Delegate to the `failure-analyst` agent or apply its checklist manually:

1. **Mock gaps** — Every external command in the script has a mock?
2. **Assertion precision** — Assertions use exact strings from the script?
3. **Branch coverage** — Every if/elif/else/case has a test?
4. **Hanging risks** — Loops have exit conditions? Sleep mocked?
5. **Mock data validity** — JSON data is valid? Fields match what script reads?
6. **Tekton variables** — All $(params.X) replaced? All $(results.X.path) replaced?
7. **Cross-platform** — No &>>, #!/bin/bash in heredocs, sed -i'' -e?

### Step 4: For passing tests, verify they're NOT trivially passing

A test that always passes regardless of input is worthless. Check:
- Does the test actually run the script? (not just `run echo "hello"`)
- Does it set up meaningful mock data? (not empty)
- Do assertions check for specific strings? (not just exit 0)
- Would the test FAIL if the script logic changed?

### Step 5: Flaky check
Run each test file 3 times. Any inconsistency → flag as flaky.

### Step 6: Report

```
REVIEW SUMMARY:
  Files reviewed: 15
  Passing: 12
  Failing: 2
  Flaky: 1

  ISSUES FOUND:
  1. store-pipeline-status_unit-tests.bats
     - [MOCK_GAP] Missing mock for `date -u`
     - [ASSERTION_DRIFT] Line 87: asserts *"error"* but script echoes "[ERROR]: Pipeline failed"

  2. push-oci-artifact_unit-tests.bats
     - [HANGING_RISK] while loop on line 45 has no mock exit condition
     - [MISSING_BRANCH] elif for empty annotations (line 67) untested

  3. trigger-jenkins_unit-tests.py (FLAKY)
     - Passes 2/3 times. Port conflict in mock HTTP server.

  FIXES APPLIED: 3
  REMAINING ISSUES: 1 (flaky test needs port randomization)
```
