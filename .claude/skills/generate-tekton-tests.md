---
name: generate-tekton-tests
version: 1.0.0
description: |
  Run the full autonomous test generation pipeline on a Tekton catalog — generates BATS/pytest
  tests for all embedded bash and Python scripts in Tasks, StepActions, and Pipelines.

  TRIGGER when: user asks to "generate tests for tekton", wants to run the tektonit pipeline,
  or needs comprehensive test coverage for a Tekton catalog with inline scripts.

  DO NOT TRIGGER when: user wants to test a single file manually, needs help writing tests
  themselves, or wants to understand existing tests (use review-tekton-tests instead).
user_invocable: true
tags:
  - testing
  - tekton
  - automation
  - bats
  - pytest
  - ci-cd
  - quality-assurance
examples:
  - description: Generate tests for official Tekton catalog
    input: /generate-tekton-tests https://github.com/tektoncd/catalog
  - description: Generate tests for local catalog directory
    input: /generate-tekton-tests ./my-tekton-tasks/
  - description: Generate tests for private GitHub repo
    input: /generate-tekton-tests https://github.com/myorg/tekton-catalog
resources:
  - url: https://bats-core.readthedocs.io/
    description: BATS (Bash Automated Testing System) framework documentation
  - url: https://tekton.dev/docs/
    description: Tekton Pipelines official documentation
  - url: https://docs.pytest.org/
    description: pytest framework for Python testing
  - url: https://github.com/flacatus/test_agent
    description: tektonit source code and architecture
---

# Skill: Generate Tekton Tests

Run the complete autonomous test generation pipeline on a Tekton catalog. This skill orchestrates the full workflow: risk analysis → generation → evaluation → fixing → coverage → flaky detection → learning.

## When to Use This

Use this skill when you want:
- **Full catalog coverage** — test all resources in a Tekton catalog
- **Autonomous operation** — the agent handles everything (generation, fixing, validation)
- **Production-ready tests** — verified stable, passing, comprehensive coverage

Don't use this skill when you need:
- **Single resource testing** — use `tektonit generate-single <yaml>` directly
- **Test review only** — use `/review-tekton-tests` skill
- **Test fixing only** — use `/fix-test` skill

## Skill Dependencies

This skill orchestrates multiple other skills throughout the pipeline:

- **`/risk-audit`** — Prioritizes resources by complexity before generation
- **`/diagnose-failure`** — Classifies test failures to determine fix strategy
- **`/fix-test`** — Repairs failing tests with progressive escalation
- **`/evaluate-coverage`** — Verifies branch coverage after tests pass
- **`/review-tekton-tests`** — Final quality gate before completion
- **`/learn-from-pr`** — Harvests lessons from PR feedback (if available)

**Execution Flow**:
```
scan catalog → rank by risk → for each resource:
  generate → evaluate (pre-run) → execute →
  if fail: diagnose → fix (up to 10x) → execute →
  if pass: check coverage → detect flaky → store patterns
```

## Usage

```
/generate-tekton-tests <source>
```

Where `<source>` is:
- Local directory path containing Tekton YAML files
- Git URL (e.g., `https://github.com/user/tekton-catalog`)

## What This Skill Does

For each testable resource in the catalog:

1. **Risk scoring** — Prioritizes complex scripts over simple ones
2. **Memory query** — Retrieves lessons learned from past failures
3. **Generation** — Delegates to specialist agents (StepAction, Task, Pipeline)
4. **Evaluation** — Skeptical reviewer checks for issues before running
5. **Pre-run fixes** — Corrects issues found by evaluator
6. **Coverage analysis** — Ensures all branches are tested
7. **Test execution** — Runs BATS or pytest
8. **Progressive fixing** — Up to 10 attempts with escalating strategies
9. **Flaky detection** — Runs 3x to catch non-determinism
10. **Pattern storage** — Records successes and failures for future sessions

## Protocol

### Step 1: Setup

```bash
cd /Users/flacatus/WORKSPACE/devprod/test_agent && pip install -e ".[dev]"
```

Ensure the tektonit package is installed in the Python environment.

### Step 2: Risk Audit (Optional but Recommended)

```bash
tektonit scan <source>
```

This shows you:
- How many resources are testable
- Which ones are complex vs simple
- Which already have tests
- Suggested priority order

Understanding the catalog structure before generation helps you:
- Estimate how long generation will take
- Identify if any resources need special attention
- Confirm you're testing what you think you're testing

### Step 3: Run Generation Pipeline

```bash
GEMINI_API_KEY=... tektonit generate <source>
```

The pipeline runs autonomously. You'll see:
- Which resource is being processed
- Generation attempts
- Test results (pass/fail)
- Fix attempts and strategies
- Final outcome for each resource

### Step 4: Review Results

After pipeline completes, check for each resource:

| Status | Meaning | What to Do |
|---|---|---|
| **PASS** | Tests generated and passing | Verify they're not trivially passing (check assertions) |
| **FAIL** | Couldn't fix after 10 attempts | Use `/diagnose-failure` to investigate |
| **CODE ISSUE** | Script has a bug | Review script, may need upstream fix |
| **FLAKY** | Sometimes passes, sometimes fails | Use `/fix-test` with focus on stability |

### Step 5: Validate Generated Tests

Don't trust the agent blindly. Run all tests manually to confirm:

```bash
# BATS tests
find <source> -name "*.bats" -path "*/sanity-check/*" -exec bats {} \;

# pytest tests
find <source> -name "*.py" -path "*/sanity-check/*" -exec python -m pytest {} -v \;
```

Look for:
- Tests that pass too easily (no real assertions)
- Tests that test the mock instead of the script
- Missing edge cases

### Step 6: Report to User

Provide a summary with:
- Resources scanned (by type: Task, StepAction, Pipeline)
- Tests generated vs proposed additions (to existing test files)
- Test results breakdown (passing / failing / code issues / flaky)
- Coverage metrics (tests per branch ratio)
- Fix attempts used and strategies applied
- Key lessons learned (new patterns discovered)
- Recommendations (which failed tests need manual review)

## Understanding Test Structure

Generated tests follow these patterns:

**BATS (bash scripts)**:
- Script embedded verbatim in `setup()`
- Tekton variables replaced with test values
- External commands mocked with exact invocation matching
- Tests organized by suite (Happy Path, Error Handling, Edge Cases)

**pytest (Python scripts)**:
- Script embedded in fixture with textwrap.dedent
- Parameters replaced inline
- Minimal mocking (Python scripts typically simpler than bash)
- Tests grouped in classes by scenario

## Common Outcomes and Next Steps

**Scenario: All tests pass first try**
→ Great! But verify they're comprehensive. Run `/evaluate-coverage` to check if all branches are tested.

**Scenario: Most tests fail with mock_mismatch**
→ The generator misunderstood how commands are called. Check if there's a pattern (e.g., all jq mocks fail). The fix loop will rewrite mocks at attempts 4-6.

**Scenario: Tests pass but are marked flaky**
→ Non-determinism detected. Common causes: port conflicts, uninitialized variables, race conditions. The fix loop addresses these.

**Scenario: Tests fail with script_bug classification**
→ The original script has a bug. Review the script manually. This is valuable feedback — you found a real issue.

## Performance Expectations

- **Simple resources** (< 30 lines, few branches): 1-2 minutes per resource
- **Medium resources** (30-100 lines): 3-5 minutes per resource
- **Complex resources** (> 100 lines, many branches): 5-15 minutes per resource

If a resource is taking longer than 15 minutes, it's likely stuck in the fix loop. Check the output to see what's failing.

## What This Skill Doesn't Do

- **Doesn't test non-Tekton code** — this is Tekton-specific
- **Doesn't test container images** — only embedded scripts
- **Doesn't test declarative YAML** — only imperative script logic
- **Doesn't test external StepAction refs** — those are tested in their own catalog
