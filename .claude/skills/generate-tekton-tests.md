---
name: generate-tekton-tests
description: Generate unit tests for all Tekton resources in a catalog (fully autonomous pipeline)
user_invocable: true
---

# Skill: Generate Tekton Tests

Run the full autonomous test generation pipeline on a Tekton catalog.

## Usage
```
/generate-tekton-tests <source>
```

Where `<source>` is a local path or git URL containing Tekton YAML files.

## Protocol

### Step 1: Setup
```bash
cd /Users/flacatus/WORKSPACE/devprod/test_agent && pip install -e ".[dev]"
```

### Step 2: Risk Audit (optional but recommended)
```bash
tektonit scan <source>
```
Identify which resources have the most complex scripts. Prioritize those.

### Step 3: Generate tests (full autonomous pipeline)
```bash
GEMINI_API_KEY=... tektonit generate <source>
```

This runs the complete pipeline for each resource:
1. Query episodic memory for relevant past failures
2. Generate tests (BATS for bash, pytest for Python)
3. Evaluate with skeptical reviewer (multi-agent)
4. Fix evaluator issues before running
5. Analyze coverage, add tests if low
6. Run tests
7. Progressive fix loop (up to 10 attempts)
8. Flaky detection (3 runs)
9. Record learned patterns

### Step 4: Review results

For each resource, check:
- **PASS** — Tests generated and passing. Verify they're not trivially passing.
- **FAIL** — Tests couldn't be fixed after 10 attempts. Use `/diagnose-failure` to investigate.
- **CODE ISSUE** — Agent detected a bug in the original script. Review manually.
- **FLAKY** — Tests pass sometimes, fail sometimes. Use `/fix-test` to stabilize.

### Step 5: Run all generated tests manually
```bash
# BATS tests
find <source> -name "*.bats" -path "*/sanity-check/*" -exec bats {} \;

# pytest tests
find <source> -name "*.py" -path "*/sanity-check/*" -exec python -m pytest {} -v \;
```

### Step 6: Report to the user
- Resources scanned (count by type: Task, StepAction, Pipeline)
- Tests generated vs proposed (additions to existing)
- Test results: passing / failing / code issues / flaky
- Coverage: tests per branches ratio
- Fix attempts used
- Lessons learned (new patterns stored in episodic memory)
