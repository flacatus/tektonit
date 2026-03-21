# Skills & Agents Reference

tektonit integrates with Claude Code through specialized subagents and user-invocable skills. This document describes each one and when to use it.

## Skills

Skills are user-invocable commands that run multi-step workflows.

### /generate-tekton-tests

**Purpose**: Run the full autonomous test generation pipeline on a catalog.

```
/generate-tekton-tests /path/to/catalog
```

Steps:
1. Install tektonit
2. Scan catalog for resources
3. Generate tests for each resource (full pipeline with evaluation, coverage, fix loop, flaky detection)
4. Report: resources scanned, tests generated, passing/failing/code issues/flaky

### /analyze-tekton

**Purpose**: Deep analysis of all Tekton resources for testability and complexity.

```
/analyze-tekton /path/to/catalog
```

Produces:
- Resource count by type (Task, StepAction, Pipeline)
- Language breakdown (bash vs python)
- Test coverage (already tested vs untested)
- Complexity distribution (simple/medium/complex)
- Most used external commands (for mock prioritization)

### /risk-audit

**Purpose**: Score and rank resources by testing risk. Helps decide what to test first.

```
/risk-audit /path/to/catalog
```

Scoring factors:
- Script lines / 10 (up to 30 points)
- Branches x2
- External commands x3
- Loops x5
- Traps x3

Output: prioritized list with scores, risk factors, and batch strategy recommendations.

### /review-tekton-tests

**Purpose**: Skeptical review of generated tests — find problems before they ship.

```
/review-tekton-tests /path/to/catalog
```

Runs all tests, then reviews each file against a 7-point checklist:
1. Mock gaps
2. Assertion precision
3. Branch coverage
4. Hanging risks
5. Mock data validity
6. Tekton variable replacement
7. Cross-platform compatibility

Also checks for trivially passing tests (tests that always pass regardless of input).

### /diagnose-failure

**Purpose**: Debug a failing test file — classify the root cause and recommend a fix strategy.

```
/diagnose-failure path/to/test.bats
```

Classifies failures into 10 types (mock_mismatch, assertion_mismatch, syntax_error, timeout, import_error, script_bug, mock_data_invalid, path_not_replaced, env_missing, cross_platform) and recommends specific fixes with line references.

### /fix-test

**Purpose**: Fix a failing test using progressive escalation.

```
/fix-test path/to/test.bats
```

Applies the 4-phase fix strategy:
- Phase 1 (attempts 1-3): Targeted fix
- Phase 2 (attempts 4-6): Rewrite mocks
- Phase 3 (attempts 7-9): Full regeneration
- Phase 4 (attempt 10): Submit as-is

Verifies fix with flaky check (3 runs).

### /evaluate-coverage

**Purpose**: Analyze how well tests cover the script's code paths.

```
/evaluate-coverage path/to/test.bats
```

Maps each test to the code path it exercises, identifies untested branches, and rates coverage (excellent/good/needs improvement/poor).

### /learn-from-pr

**Purpose**: Extract actionable lessons from PR reviews and store in episodic memory.

```
/learn-from-pr https://github.com/org/repo/pull/42
```

Fetches PR comments, classifies feedback (mock accuracy, assertion precision, missing coverage, script understanding, style preference), and stores lessons for future test generation.

## Agents

Agents are specialized subagents that handle specific types of Tekton resources. They are delegated to by the orchestrator, not invoked directly by users.

### test-generator (Orchestrator)

The main orchestrator that coordinates the entire test generation process. It:
- Plans which resources to test (risk-based)
- Delegates generation to resource-specific agents
- Evaluates results and decides on fix strategy
- Learns from outcomes

Uses the Perception -> Reasoning -> Action -> Reflection loop for every decision.

### failure-analyst

The skeptical reviewer. Reviews generated tests with a 7-point checklist and assigns severity levels (critical/moderate/minor). This agent uses a different persona than the generator to avoid confirmation bias.

### stepaction-test-generator

Specialist for StepAction resources (single script, single step). Handles:
- Language detection (bash vs python via shebang)
- Parameter substitution
- Result file verification
- External command mocking

### task-test-generator

Specialist for Task resources (multi-step, complex). Handles:
- Step-to-step dependencies
- Workspace simulation
- Volume mount simulation
- Environment variable classification (params, fieldRef, secretKeyRef, downward API)
- Sidecar and init container handling

### pipeline-test-generator

Specialist for Pipeline resources. Makes testability decisions:
- Inline `taskSpec` with scripts → testable
- External `taskRef` references → not testable (no scripts to test)
- Mixed → test only inline parts

### pipelinerun-test-generator

Specialist for PipelineRun resources. Extracts embedded `pipelineSpec` and handles:
- Nested YAML structure extraction
- Parameter value resolution
- When blocks and conditions
