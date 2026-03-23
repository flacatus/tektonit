---
name: risk-audit
version: 1.0.0
description: |
  Audit Tekton catalog and rank resources by testing risk/complexity. Provides priority order
  for test generation based on where bugs are most likely (complex logic, many branches, etc.).

  TRIGGER when: you need to prioritize which resources to test first in a large catalog, or want
  data-driven guidance on where testing effort will have highest impact.

  DO NOT TRIGGER when: only testing a single resource, or when you want general catalog analysis
  (use analyze-tekton for broader strategic view).
user_invocable: true
tags:
  - risk-analysis
  - prioritization
  - strategy
  - complexity
  - planning
examples:
  - description: Audit catalog and show high-risk resources
    input: /risk-audit https://github.com/tektoncd/catalog
  - description: Prioritize tasks in local directory
    input: /risk-audit ./tasks/ --sort-by-risk
  - description: Show risk scores with explanations
    input: /risk-audit ./catalog/ --explain-scores
resources:
  - url: https://github.com/flacatus/test_agent/blob/main/tektonit/script_analyzer.py
    description: Script complexity analysis implementation
  - url: https://en.wikipedia.org/wiki/Cyclomatic_complexity
    description: Code complexity metrics and risk assessment
---

# Skill: Risk Audit

Scan Tekton catalog and rank resources by testing risk/value. Think like a test strategist — identify where bugs are most likely based on complexity, then prioritize testing effort there.

## When to Use This

Use this skill when:
- Starting work on a large catalog (10+ resources)
- You need to prioritize which resources to test first
- You want data-driven justification for where to focus
- You have limited time and need highest-impact tests

Don't use this skill when:
- Only 1-3 resources to test (just test them all)
- You want general catalog overview (use `/analyze-tekton`)
- Resources are already prioritized by other means

## The Risk-First Philosophy

**Why prioritize by risk?** Because not all code is equally likely to fail:

- 10-line script with no branches → probably works, low test value
- 100-line script with 15 branches and 5 external commands → high bug probability, high test value

Testing resources in random order wastes effort on simple scripts while complex ones remain untested. Risk-first ensures maximum bug-finding per hour invested.

## Usage

```
/risk-audit <path-or-git-url>
```

## Risk Scoring Formula

For each resource with testable scripts:

```
Risk Score =
  (Lines / 10)                  [max 30] — More code = more can go wrong
  + (Branches × 2)              [no max] — More paths = more edge cases
  + (External commands × 3)     [no max] — Integration points = failure points
  + (Loops × 5)                 [no max] — Infinite loop risk, retry complexity
  + (Traps × 3)                 [no max] — Error handling complexity
  + (JSON processing × 3)       [no max] — Parsing errors, schema dependencies
  + (Network calls × 4)         [no max] — External dependencies, error handling
  + (File I/O × 2)              [no max] — State management, race conditions
```

**Why these weights?**

- **Lines:** General complexity proxy, but capped (300-line script ≠ 30x risk of 10-line)
- **Branches:** Each branch doubles test cases needed, high weight
- **Commands:** Each external call is a mock needed, integration risk
- **Loops:** Hang risk, retry logic complexity, worth 5x a simple branch
- **Traps:** Error handling is hard to get right, signals complex error paths
- **JSON:** Parsing failures, schema mismatches common
- **Network:** Real external dependencies, timeouts, error handling critical
- **File I/O:** Results, workspaces — state complexity

## Protocol

### Step 1: Scan Catalog

```bash
cd /Users/flacatus/WORKSPACE/devprod/test_agent && pip install -e ".[dev]"
tektonit scan <path>
```

This identifies all resources and their basic properties.

### Step 2: Extract Scripts and Analyze

For each resource with inline scripts:

1. Count lines (excluding comments/blanks)
2. Count branches (if/elif/else/case — including nested)
3. List external commands (kubectl, curl, jq, git, oras, etc.)
4. Identify loops (while/until/for)
5. Identify error handlers (trap, set -e)
6. Identify JSON processing (jq, python json module)
7. Identify network calls (curl, wget, http requests)
8. Identify file operations (reading/writing results, workspaces)

Calculate risk score using formula above.

### Step 3: Check Existing Coverage

For each resource:
- Has `sanity-check/` directory?
- Has `.bats` or `.py` file?
- If yes, count tests and note status (passing/failing)

Coverage status:
- **UNTESTED** — No test file exists
- **TESTED** — Has tests, note how many and if passing
- **PARTIAL** — Has some tests but incomplete coverage

### Step 4: Sort by Risk Score (Descending)

Highest risk = highest priority for testing.

### Step 5: Report

```
RISK AUDIT REPORT
Catalog: <path>
Resources scanned: 24
Testable resources: 18
Already tested: 7
Untested: 11

PRIORITY ORDER (highest risk first):

 #   Score  Kind        Name                     Lines  Branches  Cmds  Loops  Status
 1.  85.0   Task        create-advisory          67     8         6     2      UNTESTED
 2.  72.5   StepAction  push-oci-artifact        54     6         7     1      UNTESTED
 3.  65.0   Task        run-pipeline-check       58     7         5     1      UNTESTED
 4.  58.0   StepAction  trigger-jenkins-job      42     5         4     0      UNTESTED
 5.  45.0   Task        verify-signatures        38     4         5     0      TESTED (5/8 passing)
 6.  42.0   StepAction  store-pipeline-status    35     4         4     1      TESTED (12/12 passing)
 7.  38.0   Task        fail-if-any-step-failed  32     3         3     1      TESTED (8/8 passing)
 8.  35.0   StepAction  secure-push-oci          28     3         4     1      TESTED (10/10 passing)
 9.  28.0   StepAction  fetch-metadata           24     2         3     0      UNTESTED
10.  22.0   Task        simple-validation        18     2         2     0      UNTESTED
...

RISK ANALYSIS BY FACTOR:

Top complexity drivers:
  1. create-advisory: 6 external commands (kubectl, curl, git, jq, date, tr)
  2. push-oci-artifact: 2 retry loops (hang risk if unmocked)
  3. run-pipeline-check: 7 branches (many code paths)

Top risk patterns:
  - 6 resources use kubectl (cluster integration, complex mocking)
  - 4 resources use jq (JSON parsing, schema dependencies)
  - 3 resources have retry loops (timeout/hang risk)
  - 2 resources read secrets (mock complexity, security considerations)

TESTING PRIORITIES:

Priority 1: High-risk untested (scores 60+)
  - create-advisory (score 85) — Most complex, uses curl+jq+git
  - push-oci-artifact (score 72.5) — Retry loops, oras+leaktk+jq
  - run-pipeline-check (score 65) — Many branches, kubectl heavy

  Rationale: These have the most logic and integration points. Highest
  probability of bugs, highest value from testing.

Priority 2: Medium-risk untested (scores 30-60)
  - trigger-jenkins-job (score 58)
  - fetch-metadata (score 28)
  - simple-validation (score 22)

  Rationale: Moderate complexity. Test after high-risk resources.

Priority 3: Low-risk untested (scores < 30)
  - (5 simple resources)

  Rationale: Minimal logic, likely work correctly. Test last or skip.

Priority 4: Tested but incomplete
  - verify-signatures (score 45) — 5/8 tests passing
    Fix failing tests, may need additional coverage

RECOMMENDATIONS:

1. START WITH: create-advisory
   - Highest score (85)
   - Uses 6 different commands (comprehensive mocking needed)
   - 8 branches (many test cases)
   - 2 loops (hang risk)
   Expected effort: 15-20 minutes (complex)

2. BUILD REUSABLE PATTERNS:
   - kubectl mock (used in 6 resources)
   - jq mock (used in 4 resources)
   - curl HTTP mock (used in 4 resources)
   Invest time up front, reuse across resources.

3. BATCH SIMPLE RESOURCES:
   - Process 5 simple resources together at end
   - Low risk, minimal mocking, quick wins

4. FIX INCOMPLETE:
   - verify-signatures has 3 failing tests
   - Fix before moving to untested resources
   - Demonstrates agent can fix as well as generate

ESTIMATED TIME:
  - High-risk (3 resources):  ~45-60 minutes
  - Medium-risk (3 resources): ~20-30 minutes
  - Low-risk (5 resources):   ~15-20 minutes
  - Fix incomplete (1 resource): ~10 minutes
  Total: ~90-120 minutes for full catalog

BATCH STRATEGY:
  Batch 1: create-advisory (alone — too complex for batching)
  Batch 2: push-oci-artifact (alone — retry loops need focus)
  Batch 3: run-pipeline-check (alone — many branches)
  Batch 4: trigger-jenkins-job, fetch-metadata (pair — medium)
  Batch 5: All 5 simple resources (together — quick batch)
  Batch 6: Fix verify-signatures (cleanup)
```

## Risk Score Interpretation

Use these thresholds:

**Critical (80+):**
- Extremely complex
- Process individually with full fix loop
- Expect 15-20 minutes per resource
- High failure probability, worth the effort

**High (60-79):**
- Complex
- Process individually or in pairs
- Expect 10-15 minutes per resource
- Significant test value

**Medium (30-59):**
- Moderate complexity
- Can batch 2-3 together
- Expect 5-10 minutes per resource
- Standard test value

**Low (< 30):**
- Simple
- Batch 5+ together
- Expect 2-3 minutes per resource
- Marginal test value, test for completeness

## What This Enables

**Efficient resource allocation:** Focus effort where bugs are most likely.

**Justifiable priorities:** "Test X first because it has 15 branches and 6 commands" is data-driven.

**Batch planning:** Know which resources can be batched vs need individual attention.

**Time estimation:** Predict how long full catalog coverage will take.

**Pattern identification:** See which mocks will be reused most.

Use risk audit to work smarter, not harder.
