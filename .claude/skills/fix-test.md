---
name: fix-test
version: 1.0.0
description: |
  Fix failing tests using progressive escalation strategy. Diagnoses failures, applies targeted
  fixes, escalates to mock rewriting or full regeneration as needed, up to 10 attempts.

  TRIGGER when: tests are failing and you need to fix them, especially when working through
  multiple fix attempts that may require escalating strategies.

  DO NOT TRIGGER when: tests haven't been run yet (generate first), tests are already passing
  (use evaluate-coverage instead), or you just need diagnosis without fixing (use diagnose-failure).
user_invocable: true
tags:
  - debugging
  - testing
  - repair
  - automation
  - escalation
examples:
  - description: Fix failing BATS test with progressive strategy
    input: /fix-test tasks/git-clone/sanity-check/git_clone_unit-tests.bats
  - description: Fix pytest test that's been failing for multiple attempts
    input: /fix-test tasks/python-scan/sanity-check/python_scan_unit-tests.py
  - description: Apply full regeneration as last resort
    input: /fix-test --escalate full tasks/complex-task/sanity-check/complex_task_unit-tests.bats
resources:
  - url: https://bats-core.readthedocs.io/
    description: BATS testing framework reference
  - url: https://docs.pytest.org/en/stable/
    description: pytest framework documentation
---

# Skill: Fix Failing Test

Fix failing BATS or pytest tests using progressive escalation. Think like a senior engineer — diagnose first, apply targeted fixes, escalate only when patterns indicate deeper issues.

## When to Use This

Use this skill when:
- Tests have been generated and run
- Tests are failing
- You need systematic fix attempts with escalation

Don't use this skill when:
- Tests haven't been generated yet
- Tests are passing (use `/evaluate-coverage` instead)
- You want diagnosis only without fixes (use `/diagnose-failure`)

## Skill Dependencies

This skill calls:

- **`/diagnose-failure`** — Always runs first to classify root cause before attempting fixes

**Progressive Strategy** (10 attempts max):
```
1-3: targeted fixes → diagnose → apply specific fix → rerun
4-6: rewrite mocks → diagnose → regenerate all mocks → rerun
7-9: full regeneration → diagnose → regenerate entire test → rerun
10: submit as-is → mark test, store failure pattern, continue
```

Each escalation level is triggered by failure patterns (e.g., persistent mock_mismatch → rewrite mocks at attempt 4).

## Usage

```
/fix-test <path-to-test-file>
```

## The Progressive Escalation Strategy

**Why escalate?** Because not all failures are created equal. A simple typo needs a simple fix. A fundamental misunderstanding of the script needs a fresh start. Escalating wastes effort on simple fixes, but not escalating wastes effort on deep issues.

### Phase 1: Targeted Fix (Attempts 1-3)

**Strategy:** Read the error, read the script, fix the specific issue.

**When this works:**
- Clear, specific error messages
- One or two tests failing out of many
- Different failures for different reasons

**Common fixes in this phase:**
- Add missing mock for a command
- Fix assertion string to match exact script output
- Export environment variable that script reads
- Add sed replacement for Tekton variable
- Fix JSON syntax in mock data

**Why 3 attempts?** Allows fixing multiple independent issues (e.g., one test needs mock, another needs assertion, third needs env var). But if same issue persists, escalate.

### Phase 2: Rewrite Mocks (Attempts 4-6)

**Strategy:** Keep test structure, rebuild ALL mocks from scratch.

**When to escalate here:**
- Same command fails across multiple tests
- Mock data format consistently wrong
- Multiple mock_mismatch failures persist after targeted fixes

**What "rewrite mocks" means:**
1. Re-read the script line by line
2. List EVERY external command call with exact flags
3. Throw away old mocks
4. Create fresh mocks matching exact invocations
5. Regenerate mock data files in correct format

**Why rewrite instead of fix?** When mocks have systemic issues (wrong data format, missing flag variants), fixing individual cases often misses the pattern. Starting fresh ensures complete coverage.

### Phase 3: Full Regeneration (Attempts 7-9)

**Strategy:** Start over with failure context, try different approach.

**When to escalate here:**
- Mock rewrites didn't help
- Fundamentally wrong understanding of script
- Failures change between attempts (whack-a-mole)

**What "full regeneration" means:**
1. Review all previous failure output
2. Identify what was misunderstood about the script
3. Try completely different approach:
   - Different mocking strategy (inline vs files)
   - Different test organization (one test per path vs comprehensive)
   - Different mock data structure
4. Regenerate the entire test file

**Why 3 attempts at this phase?** Allows trying 2-3 different approaches. If none work, either the script is genuinely hard to test or has a bug.

### Phase 10: Submit As-Is

**Strategy:** Mark "needs review", document what was tried.

**When to do this:**
- 9 attempts exhausted
- Script likely has a bug, OR
- Script is genuinely difficult to test (complex state, external dependencies)

**What to include:**
- Add `# CODE_ISSUE: <description>` if script bug suspected
- Document in comments what was tried and why it failed
- Include diagnostic output
- Flag for human review

**Why stop at 10?** Diminishing returns. If 9 diverse attempts failed, something deeper is wrong. Human judgment needed.

## Protocol

### Step 1: Run Test and Capture Output

```bash
# BATS
bats <file> 2>&1 | tee /tmp/test-output.txt

# pytest
python -m pytest <file> -v --tb=short 2>&1 | tee /tmp/test-output.txt
```

Capture FULL output, including error details, line numbers, actual vs expected values.

### Step 2: Diagnose

Use `/diagnose-failure` mentally or explicitly:
- Classify each failure type
- Identify patterns
- Determine if targeted fix, mock rewrite, or regeneration is appropriate

**Why diagnose first?** Applying random fixes wastes attempts. Understanding the root cause leads to correct fixes.

### Step 3: Apply Fix

Based on phase (determined by attempt number):

**Phase 1 (1-3): Targeted fixes**
```bash
# Example: Add missing mock
cat << 'EOF' >> "$MOCK_BIN/kubectl"
elif [[ "$1" == "get" && "$2" == "pods" && "$3" == "-o" ]]; then
  echo '{"items": []}'
EOF

# Example: Fix assertion
sed -i'' -e 's|*"Processing"*|*"[INFO]: Processing 3 items"*|' test.bats

# Example: Export env var
echo 'export MY_VAR="test-value"' >> setup() block
```

**Phase 2 (4-6): Mock rewrite**
```bash
# Rebuild kubectl mock from scratch after analyzing all invocations
cat << 'EOF' > "$MOCK_BIN/kubectl"
#!/usr/bin/env bash
case "$1 $2 ${3:-} ${4:-}" in
  "get pods -o json") echo '{"items": []}' ;;
  "get pods -o yaml") echo 'items: []' ;;
  "get pods") echo 'NAME STATUS' ;;
  *) echo "" >&2; exit 1 ;;
esac
EOF
```

**Phase 3 (7-9): Full regeneration**
```bash
# Regenerate with context from failures
# Use different mocking approach (e.g., data files instead of inline)
# Reorganize tests differently (e.g., one setup per step vs shared)
```

### Step 4: Run and Verify

```bash
bats <file>   # or pytest <file> -v
```

Check results:
- All tests passing? → Proceed to flaky check
- Some passing, some failing? → Diagnose new failures, continue fixing
- All still failing with same errors? → Consider escalating

### Step 5: Flaky Check (If Tests Pass)

Run 2 more times:
```bash
for i in 1 2; do bats <file> || echo "FLAKY DETECTED"; done
```

If any run fails → flaky → fix before declaring victory.

Common flakiness causes and fixes:
- Port conflicts → Use random port selection
- Uninitialized variables → Initialize in setup()
- Temp file races → Use unique prefixes per test
- Non-deterministic ordering → Sort output before asserting

### Step 6: Report

```
FIX RESULT:
  File: <path>
  Initial failures: 8 tests
  Attempts used: 3
  Strategy: targeted_fix (attempt 1), targeted_fix (attempt 2), mock_rewrite (attempt 3)
  Final status: PASS (all 8 tests passing)

  Fixes applied:
  Attempt 1:
    - Added jq mock for `jq -r '.items[]'` invocation
    - Fixed assertion: changed *"error"* to *"[ERROR]: Failed to fetch manifest"*

  Attempt 2:
    - Exported GITHUB_TOKEN environment variable

  Attempt 3:
    - Rewrote kubectl mock to handle all flag variants (-o json, -o yaml, no flags)
    - Regenerated mock data files with complete field structure

  Flaky check: STABLE (3/3 runs passed)
  Pattern learned: kubectl mocks must handle -o flag variants explicitly
```

## Decision Rules

These guide when to escalate:

**Don't escalate if:**
- Error message is clear and specific ("command not found: xyz")
- Only 1-2 tests failing
- Each failure has different root cause
- Syntax errors (fix syntax, don't regenerate)

**Do escalate to Phase 2 if:**
- Same assertion fails after 3 fixes
- Multiple tests fail with same command
- Mock data format consistently wrong
- Failures involve same component

**Do escalate to Phase 3 if:**
- Mock rewrites didn't help
- Failures change between attempts (fix one issue, new one appears)
- Fundamentally wrong approach to mocking/testing

**Consider script bug if:**
- After 3 attempts, same logic path fails
- Script's error handling doesn't match its code
- Script would fail with valid production inputs
- Multiple tests fail on unreachable code paths

## What Success Looks Like

Good fix outcomes:
- Tests pass on first targeted fix (clear error, obvious fix)
- Tests pass after mock rewrite (systemic issue identified and fixed)
- Pattern identified and recorded for future generations

Bad fix outcomes to avoid:
- 10 attempts of the same fix type (should have escalated)
- Fixing symptoms not root cause (assertion changes when mock is wrong)
- Tests pass but are trivially passing (fixed by weakening assertions)

## Common Fix Patterns

**Pattern: All JSON parsing tests fail**
→ Mock returns invalid JSON or wrong structure. Rewrite mock data files with correct JSON schema.

**Pattern: Tests pass individually, fail together**
→ Shared state contamination. Fix teardown to clean up properly, ensure mocks use test-specific temp dirs.

**Pattern: Same assertion fails repeatedly**
→ Mock returns wrong data. Don't keep changing assertion, fix the mock's output.

**Pattern: Failures move around**
→ Multiple independent issues, or systemic mock problem. If same component, rewrite. If different components, continue targeted fixes.
