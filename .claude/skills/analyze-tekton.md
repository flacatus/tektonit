---
name: analyze-tekton
description: Deep analysis of Tekton resources — scripts, commands, complexity, testability
user_invocable: true
---

# Skill: Analyze Tekton Resources

Perform deep analysis of Tekton resources for testability, complexity, and test coverage gaps.

## Usage
```
/analyze-tekton <path-or-git-url>
```

## Protocol

### Step 1: Setup and scan
```bash
cd /Users/flacatus/WORKSPACE/devprod/test_agent && pip install -e ".[dev]"
tektonit scan <source>
```

### Step 2: Classify each resource

For each resource, determine:

| Aspect | What to look for |
|---|---|
| **Testability** | Has inline scripts? bash or python? |
| **Complexity** | Line count, branch count, external commands |
| **Language** | Shebang: bash/sh → BATS, python → pytest |
| **Dependencies** | What external commands does it call? |
| **Env vars** | From fieldRef, secretKeyRef, params, literals |
| **Results** | What does it write to $(results.X.path)? |
| **Workspaces** | Shared storage paths used |
| **Existing tests** | Does sanity-check/ already exist? |

### Step 3: Identify external command usage across catalog

Aggregate which commands are used most:
```
Command Usage:
  kubectl  — 12 resources (most common)
  curl     — 8 resources
  jq       — 7 resources
  git      — 5 resources
  oras     — 4 resources
  cosign   — 2 resources
```

This tells you which mock patterns are most important to get right.

### Step 4: Report

```
CATALOG ANALYSIS:
  Path: <source>
  Total resources: 24

  By Type:
    StepAction: 10 (8 testable, 2 no scripts)
    Task: 12 (10 testable, 2 no scripts)
    Pipeline: 2 (0 testable — all external refs)

  By Language:
    Bash: 16 resources → BATS tests
    Python: 2 resources → pytest tests

  Test Coverage:
    Already tested: 7/18 (39%)
    Untested: 11/18 (61%)

  Complexity Distribution:
    Simple (< 30 lines): 5 resources
    Medium (30-100 lines): 8 resources
    Complex (> 100 lines): 5 resources

  Most Used Commands:
    kubectl (12), curl (8), jq (7), git (5), oras (4)

  RECOMMENDATIONS:
  - 11 resources need tests
  - Start with complex bash resources (highest value)
  - Reuse kubectl mock pattern across resources
  - 2 Python resources need pytest (not BATS)
```
