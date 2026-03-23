---
name: analyze-tekton
version: 1.0.0
description: |
  Deep analysis of Tekton resources — examines scripts, commands, complexity, testability, and
  existing coverage. Provides strategic overview of a catalog before test generation.

  TRIGGER when: you want to understand a Tekton catalog before generating tests, need to assess
  testability, or want strategic guidance on where to focus testing effort.

  DO NOT TRIGGER when: you just want to generate tests (use generate-tekton-tests), or you're
  analyzing test results (use review-tekton-tests).
user_invocable: true
tags:
  - analysis
  - tekton
  - planning
  - strategy
  - discovery
examples:
  - description: Analyze catalog structure and complexity
    input: /analyze-tekton https://github.com/tektoncd/catalog
  - description: Assess testability of local tasks
    input: /analyze-tekton ./my-tasks/
  - description: Strategic overview before test generation
    input: /analyze-tekton ./catalog/ --show-complexity
resources:
  - url: https://tekton.dev/docs/pipelines/tasks/
    description: Tekton Tasks documentation
  - url: https://tekton.dev/docs/pipelines/pipelines/
    description: Tekton Pipelines documentation
  - url: https://github.com/flacatus/test_agent/blob/main/docs/architecture.md
    description: tektonit architecture and analysis methodology
---

# Skill: Analyze Tekton Resources

Deep strategic analysis of Tekton resources — understanding what's in a catalog, what's testable, how complex it is, and where testing effort should focus.

## When to Use This

Use this skill when:
- Starting work on a new Tekton catalog
- Planning test generation strategy
- Understanding catalog structure and complexity
- Assessing testability before committing effort

Don't use this skill when:
- You're ready to generate tests (use `/generate-tekton-tests`)
- You're analyzing test results (use `/review-tekton-tests`)
- You need to prioritize by risk (use `/risk-audit` instead — it's more focused)

## Usage

```
/analyze-tekton <path-or-git-url>
```

## What This Skill Does

1. Scans catalog structure and resource types
2. Identifies testable vs non-testable resources
3. Classifies scripts by language and complexity
4. Catalogs external command usage
5. Assesses existing test coverage
6. Provides strategic recommendations

This is a planning skill — it helps you understand WHAT you're dealing with before you start generating tests.

## Protocol

### Step 1: Setup and Scan

```bash
cd /Users/flacatus/WORKSPACE/devprod/test_agent && pip install -e ".[dev]"
tektonit scan <source>
```

The scan identifies:
- All Tekton resource files
- Which ones have inline scripts
- What languages those scripts use
- Basic complexity metrics

### Step 2: Classify Resources

For each resource discovered, determine:

| Aspect | What to Look For | Why It Matters |
|---|---|---|
| **Testability** | Has inline scripts? | Resources with refs aren't tested here |
| **Complexity** | Lines, branches, commands | Complex = higher test value |
| **Language** | bash/sh/python shebang | Determines BATS vs pytest |
| **Dependencies** | Which external commands | Tells you what mocks you'll need |
| **Env vars** | From where (fieldRef, secretKeyRef, params) | Setup complexity |
| **Results** | What gets written to $(results.X.path) | What to verify |
| **Workspaces** | Shared storage paths | Temp dir mocking needed |
| **Existing tests** | Does sanity-check/ exist? | Avoid duplicates |

**Why classify up front?** So you know:
- How much work this will be
- What challenges to expect
- Which resources to prioritize
- What mock patterns you'll reuse

### Step 3: Aggregate Command Usage

Across all resources, count command frequency:

```
Command Usage Across Catalog:
  kubectl  — 12 resources (40%)
  curl     — 8 resources (27%)
  jq       — 7 resources (23%)
  git      — 5 resources (17%)
  oras     — 4 resources (13%)
  cosign   — 2 resources (7%)
```

**Why this matters:** The most common commands are where you'll invest most mocking effort. Get the kubectl mock right once, reuse it 12 times.

### Step 4: Assess Coverage Status

For each resource:
- Already has tests? → Count tests, check if comprehensive
- No tests? → Flag for generation
- Has partial tests? → Decide: extend or regenerate

```
Coverage Status:
  Fully tested:    7/18 (39%)
  Partially tested: 2/18 (11%)
  Untested:        9/18 (50%)
```

**Why distinguish partial from none?** Extending existing tests requires reading and matching the existing style. Generating from scratch is often faster for complex resources.

### Step 5: Report Structure

```
CATALOG ANALYSIS:
  Source: <path-or-git-url>
  Total YAML files: 30
  Tekton resources: 24
  Testable resources: 18 (75%)

BY TYPE:
  StepAction: 10 resources
    - Testable: 8 (bash: 7, python: 1)
    - Not testable: 2 (no inline scripts, use ref)

  Task: 12 resources
    - Testable: 10 (bash: 9, python: 1)
    - Not testable: 2 (no inline scripts, all refs)

  Pipeline: 2 resources
    - Testable: 0 (all use external task refs)
    - Not testable: 2

BY LANGUAGE:
  Bash: 16 resources → Generate BATS tests
  Python: 2 resources → Generate pytest tests
  Mixed: 0 resources → Would need both

COMPLEXITY DISTRIBUTION:
  Simple (< 30 lines, few branches):
    5 resources — fast to test, low risk

  Medium (30-100 lines, some branches):
    8 resources — moderate effort, moderate value

  Complex (> 100 lines, many branches):
    5 resources — high effort, high value

TEST COVERAGE:
  Already tested: 7/18 (39%)
    - store-pipeline-status (12 tests, passing)
    - push-oci-artifact (10 tests, passing)
    - fail-if-any-step-failed (8 tests, passing)
    - (4 more...)

  Partially tested: 2/18 (11%)
    - create-advisory (3 tests, missing error paths)
    - verify-signatures (2 tests, incomplete coverage)

  Untested: 9/18 (50%)
    - run-pipeline-check (complex, 85 lines)
    - trigger-jenkins-job (medium, 45 lines)
    - (7 more...)

COMMAND USAGE:
  kubectl — 12 resources (most common)
    Pattern: get, create, delete, patch operations
    Mock strategy: Comprehensive kubectl mock with all subcommands

  curl — 8 resources
    Pattern: API calls to GitHub, Jenkins, Artifactory
    Mock strategy: HTTP mock server or static response files

  jq — 7 resources
    Pattern: JSON parsing, field extraction
    Mock strategy: Ensure JSON mocks have all referenced fields

  git — 5 resources
    Pattern: clone, checkout, push operations
    Mock strategy: Mock repo structure in temp dir

  oras — 4 resources
    Pattern: manifest fetch, pull, push operations
    Mock strategy: Mock registry with predefined responses

CHALLENGES IDENTIFIED:
  1. kubectl complexity: 12 resources use it, many different invocations
     → Recommendation: Build comprehensive kubectl mock first, reuse

  2. Python minority: Only 2 Python resources
     → Different test framework, ensure pytest setup works

  3. Workspace complexity: 6 resources use /workspace/ paths heavily
     → Need robust workspace temp dir simulation

  4. Secret volumes: 4 resources read from /var/run/secrets/
     → Mock secret files in setup

RECOMMENDATIONS:

  Priority 1: Test complex bash resources first
    - run-pipeline-check (85 lines, untested)
    - create-advisory (75 lines, partial coverage)
    These have the most logic and highest bug risk.

  Priority 2: Standardize kubectl mocking
    Since 12 resources use it, invest in a comprehensive mock
    that handles all common invocations. Reuse across all tests.

  Priority 3: Test Python resources separately
    Different framework, different patterns. Don't mix with bash batch.

  Priority 4: Simple resources last
    5 simple resources can be batched quickly at the end.

ESTIMATED EFFORT:
  - Complex resources: ~10-15 min each × 5 = 50-75 min
  - Medium resources: ~5-8 min each × 8 = 40-64 min
  - Simple resources: ~2-3 min each × 5 = 10-15 min
  Total: ~100-150 minutes for full catalog

NEXT STEPS:
  1. Run /risk-audit to get exact priority order
  2. Start with run-pipeline-check (highest complexity untested)
  3. Build reusable kubectl mock pattern
  4. Generate tests in batches by complexity tier
```

## Strategic Insights This Provides

**Scope understanding:** You know if this is a 1-hour job or a 5-hour job before starting.

**Challenge awareness:** kubectl mocking is critical, get it right first.

**Batch planning:** Can process simple resources 3-5 at a time, complex ones need individual attention.

**Risk focus:** Don't waste time testing simple resources with no branches.

**Reuse opportunities:** Build mocks once, use many times.

Use this analysis to inform your test generation strategy.
