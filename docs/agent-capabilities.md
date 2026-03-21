# Autonomous Agent Capabilities

tektonit implements 8 intelligence capabilities that make it behave like a senior test engineer rather than a simple code generator.

## 1. Episodic Memory

**Problem**: Without memory, the agent repeats the same mistakes across sessions.

**Solution**: SQLite-backed pattern storage. After every fix attempt, the agent records:
- What failure type occurred (mock_mismatch, assertion_drift, etc.)
- What features the script had (jq, curl, kubectl, loops, etc.)
- What fix worked (or didn't work)
- How many times this pattern has been seen

Before generating tests for a new resource, the agent queries for relevant patterns and injects them into the prompt:

```
## LESSONS FROM PAST FAILURES (episodic memory)
- [mock_mismatch] kubectl mock didn't handle -o json flag → Fix: always include output format flags in mock matching (seen 5x)
- [timeout] while loop with sleep 5 caused hang → Fix: mock sleep as no-op, mock exit condition for loop (seen 3x)
```

This prevents the agent from making the same mistakes it has already learned to fix.

## 2. Failure Diagnosis

**Problem**: Blindly retrying a failing test without understanding WHY it fails leads to random fixes.

**Solution**: Before every fix attempt, the agent classifies the failure:

| Type | Symptoms | What went wrong |
|---|---|---|
| `mock_mismatch` | "command not found", wrong output | Mock doesn't match the script's invocation |
| `assertion_mismatch` | Assertion fails with wrong string | Test expects different output than script produces |
| `syntax_error` | Parse error, unexpected token | Broken bash/python syntax |
| `timeout` | Test hangs | Unmocked sleep, infinite loop, real network call |
| `import_error` | ModuleNotFoundError | Missing Python dependency |
| `script_bug` | Script logic is wrong | Bug in original code, not the test |
| `runtime_error` | General exception | Missing env var, invalid JSON, wrong path |

The diagnosis is injected into the fix prompt so the LLM knows exactly what to fix and how.

## 3. Multi-Agent Separation

**Problem**: When the same LLM generates tests AND validates them, it suffers from confirmation bias — it won't find its own mistakes.

**Solution**: Two distinct LLM personas with different system prompts:

- **Generator** — Uses `BATS_SYSTEM_PROMPT`. Optimistic. Creates comprehensive tests.
- **Evaluator** — Uses `EVALUATOR_SYSTEM_PROMPT_BATS`. Skeptical. Finds problems the generator missed.

The evaluator checks for:
1. Mock gaps — commands in the script without mocks
2. Assertion drift — assertions that don't match exact script output
3. Missing branches — untested if/elif/else/case paths
4. Hanging risks — loops without exit conditions, unmocked sleep
5. Mock data bugs — invalid JSON, missing fields
6. Path/env gaps — Tekton variables not replaced

If the evaluator finds critical issues, the agent fixes them BEFORE running the tests.

## 4. Flaky Detection

**Problem**: A test that passes once might not be stable. Flaky tests erode trust.

**Solution**: After tests pass, run them 2 more times. If any run fails, the test is marked as flaky.

Common flaky causes the agent looks for:
- Port conflicts in mock HTTP servers
- Temp file race conditions
- Non-deterministic output ordering (e.g., JSON key order)
- System clock dependencies

If flakiness is detected, the agent attempts one more fix specifically targeting the non-determinism.

## 5. Coverage Analysis

**Problem**: Tests might pass but only cover the happy path, leaving error handling untested.

**Solution**: The agent counts:
- **Script branches**: if/elif/else/case/except blocks in the original script
- **Test blocks**: @test (BATS) or def test_ (pytest) in the generated tests
- **Coverage ratio**: tests / branches

If coverage is below 50% or fewer than 3 tests, the agent requests additional tests from the LLM, specifically targeting untested branches.

## 6. Risk-Based Prioritization

**Problem**: Processing simple resources first wastes LLM tokens on low-value targets.

**Solution**: Score each resource by complexity and process highest-risk first:

| Factor | Points | Rationale |
|---|---|---|
| Script lines / 10 | up to 30 | More code = more risk |
| Branches (if/elif/else/case) | x2 each | More logic paths |
| External commands | x3 each | Integration points |
| Loops (while/until/for) | x5 each | Infinite loop risk |
| Traps (error handlers) | x3 each | Error handling complexity |

A resource with 200 lines, 15 branches, 8 external commands, and 2 loops scores much higher than a simple 20-line script — and gets tested first because it has the most value from testing.

## 7. PR Feedback Learning

**Problem**: Human reviewers catch issues the agent misses, but feedback is lost after the PR.

**Solution**: The agent harvests review comments from closed PRs and stores them in the `pr_feedback` table. Before generating tests for a resource of the same kind, it injects relevant feedback:

```
## FEEDBACK FROM PR REVIEWS
- When mocking commands that pipe to jq, mock both output AND exit code
- Always test empty/null JSON input for JSON-parsing scripts
- exit 1 inside functions bypasses || true — test accordingly
```

This creates a feedback loop: human review -> stored lesson -> better future tests -> fewer review comments.

## 8. Progressive Fix Strategy

**Problem**: Simple retry loops waste tokens. If the same approach failed 3 times, trying it a 4th time won't help.

**Solution**: Escalate the fix strategy based on attempt number:

```
Phase 1 (attempts 1-3): TARGETED FIX
  → Diagnose the specific error
  → Fix only that issue
  → Include diagnosis context in the prompt

Phase 2 (attempts 4-6): REWRITE MOCKS
  → Keep the test structure (assertions, test names)
  → Rebuild ALL mocks from scratch
  → Re-read the script line by line for exact command patterns

Phase 3 (attempts 7-9): FULL REGENERATION
  → Start completely over
  → Include all failure context: "previous approach failed because..."
  → Use a different mocking strategy

Phase 4 (attempt 10): LAST TRY
  → One final targeted fix
  → If it fails, submit as-is with documentation
  → Mark CODE_ISSUE if script bug is suspected
```

Each phase change forces the LLM into a fundamentally different approach rather than repeating the same strategy.

## How capabilities work together

The 8 capabilities form a feedback loop:

```
                    ┌──── Episodic Memory ◄────┐
                    │                          │
                    ▼                          │
Risk Prioritize → Generate → Evaluate → Run   │
                                │              │
                        fail?   │   pass?      │
                    ┌───────────┘   │          │
                    ▼               ▼          │
              Diagnose         Flaky Check     │
                    │               │          │
                    ▼               │          │
              Progressive Fix      │          │
                    │               │          │
                    └───────────────┴──► Learn ┘
                                        │
                              PR Feedback ◄── Human Review
```

Each cycle strengthens future generations through learned patterns and reviewer feedback.
