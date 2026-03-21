# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**tektonit** is a fully autonomous LLM-powered agent that generates unit tests for scripts embedded in Tekton CI/CD resources (Tasks, StepActions, Pipelines). It works with any Tekton catalog regardless of directory structure.

- **Test framework**: BATS (Bash Automated Testing System) — no pytest
- **LLM default**: Gemini 3.1 Pro Preview (`GEMINI_API_KEY`)
- **Linting**: ruff
- **Virtual environment**: `.venv/`

## Architecture

```
tektonit/
  parser.py         - Parse Tekton YAML into structured dataclasses
  llm.py            - LLM provider abstraction (Gemini, Claude, OpenAI) with resilience
  prompts.py        - BATS prompt templates, script analysis, evaluator prompts
  test_generator.py - Autonomous test pipeline (8 intelligence capabilities)
  monitor.py        - Production daemon: clone → scan → generate → PR (Kubernetes-ready)
  state.py          - SQLite persistence: processed resources, episodic memory, PR feedback
  github_client.py  - PyGithub integration: clone, branch, commit, PR creation
  resilience.py     - Retry, circuit breaker, rate limiter
  observability.py  - Prometheus /metrics, JSON logging, health endpoints
  script_analyzer.py - Bash static analysis
  generators.py     - Template-based fallback (offline, no LLM)
  cli.py            - Click CLI entry point

.claude/
  agents/
    test-generator.md       - Orchestrator: autonomous decision-making, delegation
    failure-analyst.md      - Skeptical reviewer: finds problems before tests run
    stepaction-test-generator.md - StepAction specialist (single script)
    task-test-generator.md  - Task specialist (multi-step, workspaces, secrets)
    pipeline-test-generator.md  - Pipeline specialist (inline taskSpec only)
    pipelinerun-test-generator.md - PipelineRun specialist (inline scripts only)
  skills/
    generate-tekton-tests.md - Full autonomous pipeline
    diagnose-failure.md      - Classify and debug failing tests
    fix-test.md              - Progressive fix strategy (10 attempts)
    evaluate-coverage.md     - Branch coverage analysis
    review-tekton-tests.md   - Skeptical review of generated tests
    analyze-tekton.md        - Deep catalog analysis
    learn-from-pr.md         - Extract lessons from PR reviews
    risk-audit.md            - Prioritize resources by complexity
```

## Autonomous Agent Capabilities

The agent has 8 intelligence capabilities:

1. **Episodic Memory** — Learns from past failures, stores patterns in SQLite, injects lessons into future prompts
2. **Failure Diagnosis** — Classifies failures (mock_mismatch, assertion_mismatch, syntax_error, timeout, etc.) before fixing
3. **Multi-Agent Separation** — Generator creates, skeptical evaluator critiques, fixer resolves (avoids confirmation bias)
4. **Flaky Detection** — Runs tests 3x after passing to catch non-determinism
5. **Coverage Analysis** — Counts branches vs tests, requests more tests if coverage is low
6. **Risk-Based Prioritization** — Scores resources by complexity, processes highest-risk first
7. **PR Feedback Learning** — Harvests review comments from closed PRs, injects into future prompts
8. **Progressive Fix Strategy** — Escalates: targeted fix → rewrite mocks → full regeneration → submit as-is

## Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Scan a catalog
tektonit scan <path-or-git-url>

# Generate tests in-place (full autonomous pipeline)
GEMINI_API_KEY=... tektonit generate <path-or-git-url>

# Generate for a single resource
GEMINI_API_KEY=... tektonit generate-single <path-to-yaml>

# Run generated tests
bats <catalog>/**/sanity-check/*.bats

# Lint
ruff check . && ruff format .

# Run agent tests
python -m pytest tests/ -v
```

## Test Output

Tests are placed in `sanity-check/` next to each resource YAML:
```
<resource-dir>/
  <name>.yaml
  sanity-check/
    <name>_unit-tests.bats
```

## What Gets Tested

Every test file exercises the actual script logic:
- Script embedded verbatim via heredoc, Tekton variables stubbed with sed
- All code paths: conditionals, loops, error exits
- Exit codes verified for success and failure
- stdout/stderr output validated with exact strings from the script
- Result files (`$(results.X.path)`) content verified
- External commands mocked with exact invocation matching
- Edge cases: empty inputs, missing files, malformed data, command failures
- Cross-platform: macOS + Linux compatible (sed -i'' -e, #!/usr/bin/env bash)
