---
name: risk-audit
description: Audit a Tekton catalog and prioritize resources by testing risk
user_invocable: true
---

# Skill: Risk Audit

Scan a Tekton catalog and rank resources by testing risk/value. Helps decide what to test first.

## Usage
```
/risk-audit <path-or-git-url>
```

## Protocol

### Step 1: Scan the catalog
```bash
cd /Users/flacatus/WORKSPACE/devprod/test_agent && pip install -e ".[dev]"
tektonit scan <path>
```

### Step 2: Score each resource

For each resource with testable scripts, compute a risk score:

| Factor | Points | Rationale |
|---|---|---|
| Script lines / 10 | up to 30 | More code = more risk |
| Branches (if/elif/else/case) | × 2 each | More logic paths = more can go wrong |
| External commands | × 3 each | Integration points = failure points |
| Loops (while/until/for) | × 5 each | Infinite loop risk, retry complexity |
| Traps (trap handlers) | × 3 each | Error handling complexity |
| set -e / set -euo pipefail | × 2 | Strict mode = more failure paths |
| JSON processing (jq) | × 3 | Parsing complexity, schema dependency |
| Network calls (curl/wget) | × 4 | External dependency, error handling |
| File I/O (results, workspace) | × 2 | State management complexity |

### Step 3: Check existing coverage

For each resource, check if `sanity-check/` exists:
- Has `.bats` file? → BATS coverage exists
- Has `.py` file? → pytest coverage exists
- Empty or no dir? → UNTESTED

### Step 4: Report

```
RISK AUDIT REPORT
Catalog: <path>
Total resources: 24
Testable: 18
Already tested: 7
Untested: 11

PRIORITY ORDER (highest risk first):

 #  Score  Kind        Name                    Languages  Status
 1. 85.0   Task        create-advisory         bash       UNTESTED
 2. 72.5   StepAction  push-oci-artifact       bash       UNTESTED
 3. 65.0   Task        run-pipeline-check      bash       UNTESTED
 4. 58.0   StepAction  trigger-jenkins-job     python     UNTESTED
 5. 45.0   Task        verify-signatures       bash       TESTED (5/8 passing)
 ...

TOP RISK FACTORS:
- 6 resources use kubectl (cluster integration risk)
- 4 resources use jq with complex queries (parsing risk)
- 3 resources have retry loops (timeout/hang risk)
- 2 resources read secrets (mock complexity)

RECOMMENDATION:
Start with #1 (create-advisory) — highest complexity, uses curl+jq+git,
has 15 branches, 2 retry loops. Most value from testing this first.
```

### Step 5: Suggest batch strategy

Based on batch size and resource complexity:
- Simple resources (score < 30): batch 5+ at a time
- Medium resources (score 30-60): batch 3 at a time
- Complex resources (score > 60): process 1 at a time with full fix loop
