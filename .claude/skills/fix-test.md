---
name: fix-test
description: Fix a failing test using progressive escalation strategy
user_invocable: true
---

# Skill: Fix Failing Test

Fix a failing BATS or pytest test file using a progressive escalation strategy. Think like a senior engineer — don't just blindly retry.

## Usage
```
/fix-test <path-to-test-file>
```

## Protocol

### Step 1: Run the test and capture output
```bash
# BATS
bats <file> 2>&1 | tee /tmp/test-output.txt

# pytest
python -m pytest <file> -v --tb=short 2>&1 | tee /tmp/test-output.txt
```

### Step 2: Diagnose (use /diagnose-failure mentally)
Classify each failure. Determine if this needs:
- **Targeted fix** — specific error, clear root cause
- **Mock rewrite** — systemic mock issues
- **Full regeneration** — fundamentally wrong approach

### Step 3: Apply progressive fix strategy

```
Phase 1 (attempts 1-3): TARGETED FIX
  → Read the error. Read the script. Fix the specific issue.
  → Common fixes: add missing mock, fix assertion string, export env var

Phase 2 (attempts 4-6): REWRITE MOCKS
  → Keep test structure. Rebuild ALL mocks from scratch.
  → Re-read the script line by line. List every command. Create fresh mocks.

Phase 3 (attempts 7-9): FULL REGENERATION
  → Start over. New approach. Different mocking strategy.
  → Use the failure output as context: "previous attempt failed because..."

Phase 10: SUBMIT AS-IS
  → Mark with # CODE_ISSUE if script bug suspected
  → Document what was tried in comments
```

### Step 4: After each fix, run and verify
```bash
bats <file>   # or pytest <file> -v
```

### Step 5: If tests pass, check for flakiness
Run 2 more times. If any run fails → flaky → fix before declaring victory.

### Step 6: Report

```
FIX RESULT:
  File: <path>
  Attempts: 3
  Strategy: targeted_fix → mock_rewrite (escalated at attempt 4)
  Final status: PASS (all 11 tests passing)

  Fixes applied:
  1. Added missing `jq` mock for `jq -r '.items[]'` invocation (line 45)
  2. Fixed assertion: changed *"error"* to *"[ERROR]: Failed to fetch manifest"*
  3. Rewrote kubectl mock to return JSON with `status` field

  Flaky check: STABLE (3/3 runs passed)
```

## Decision Rules

- If the SAME assertion fails after 3 targeted fixes → escalate to mock rewrite
- If failures change between attempts (fix one, new one appears) → systemic issue, rewrite mocks
- If error says "command not found" → missing mock, don't escalate, just add it
- If error is "syntax error" → fix syntax, don't escalate
- If error is "timeout" → mock sleep/loops, this is always a missing mock issue
- If the script ITSELF has a bug → add `# CODE_ISSUE:` comment, stop fixing, submit
