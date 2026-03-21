# Architecture

## Overview

tektonit is built as an autonomous agent with a modular architecture. The system can run as a CLI tool for one-off test generation or as a Kubernetes deployment that continuously monitors a Tekton catalog and opens PRs with generated tests.

```
                    ┌─────────────────────────────────────┐
                    │            Entry Points             │
                    │  cli.py (interactive)                │
                    │  monitor.py (production daemon)      │
                    └────────────┬────────────────────────┘
                                 │
                    ┌────────────▼────────────────────────┐
                    │        Test Generator Pipeline       │
                    │  test_generator.py                   │
                    │                                      │
                    │  generate → evaluate → run → fix     │
                    │  → coverage → flaky → learn          │
                    └──┬─────────┬──────────┬─────────────┘
                       │         │          │
              ┌────────▼──┐  ┌──▼─────┐  ┌─▼──────────┐
              │  parser.py │  │ llm.py │  │ prompts.py │
              │            │  │        │  │            │
              │ YAML →     │  │ Gemini │  │ System     │
              │ dataclass  │  │ Claude │  │ prompts +  │
              │            │  │ OpenAI │  │ templates  │
              └────────────┘  └────────┘  └────────────┘
                       │
              ┌────────▼────────────────────────────────┐
              │          Production Layer                │
              │  state.py        SQLite persistence      │
              │  github_client.py  PR creation           │
              │  resilience.py   Retry + circuit breaker │
              │  observability.py  Metrics + health      │
              └─────────────────────────────────────────┘
```

## Core components

### parser.py — Tekton YAML parser

Parses any Tekton YAML file into a `TektonResource` dataclass. Handles:

- **Tasks** — params, results, steps (with embedded scripts), workspaces, volumes
- **StepActions** — single-step resources with params, results, env vars
- **Pipelines** — pipeline-level params, tasks, finally blocks
- **PipelineRuns** — embedded pipelineSpec extraction

Key function: `load_all_resources(path)` recursively discovers all Tekton YAMLs in a directory.

The parser is structure-agnostic — it works with any directory layout, not just the standard `tasks/<name>/<version>/` convention.

### llm.py — LLM provider abstraction

Unified interface for multiple LLM providers:

```python
class LLMProvider:
    def generate(self, system_prompt: str, user_prompt: str) -> LLMResponse
    def name(self) -> str
```

Supported providers:
- **Gemini** (default) — via `google-genai` SDK
- **Claude** — via `anthropic` SDK (optional dependency)
- **OpenAI** — via `openai` SDK, supports custom base URLs (optional dependency)

### prompts.py — Prompt engineering

Contains the system prompts and prompt builders that drive test generation quality:

- `BATS_SYSTEM_PROMPT` — Detailed instructions for generating BATS tests with exact mocking rules
- `PYTEST_SYSTEM_PROMPT` — Instructions for Python script testing
- `build_bats_prompt()` — Constructs the user prompt with resource YAML, script analysis, and mock requirements
- `has_testable_scripts()` — Detects whether a resource has bash or Python scripts
- `get_script_languages()` — Returns the set of languages found in embedded scripts

### test_generator.py — Autonomous pipeline

The core brain of the agent. Implements the full 8-capability pipeline:

```
generate_and_fix(resource, provider, language, state_store)
│
├── 1. Build context (episodic memory + PR feedback)
├── 2. Generate tests (call LLM with system + user prompt)
├── 3. Evaluate with skeptical evaluator (separate LLM persona)
├── 4. Fix evaluator issues
├── 5. Analyze coverage, request more tests if low
├── 6. Run tests (bats or pytest)
├── 7. Progressive fix loop (up to 10 attempts)
│   ├── Attempts 1-3: Targeted fix with diagnosis
│   ├── Attempts 4-6: Rewrite all mocks
│   ├── Attempts 7-9: Full regeneration
│   └── Attempt 10: Last try
├── 8. Flaky detection (run 2 more times)
└── 9. Record learned patterns
```

Key supporting functions:
- `_diagnose_failure()` — Classifies test failures into 8 categories
- `_evaluate_tests()` — Runs a separate "skeptical evaluator" LLM persona
- `_analyze_coverage()` — Counts branches vs tests
- `_check_flaky()` — Runs tests multiple times to detect flakiness
- `_detect_code_issue()` — Detects when the original script has a bug

### monitor.py — Production daemon

Runs in Kubernetes as a continuous monitoring loop:

```
while running:
    1. Clone/pull latest catalog from GitHub
    2. Scan for resources without tests
    3. Collect PR review feedback (learning)
    4. Sort resources by risk score (complexity)
    5. For each resource (up to batch size):
       a. Generate tests with full autonomous pipeline
       b. Create git branch, commit, push
       c. Open PR with test results
    6. Sleep until next cycle
```

Features:
- Graceful shutdown on SIGTERM
- SQLite state persistence (survives pod restarts)
- Circuit breaker for LLM failures
- Prometheus metrics and health endpoints

### state.py — Persistence layer

SQLite-backed persistence with three tables:

| Table | Purpose |
|---|---|
| `processed_resources` | Track which resources have been tested |
| `failure_patterns` | Episodic memory — failure types and fixes that worked |
| `pr_feedback` | Lessons from PR review comments |

The state database survives pod restarts via a PersistentVolumeClaim.

### resilience.py — Fault tolerance

Production hardening for LLM API calls:

- **Retry with exponential backoff** — Uses tenacity, retries on rate limits and transient errors
- **Circuit breaker** — Opens after 5 consecutive failures, prevents wasting tokens
- **Token bucket rate limiter** — Prevents hitting API rate limits

### observability.py — Monitoring

- **Prometheus metrics** — `tektonit_tests_generated`, `tektonit_tests_fixed`, `tektonit_prs_created`, `tektonit_cycle_duration_seconds`, `tektonit_errors_total`
- **Health endpoints** — `/healthz` (liveness), `/readyz` (readiness)
- **Structured JSON logging** — via `python-json-logger`

## Data flow

### CLI flow (interactive)

```
User runs: tektonit generate /path/to/catalog
  │
  ├── parser.load_all_resources() → list[TektonResource]
  ├── For each resource with testable scripts:
  │   ├── test_generator.generate_and_fix() → result dict
  │   │   ├── prompts.build_bats_prompt() → user prompt
  │   │   ├── llm.generate() → LLMResponse
  │   │   ├── _evaluate_tests() → evaluator feedback
  │   │   ├── Run bats/pytest
  │   │   └── Fix loop (if failing)
  │   └── Write test file to sanity-check/
  └── Print summary
```

### Monitor flow (production)

```
monitor.run_cycle()
  │
  ├── github_client.clone_or_pull()
  ├── parser.load_all_resources()
  ├── _collect_pr_feedback() → learn from reviews
  ├── _sort_by_risk() → prioritize complex resources
  ├── For each unprocessed resource:
  │   ├── test_generator.generate_and_fix(state_store=state)
  │   ├── github_client.create_branch_commit_push()
  │   └── github_client.create_pr()
  └── state.mark_processed()
```

## Multi-agent design

tektonit uses multi-agent separation to avoid confirmation bias (based on MAR research):

| Role | System Prompt | Purpose |
|---|---|---|
| **Generator** | `BATS_SYSTEM_PROMPT` | Creates tests — optimistic, comprehensive |
| **Evaluator** | `EVALUATOR_SYSTEM_PROMPT_BATS` | Reviews tests — skeptical, critical |
| **Fixer** | `BATS_SYSTEM_PROMPT` + diagnosis | Fixes specific issues identified |

The evaluator uses a different persona than the generator, preventing the same LLM from self-validating its own output.
