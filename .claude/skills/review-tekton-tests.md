---
name: review-tekton-tests
version: 1.0.0
description: |
  Comprehensive review of generated tests across an entire catalog — runs all tests, checks for
  issues, verifies quality, and detects flaky tests. Acts as final quality gate before shipping.

  TRIGGER when: you want to validate ALL tests in a catalog, check for patterns across multiple
  test files, or ensure comprehensive quality before submitting PRs.

  DO NOT TRIGGER when: reviewing a single test file (use failure-analyst directly), or when tests
  haven't been generated yet (nothing to review).
user_invocable: true
tags:
  - testing
  - review
  - quality-assurance
  - validation
  - pr-review
examples:
  - description: Review all tests in a catalog before PR
    input: /review-tekton-tests ./tekton-catalog/
  - description: Validate tests for specific directory
    input: /review-tekton-tests tasks/managed/
  - description: Check for flaky tests across catalog
    input: /review-tekton-tests ./catalog/ --detect-flaky
resources:
  - url: https://bats-core.readthedocs.io/
    description: BATS framework for test execution
  - url: https://docs.pytest.org/
    description: pytest framework reference
  - url: https://martinfowler.com/articles/nonDeterminism.html
    description: Understanding and addressing test flakiness
---

# Skill: Review Tekton Tests

Comprehensive quality review of all generated tests in a catalog. Think like a tech lead doing final review before merging a PR — checking not just that tests pass, but that they're meaningful, stable, and maintainable.

## When to Use This

Use this skill when:
- You've generated tests for multiple resources
- You want systematic quality check across the catalog
- You're preparing to submit a PR with generated tests
- You want to identify patterns or systemic issues

Don't use this skill when:
- Only one test file exists (use `failure-analyst` agent directly)
- Tests haven't been generated
- You just want to run tests without review (use bats/pytest directly)

## Skill Dependencies

This skill may invoke:

- **`/evaluate-coverage`** — For each passing test, checks branch coverage completeness
- **`/diagnose-failure`** — For any failing tests found during review

**Review Protocol**:
```
for each test file:
  run test → collect output →
  if passing: evaluate coverage → check assertions quality
  if failing: diagnose failure → report root cause
  check for flaky: run 3x → detect non-determinism
aggregate results → identify patterns → report summary
```

## Usage

```
/review-tekton-tests <catalog-path>
```

## What This Skill Does

1. Finds all generated test files in the catalog
2. Runs every test (BATS and pytest)
3. For each file, applies failure-analyst checklist
4. Checks for flakiness (runs tests multiple times)
5. Identifies patterns across test files
6. Reports issues with specific fixes
7. Applies fixes where appropriate

## Protocol

### Step 1: Discover All Tests

```bash
find <catalog-path> -name "*.bats" -path "*/sanity-check/*"
find <catalog-path> -name "*.py" -path "*/sanity-check/*"
```

This gives you the full scope — how many test files, which resources are tested.

### Step 2: Run All Tests

```bash
# BATS
find <catalog-path> -name "*.bats" -path "*/sanity-check/*" -exec bats {} \;

# pytest
find <catalog-path> -name "*.py" -path "*/sanity-check/*" -exec python -m pytest {} -v \;
```

Capture results for each file:
- How many tests total
- How many passed
- How many failed
- What the failure messages were

### Step 3: Review Each File

For each test file, apply the failure-analyst checklist (or delegate to that agent):

**Mock gaps:** Every external command in script has a mock?

**Assertion precision:** Assertions use exact strings from script?

**Branch coverage:** Every if/elif/else/case has a test?

**Hanging risks:** Loops have exit conditions? Sleep mocked?

**Mock data validity:** JSON is valid? Fields match script expectations?

**Tekton variables:** All $(params.X) replaced?

**Cross-platform:** No platform-specific syntax?

**Why review passing tests?** Because tests can pass for the wrong reasons. A test that always passes regardless of input is worthless.

### Step 4: Check for Trivially Passing Tests

A test is trivially passing if it would pass even if the script logic was removed.

**Red flags:**
- Test only checks `[ "$status" -eq 0 ]` with no output assertions
- Mock data is empty or minimal
- Assertions are too vague (`*"success"*` matches any success message)
- Script is barely exercised (only runs one path)

**How to verify:**
Mentally remove key script logic and ask: "Would this test still pass?"
If yes, the test needs stronger assertions.

### Step 5: Flaky Check

For each passing test file, run it 3 times:

```bash
for i in 1 2 3; do
  bats <file> || echo "FLAKY: $file"
done
```

Any inconsistency → flag as flaky → investigate.

**Common flakiness causes:**
- Port conflicts (mock servers using hardcoded ports)
- Temp file races (multiple tests using same filename)
- Uninitialized variables (sometimes set, sometimes not)
- Non-deterministic output ordering (jq sorts, grep doesn't)

### Step 6: Identify Cross-File Patterns

Look for recurring issues:

**Good patterns to amplify:**
- Consistent mock structure across similar resources
- Thorough edge case coverage
- Clear test organization (suites, naming)

**Bad patterns to fix:**
- Same command mocked inconsistently across files
- Same assertion drift in multiple files
- Same missing branch across similar resources

**Why pattern analysis?** If 5 files have the same mock issue, fixing it once and replicating is more efficient than fixing 5 times independently.

### Step 7: Report

```
REVIEW SUMMARY:
  Catalog: <path>
  Test files: 15
  Total tests: 124
  Passing: 112 (90%)
  Failing: 10 (8%)
  Flaky: 2 (2%)

ISSUES FOUND:

  File: store-pipeline-status_unit-tests.bats
    Status: FAILING (2/12 tests)
    Issues:
      - [MOCK_GAP] Missing mock for `date -u` (line 78)
      - [ASSERTION_DRIFT] Asserts *"error"* but script says "[ERROR]: Pipeline failed"
    Severity: critical
    Fix applied: Yes (added date mock, fixed assertion)

  File: push-oci-artifact_unit-tests.bats
    Status: FAILING (1/10 tests)
    Issues:
      - [HANGING_RISK] while loop has no exit condition (line 45)
      - [MISSING_BRANCH] elif for empty annotations untested (line 67)
    Severity: critical
    Fix applied: Partial (added sleep mock, branch still needs test)

  File: trigger-jenkins_unit-tests.py
    Status: FLAKY (passes 2/3 runs)
    Issues:
      - Port conflict in mock HTTP server (uses hardcoded port 8080)
    Severity: moderate
    Fix applied: Yes (changed to random port selection)

CROSS-FILE PATTERNS:
  - kubectl mocks inconsistent: 3 files handle -o json, 2 don't
    → Recommendation: Standardize kubectl mock pattern across catalog
  - All jq tests use inline mock data, none use files
    → Good pattern: consistent approach
  - 4 files missing cross-platform date mocks
    → Should be systemic fix

FIXES APPLIED: 8
  - 3 mock gaps filled
  - 2 assertions corrected
  - 2 cross-platform issues fixed
  - 1 flaky test stabilized

REMAINING ISSUES: 3
  - 1 untested branch (needs new test case)
  - 1 complex mock issue (needs mock rewrite)
  - 1 suspected script bug (flagged for human review)

RECOMMENDATIONS:
  1. Standardize kubectl mock across all files
  2. Add missing branch test to push-oci-artifact
  3. Review create-advisory script (possible bug at line 89)
  4. Consider extracting common mock patterns to shared fixtures
```

## Review Quality Tiers

Use these to categorize files:

**Production-ready:**
- All tests passing
- Stable across multiple runs
- Comprehensive branch coverage (>80%)
- Precise assertions
- Clear test organization

**Needs minor fixes:**
- Tests passing but some gaps
- Could be more comprehensive
- Assertions could be more precise
- Organization could be clearer

**Needs major work:**
- Tests failing
- Flaky
- Poor coverage
- Trivially passing
- Systemic issues

## What Good Tests Look Like

When reviewing, these are the hallmarks of quality:

**Precision:** Assertions match exact script output, not paraphrases

**Completeness:** All branches tested, both success and error paths

**Independence:** Tests don't depend on execution order or shared state

**Clarity:** Test names describe what they test and under what conditions

**Robustness:** Tests don't hang, don't have race conditions, work cross-platform

**Meaningfulness:** Tests would fail if script logic changed (not trivially passing)

Use these criteria when evaluating each test file.
