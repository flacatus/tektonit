---
name: diagnose-failure
version: 1.0.0
description: |
  Classify and diagnose why generated tests are failing. Analyzes test output to determine root
  cause (mock mismatch, assertion drift, script bug, etc.) and recommends targeted fix strategy.

  TRIGGER when: tests have already run and failed, and you need to understand WHY they failed
  before attempting to fix them.

  DO NOT TRIGGER when: tests haven't been generated yet (use failure-analyst for pre-run review),
  or when tests are passing (use evaluate-coverage to check completeness).
user_invocable: true
tags:
  - debugging
  - testing
  - diagnosis
  - troubleshooting
  - root-cause-analysis
examples:
  - description: Diagnose why BATS tests are failing
    input: /diagnose-failure tasks/git-clone/sanity-check/git_clone_unit-tests.bats
  - description: Analyze pytest failure output
    input: /diagnose-failure tasks/python-scan/sanity-check/python_scan_unit-tests.py
  - description: Classify multiple test failures
    input: /diagnose-failure ./catalog/*/sanity-check/*.bats
resources:
  - url: https://bats-core.readthedocs.io/en/stable/writing-tests.html#special-variables
    description: Understanding BATS test output and special variables
  - url: https://docs.pytest.org/en/stable/how-to/output.html
    description: pytest output and failure reporting
---

# Skill: Diagnose Test Failure

Analyze failing test output to classify root cause and recommend fix strategy. Think like a senior engineer debugging a test failure — not just "it failed", but "it failed BECAUSE X, so we should Y".

## When to Use This

Use this skill when:
- Tests have run and failed
- You need to understand the failure pattern before fixing
- Multiple tests are failing and you need to identify if there's a systemic issue

Don't use this skill when:
- Tests haven't been generated or run yet
- Tests are passing (use `/evaluate-coverage` instead)
- You're ready to fix and know the root cause (use `/fix-test` directly)

## Usage

```
/diagnose-failure <path-to-test-file>
```

## What This Skill Does

1. Runs the test and captures full output
2. Reads both the test file and the original resource YAML
3. Classifies each failure into a specific type
4. Identifies patterns across multiple failures
5. Recommends the appropriate fix strategy
6. Provides specific guidance on what to change

## Protocol

### Step 1: Run the Test

```bash
# For BATS
bats <path-to-bats-file>

# For pytest
python -m pytest <path-to-py-file> -v --tb=short
```

Capture the full output. Details matter — error messages, line numbers, actual vs expected values.

### Step 2: Read Context

Find and read:
- The test file itself
- The resource YAML (look in parent directory of `sanity-check/`)

Understanding the original script is essential — you can't diagnose a mock mismatch without knowing what the script actually calls.

### Step 3: Classify Each Failure

Use this classification table:

| Failure Type | Symptoms | Root Cause | Typical Fix |
|---|---|---|---|
| `mock_mismatch` | "command not found", unexpected output | Mock doesn't match script's invocation pattern | Add/update mock |
| `assertion_mismatch` | Test runs but assertion fails | Assertion string ≠ script's actual output | Fix assertion |
| `syntax_error` | Parse error, unexpected token | Broken bash/python syntax in test | Fix syntax |
| `timeout` | Test hangs, killed after N seconds | Unmocked sleep/loop, real network call | Mock sleep/loop |
| `import_error` | ModuleNotFoundError, import failure | Missing python dependency | Install or mock module |
| `script_bug` | Script itself exits wrong | Bug in original script, not test | Mark CODE_ISSUE |
| `mock_data_invalid` | jq parse error, JSON syntax error | Mock JSON has invalid syntax or missing fields | Fix mock data |
| `path_not_replaced` | "$(params.X)" appears in error | Tekton variable not sed-replaced | Fix sed pattern |
| `env_missing` | Unbound variable, KeyError | Environment variable not exported | Export in setup |
| `cross_platform` | Works on Linux, fails on macOS | Platform-specific syntax | Use portable syntax |

**Why classify?** Different failure types need fundamentally different fixes. Trying to fix a mock_mismatch by changing assertions wastes attempts.

### Step 4: Identify Patterns

Look across all failures in the file:

**Systemic issues** (rewrite mocks):
- Same command fails in multiple tests
- All assertions on output from command X fail
- JSON parsing fails across multiple mocks

**Isolated issues** (targeted fix):
- One test fails, others pass
- Different failure types in different tests
- Failures in unrelated parts of the script

**Why pattern detection matters:** If 8 out of 10 tests fail because of kubectl mock precision, you need to rebuild the kubectl mock from scratch, not fix 8 tests individually.

### Step 5: Recommend Fix Strategy

Based on patterns and failure types:

**Targeted fix** when:
- 1-2 tests fail out of many
- Clear, specific root cause
- Different tests fail for different reasons

**Mock rewrite** when:
- Same command fails across multiple tests
- Mock data format doesn't match script expectations
- 50%+ of failures are mock_mismatch or mock_data_invalid

**Full regeneration** when:
- Fundamentally wrong understanding of script
- Tests fail in ways that suggest wrong mocking approach
- Failures persist after 3+ targeted fix attempts

**Script bug investigation** when:
- Script behavior contradicts its apparent intent
- Exit codes don't match script logic
- Script would fail in production with same inputs

## Output Format

```
DIAGNOSIS:
  File: <path>
  Total tests: <count>
  Failures: <count>

FAILURES BREAKDOWN:

  1. Test: "happy path: all taskruns complete"
     Type: mock_mismatch
     Line: (test line 42, script line 35)
     Details: Script calls `kubectl get pods -o json` but mock only handles
              `kubectl get pods` (no -o flag). Mock returns plain text, script
              tries to pipe through jq, jq fails with "parse error".
     Fix: Add `-o json` case to kubectl mock, return valid JSON with items array

  2. Test: "error: missing required token"
     Type: assertion_mismatch
     Line: (test line 67, script line 89)
     Details: Script echoes "[ERROR]: TOKEN environment variable not set"
              but test asserts *"missing token"* (paraphrased, not exact).
     Fix: Change assertion to *"[ERROR]: TOKEN environment variable not set"*

  3. Test: "retry: waits for incomplete taskruns"
     Type: timeout
     Line: (test line 105, script line 42)
     Details: Script has `while true; do sleep 1; done`, sleep not mocked,
              test hangs until BATS timeout at 30s.
     Fix: Mock sleep as no-op, ensure loop completion mock returns immediately

PATTERN ANALYSIS:
  - 2/3 failures involve kubectl mock (systemic)
  - Mock doesn't handle -o json flag variant
  - Assertions are paraphrased instead of exact

RECOMMENDED STRATEGY: mock_rewrite
  Priority: Fix kubectl mock to handle all flag variants used in script
  Secondary: Update assertions to use exact strings from script

CONFIDENCE: high (clear pattern, specific fixes identified)
```

## Decision Rules

Use these to guide strategy selection:

**Don't escalate for simple fixes:**
- "command not found" → missing mock, just add it
- "syntax error" → fix syntax, don't regenerate
- "unbound variable" → export it, don't rewrite mocks

**Do escalate for repeated issues:**
- Same assertion fails after 3 targeted fixes → mock is returning wrong data
- Failures change between attempts (fix one, new one appears) → systemic issue
- Multiple tests fail with same root cause → rewrite the problematic component

**Consider script bugs when:**
- Script logic contradicts its error messages
- Exit codes don't match documented behavior
- Script would fail with valid production inputs

**Why have rules?** Consistent diagnostic logic leads to better fix success rates. Ad-hoc diagnosis leads to wasted attempts.

## Common Diagnostic Patterns

**Pattern: "jq parse error" in multiple tests**
→ Mock is returning plain text or invalid JSON. Check that all JSON mocks are syntactically valid and contain the fields the script reads.

**Pattern: Tests pass individually but fail when run together**
→ Shared state issue. Tests aren't cleaning up properly in teardown, or mocks are writing to shared files instead of test-specific temp dirs.

**Pattern: Assertions fail on exact strings**
→ Variable substitution issue. The script echo contains `$VAR` but the test asserts the literal string including `$VAR` instead of the substituted value.

**Pattern: Intermittent failures**
→ Flakiness. Look for: uninitialized variables, port conflicts in mock servers, temp file race conditions, non-deterministic output ordering.
