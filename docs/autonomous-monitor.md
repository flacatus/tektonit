# Autonomous Monitor - Continuous Catalog Watching

The autonomous monitor watches Tekton catalogs 24/7, automatically:
1. **Lints** resources for structural bugs (duplicate params, invalid references)
2. **Creates GitHub issues** when bugs are found
3. **Generates tests** for untested resources
4. **Opens Pull Requests** with test improvements

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│ Every POLL_INTERVAL (default: 1 hour)                      │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
   ┌─────────────────┐
   │ Clone/Pull Repo │
   └────────┬────────┘
            │
            ▼
   ┌──────────────────┐
   │ Load All YAMLs   │
   └────────┬─────────┘
            │
            ▼
   ┌────────────────────────────┐
   │ 1. LINT ALL RESOURCES      │  ← NEW!
   │    - Duplicate parameters  │
   │    - Invalid references    │
   │    - Dependency issues     │
   └────────┬───────────────────┘
            │
            ▼
   ┌────────────────────────────┐
   │ Create GitHub Issues       │  ← NEW!
   │ for Bugs Found             │
   └────────┬───────────────────┘
            │
            ▼
   ┌────────────────────────────┐
   │ 2. Find Untested Resources │
   └────────┬───────────────────┘
            │
            ▼
   ┌────────────────────────────┐
   │ 3. Generate Tests          │
   │    (BATS for bash,         │
   │     pytest for Python)     │
   └────────┬───────────────────┘
            │
            ▼
   ┌────────────────────────────┐
   │ 4. Validate & Fix          │
   │    (up to 10 attempts)     │
   └────────┬───────────────────┘
            │
            ▼
   ┌────────────────────────────┐
   │ 5. Open Pull Request       │
   └────────┬───────────────────┘
            │
            ▼
   ┌────────────────────────────┐
   │ Sleep POLL_INTERVAL        │
   │ (default: 3600s = 1 hour)  │
   └────────┬───────────────────┘
            │
            └──────► (repeat forever)
```

## Quick Start

### 1. Set Environment Variables

```bash
# Required
export GITHUB_TOKEN="ghp_xxx..."           # GitHub PAT with repo access
export GEMINI_API_KEY="xxx..."             # Or ANTHROPIC_API_KEY

# Optional (with defaults)
export GITHUB_REPO="owner/repo"             # Default: flacatus/tekton-integration-catalog
export REPO_BRANCH="main"                   # Default: main
export POLL_INTERVAL_SECONDS="3600"         # Default: 3600 (1 hour)
export WORK_DIR="/workspace/catalog"        # Default: /workspace/catalog
export LLM_PROVIDER="gemini"                # Default: gemini (or claude, openai)
export MAX_FIX_ATTEMPTS="10"                # Default: 10
export BATCH_SIZE="10"                      # Default: 10 resources per cycle
export STATE_DB_PATH="/tmp/tektonit.db"     # Default: /tmp/tektonit-state.db
```

### 2. Run the Monitor

```bash
# Locally
python -m tektonit.monitor

# With custom settings
GITHUB_REPO="myorg/my-catalog" \
POLL_INTERVAL_SECONDS="1800" \
python -m tektonit.monitor
```

### 3. Watch the Logs

```
2025-03-23 10:00:00 INFO tektonit monitor starting
2025-03-23 10:00:00 INFO   repo:       flacatus/tekton-integration-catalog
2025-03-23 10:00:00 INFO   branch:     main
2025-03-23 10:00:00 INFO   interval:   3600s
2025-03-23 10:00:00 INFO   provider:   gemini
2025-03-23 10:00:00 INFO   workdir:    /workspace/catalog
2025-03-23 10:00:00 INFO   batch_size: 10
2025-03-23 10:00:00 INFO   max_fix:    10
2025-03-23 10:00:00 INFO   state_db:   /tmp/tektonit-state.db
2025-03-23 10:00:05 INFO == Cycle start ==
2025-03-23 10:00:10 INFO Repo ready at /workspace/catalog
2025-03-23 10:00:15 INFO Step 1: Linting resources for structural bugs...
2025-03-23 10:02:30 WARNING   Bugs found in Pipeline/push-artifacts-to-cdn
2025-03-23 10:02:35 INFO   Created issue: https://github.com/owner/repo/issues/123
2025-03-23 10:02:40 INFO Linting complete: 1 bugs found, 1 issues created
2025-03-23 10:02:45 INFO Found 15 untested resources (of 45 testable, 120 total).
2025-03-23 10:02:50 INFO Collecting PR review feedback for learning...
2025-03-23 10:03:00 INFO Processing 10 actionable resources
2025-03-23 10:03:05 INFO [1/10] Processing Task/clone-repo
2025-03-23 10:05:20 INFO   Tests passed on attempt 1
2025-03-23 10:05:25 INFO   Created PR: https://github.com/owner/repo/pull/456
...
2025-03-23 10:45:00 INFO == Cycle done in 2700s: 120 total, 1 bugs→1 issues, 45 testable, 15 untested, 3 PRs, 5 skipped, 0 errors ==
2025-03-23 10:45:05 INFO Next cycle in 3600s
```

## GitHub Issues Created

When bugs are found, the monitor creates issues like:

```
🐛 Structural issues in Pipeline: push-artifacts-to-cdn

## Structural Validation Issues

**Resource:** `Pipeline/push-artifacts-to-cdn`
**File:** `pipelines/managed/push-artifacts-to-cdn/push-artifacts-to-cdn.yaml`

The autonomous agent detected structural issues in this Tekton resource:

❌ DUPLICATE PARAMETER in 'populate-release-notes' task
  File: pipelines/managed/push-artifacts-to-cdn/push-artifacts-to-cdn.yaml
  Parameter: jiraSecretName
  First definition: line 273
  Duplicate: line 287
  Fix: Remove lines 287-288 (duplicate definition)

✅ Other checks passed:
  - No invalid parameter references
  - No invalid task references
  - No dependency issues

---
**How to fix:**
1. Review the issues listed above
2. Make the suggested changes to the YAML file
3. Test that the resource still works
4. Commit and push

🤖 This issue was automatically created by tektonit
```

Labels: `bug`, `automated`, `linting`

## State Persistence

The monitor uses SQLite to remember:
- ✅ Resources already processed (won't duplicate work)
- ✅ Bugs already reported (won't create duplicate issues)
- ✅ Failure patterns learned (improves fix success rate)
- ✅ PR review feedback (learns from human reviewers)

This survives pod restarts in Kubernetes!

## Running in Kubernetes

### Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tektonit-monitor
  namespace: tektonit
spec:
  replicas: 1
  selector:
    matchLabels:
      app: tektonit-monitor
  template:
    metadata:
      labels:
        app: tektonit-monitor
    spec:
      serviceAccountName: tektonit
      containers:
      - name: monitor
        image: quay.io/flacatus/tektonit:latest
        command: ["python", "-m", "tektonit.monitor"]
        env:
        - name: GITHUB_REPO
          value: "flacatus/tekton-integration-catalog"
        - name: REPO_BRANCH
          value: "main"
        - name: POLL_INTERVAL_SECONDS
          value: "3600"  # 1 hour
        - name: GITHUB_TOKEN
          valueFrom:
            secretKeyRef:
              name: tektonit-secrets
              key: github-token
        - name: GEMINI_API_KEY
          valueFrom:
            secretKeyRef:
              name: tektonit-secrets
              key: gemini-api-key
        - name: STATE_DB_PATH
          value: "/data/tektonit-state.db"
        volumeMounts:
        - name: state
          mountPath: /data
        - name: workspace
          mountPath: /workspace
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
        ports:
        - name: metrics
          containerPort: 8080
          protocol: TCP
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /readyz
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
      volumes:
      - name: state
        persistentVolumeClaim:
          claimName: tektonit-state
      - name: workspace
        emptyDir: {}
```

### Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: tektonit-secrets
  namespace: tektonit
type: Opaque
stringData:
  github-token: "ghp_xxx..."
  gemini-api-key: "xxx..."
```

### PVC for State

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: tektonit-state
  namespace: tektonit
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
```

## Monitoring

### Prometheus Metrics

Available at `http://localhost:8080/metrics`:

- `tektonit_cycle_duration_seconds` - How long each cycle takes
- `tektonit_tests_generated_total{kind,result}` - Tests generated (success/fail)
- `tektonit_tests_fixed_total{kind,result}` - Tests fixed after failures
- `tektonit_prs_created_total` - PRs created
- `tektonit_errors_total{component,error_type}` - Errors encountered
- `tektonit_resources{category}` - Resource counts (total/testable/untested)

### Health Checks

- `GET /healthz` - Liveness probe (200 if running)
- `GET /readyz` - Readiness probe (200 if ready to process)
- `GET /metrics` - Prometheus metrics

## Configuration Guide

### Poll Interval

How often to check the catalog:

```bash
# Every 30 minutes
export POLL_INTERVAL_SECONDS="1800"

# Every 6 hours (for large catalogs)
export POLL_INTERVAL_SECONDS="21600"

# Every 5 minutes (for rapid development)
export POLL_INTERVAL_SECONDS="300"
```

### Batch Size

How many resources to process per cycle:

```bash
# Process 5 at a time (conservative)
export BATCH_SIZE="5"

# Process 20 at a time (aggressive)
export BATCH_SIZE="20"

# Process all (not recommended for large catalogs)
export BATCH_SIZE="9999"
```

### LLM Provider

```bash
# Gemini (default, cheapest)
export LLM_PROVIDER="gemini"
export GEMINI_API_KEY="xxx..."

# Claude (best quality)
export LLM_PROVIDER="claude"
export ANTHROPIC_API_KEY="xxx..."

# OpenAI
export LLM_PROVIDER="openai"
export OPENAI_API_KEY="xxx..."
```

## What Gets Created

### For Each Bug Found:
- ✅ GitHub Issue with exact line numbers
- ✅ Suggested fix
- ✅ Labels: `bug`, `automated`, `linting`
- ✅ Deduplicated (won't create duplicates)

### For Each Untested Resource:
- ✅ BATS tests (for bash scripts)
- ✅ pytest tests (for Python scripts)
- ✅ Pull Request with tests
- ✅ Autonomous fix loop (up to 10 attempts)
- ✅ All tests passing before PR creation

## FAQ

### Q: Will it create duplicate issues/PRs?

**No.** The state database tracks:
- Bugs already reported → won't create duplicate issues
- Resources already processed → won't create duplicate PRs

### Q: What if a test fails?

The agent will:
1. Diagnose the failure (mock mismatch? assertion? syntax?)
2. Learn from past similar failures
3. Try to fix (up to 10 attempts with progressive strategy)
4. If all fixes fail: skip and move to next resource

### Q: Can I run multiple monitors?

No. Only run one instance per repository to avoid conflicts.

### Q: How much does it cost?

Depends on LLM provider:
- **Gemini**: ~$0.10-0.50 per cycle (cheapest)
- **Claude**: ~$1-5 per cycle (best quality)
- **OpenAI**: ~$0.50-2 per cycle

### Q: Can it run locally?

Yes! Just set env vars and run:
```bash
python -m tektonit.monitor
```

### Q: How do I stop it?

Send `SIGTERM` or press `Ctrl+C`:
```bash
# Graceful shutdown
kill <pid>

# Force stop (press twice)
Ctrl+C Ctrl+C
```

## Example Real-World Usage

```bash
# Monitor Tekton catalog every 2 hours, process 5 resources at a time
export GITHUB_REPO="flacatus/tekton-integration-catalog"
export GITHUB_TOKEN="ghp_xxx..."
export GEMINI_API_KEY="xxx..."
export POLL_INTERVAL_SECONDS="7200"   # 2 hours
export BATCH_SIZE="5"
export MAX_FIX_ATTEMPTS="8"

python -m tektonit.monitor
```

Expected output:
```
INFO tektonit monitor starting
INFO == Cycle start ==
INFO Linting complete: 3 bugs found, 3 issues created
INFO Found 25 untested resources
INFO [1/5] Processing Task/git-clone
INFO   Tests passed on attempt 1
INFO   Created PR: #789
INFO [2/5] Processing Task/buildah
INFO   Tests passed on attempt 3
INFO   Created PR: #790
...
INFO == Cycle done in 1800s: 150 total, 3 bugs→3 issues, 75 testable, 25 untested, 5 PRs, 15 skipped, 0 errors ==
INFO Next cycle in 7200s
```

## Troubleshooting

### Issue: "LLM circuit breaker open"

**Cause:** Too many LLM errors in short time
**Fix:** Wait 60s or check LLM provider status

### Issue: "Permission denied" on git clone

**Cause:** Invalid GITHUB_TOKEN
**Fix:** Verify token has `repo` scope

### Issue: "No issues created despite bugs found"

**Cause:** Bugs already reported in previous cycle
**Fix:** This is expected behavior (deduplication)

### Issue: High memory usage

**Cause:** Large catalog + large batch size
**Fix:** Reduce `BATCH_SIZE` or add more memory

## Next Steps

1. ✅ Set up environment variables
2. ✅ Run monitor locally to test
3. ✅ Deploy to Kubernetes
4. ✅ Set up Prometheus monitoring
5. ✅ Watch GitHub for issues and PRs
6. ✅ Review and merge agent PRs
7. ✅ Agent learns from your feedback!
