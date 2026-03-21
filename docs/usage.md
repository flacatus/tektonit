# Usage Guide

## Installation

```bash
git clone https://github.com/flacatus/tektonit.git
cd tektonit
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Optional LLM providers

By default, tektonit uses Gemini. To use Claude or OpenAI:

```bash
pip install -e ".[anthropic]"   # Claude support
pip install -e ".[openai]"      # OpenAI support
pip install -e ".[all]"         # All providers
```

## Scanning a catalog

Before generating tests, scan the catalog to see what resources are available:

```bash
tektonit scan /path/to/tekton-catalog
```

This outputs each resource's kind, name, params, results, steps, workspaces, and embedded scripts. No LLM calls are made.

You can also scan a remote git repository:

```bash
tektonit scan https://github.com/your-org/tekton-catalog.git
tektonit scan https://github.com/your-org/tekton-catalog.git --branch develop
```

## Generating tests

### Full catalog

```bash
export GEMINI_API_KEY=your-key-here
tektonit generate /path/to/tekton-catalog
```

This runs the full autonomous pipeline for every resource with testable scripts:
1. Generates BATS tests
2. Evaluates with skeptical reviewer
3. Runs tests
4. Fixes failures (up to 10 attempts)
5. Checks for flakiness
6. Reports results

Output:

```
Provider: gemini-2.0-flash
Scanning /path/to/catalog for Tekton resources...
Found 15 resource(s). Generating tests in-place...

  [1/15] StepAction: push-oci-artifact
    -> [generate:bats] PASS tasks/push-oci/0.1/sanity-check/push_oci_artifact_unit-tests.bats (1523+2891 tokens) [cov: 8t/12b]

  [2/15] Task: create-advisory
    -> [generate:bats] PASS (fixed after 2 attempts) tasks/create-advisory/0.1/sanity-check/create_advisory_unit-tests.bats (2105+3445 tokens) [cov: 15t/18b]

  [3/15] StepAction: trigger-jenkins
    -> [generate:bats] FAIL tasks/trigger-jenkins/0.1/sanity-check/trigger_jenkins_unit-tests.bats [CODE ISSUE: curl call uses undefined variable]

============================================================
Results: 13 generated, 1 proposed, 1 errors
Tests passing: 11/13
Code issues detected: 1
  - trigger-jenkins: curl call uses undefined variable
```

### Single resource

```bash
tektonit generate-single path/to/my-task.yaml
```

### Using different LLM providers

```bash
# Claude
export ANTHROPIC_API_KEY=your-key
tektonit generate /path/to/catalog --provider claude

# OpenAI
export OPENAI_API_KEY=your-key
tektonit generate /path/to/catalog --provider openai

# OpenAI-compatible endpoint
tektonit generate /path/to/catalog --provider openai --base-url http://localhost:8000/v1

# Specific model
tektonit generate /path/to/catalog --provider gemini --model gemini-2.0-flash
```

### Template-based generation (no LLM)

For offline use or when you don't have an API key, tektonit can generate basic structural tests using templates:

```bash
tektonit generate-template /path/to/catalog --output generated_tests/
```

These tests verify YAML structure but don't exercise script logic. Use LLM-powered generation for meaningful tests.

## Running generated tests

### BATS tests

```bash
# Run all tests in a catalog
find /path/to/catalog -name "*.bats" -path "*/sanity-check/*" -exec bats {} \;

# Run tests for a specific resource
bats path/to/sanity-check/my_task_unit-tests.bats

# Run with verbose output
bats -v path/to/sanity-check/*.bats
```

### Installing BATS

```bash
# macOS
brew install bats-core

# Ubuntu/Debian
sudo apt-get install bats

# From source
git clone https://github.com/bats-core/bats-core.git
cd bats-core && sudo ./install.sh /usr/local
```

## Working with existing tests

If a resource already has tests in its `sanity-check/` directory, tektonit generates **proposed** additional tests instead of overwriting:

```
sanity-check/
  my_task_unit-tests.bats           # Existing tests (untouched)
  my_task_unit-tests_proposed.bats  # New proposed tests
```

Review the proposed tests and merge what you want into the existing file.

## Understanding test output

### Test results

| Status | Meaning |
|---|---|
| `PASS` | Tests generated and all passing |
| `PASS (fixed after N attempts)` | Tests required fixing before passing |
| `FAIL` | Tests couldn't be fixed after 10 attempts |
| `CODE ISSUE: ...` | Agent detected a bug in the original script |
| `FLAKY` | Tests pass sometimes, fail sometimes |

### Coverage notation

`[cov: 8t/12b]` means 8 tests covering 12 branches in the script.

## Claude Code skills

If you use tektonit with Claude Code, the following skills are available:

```
/generate-tekton-tests /path/to/catalog     Full autonomous pipeline
/analyze-tekton /path/to/catalog            Deep resource analysis
/risk-audit /path/to/catalog                Prioritize by complexity
/review-tekton-tests /path/to/catalog       Skeptical test review
/diagnose-failure path/to/test.bats         Debug failing tests
/fix-test path/to/test.bats                 Progressive fix strategy
/evaluate-coverage path/to/test.bats        Branch coverage analysis
/learn-from-pr https://github.com/.../42    Learn from PR reviews
```

## Troubleshooting

### "bats not installed"

Install BATS (see above) or use the Docker image which includes it.

### "No Tekton resources found"

tektonit looks for YAML files with `apiVersion: tekton.dev/...` and a `kind` of Task, StepAction, Pipeline, or PipelineRun. Verify your files have the correct Tekton API version.

### Tests hang or timeout

The script likely has an unmocked `sleep` or `while` loop. Check the test's `setup()` function — ensure:
- `sleep` is mocked as a no-op
- Loops have mock exit conditions that trigger immediately
- No real network calls are made

### LLM rate limit errors

tektonit includes retry with exponential backoff. If you still hit rate limits, increase the poll interval or reduce the batch size:

```bash
export POLL_INTERVAL_SECONDS=7200  # 2 hours between cycles
export BATCH_SIZE=5                 # Fewer resources per cycle
```

### Tests pass locally but fail in CI

Check for cross-platform issues:
- `&>>` (bash 4+) — tektonit auto-fixes this to `>> file 2>&1`
- `#!/bin/bash` — tektonit auto-fixes this to `#!/usr/bin/env bash`
- `sed -i` — tektonit uses `sed -i'' -e` for macOS/Linux portability
- `date -d` — GNU-specific, not available on macOS
