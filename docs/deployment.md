# Deployment Guide

## Prerequisites

- A Kubernetes cluster
- `kubectl` configured with cluster access
- A Gemini API key (or Claude/OpenAI key)
- A GitHub token with `repo` and `pull_request` permissions

## Kubernetes deployment

### 1. Create the namespace

```bash
kubectl apply -f deploy/namespace.yaml
```

### 2. Configure secrets

Edit `deploy/secret.yaml` with your actual API keys:

```yaml
stringData:
  GITHUB_TOKEN: "ghp_your_actual_token"
  GEMINI_API_KEY: "your_actual_gemini_key"
```

Then apply:

```bash
kubectl apply -f deploy/secret.yaml
```

### 3. Deploy the agent

Review `deploy/deployment.yaml` and adjust environment variables as needed:

```yaml
env:
  - name: GITHUB_REPO
    value: "your-org/your-tekton-catalog"  # Target repository
  - name: REPO_BRANCH
    value: "main"
  - name: POLL_INTERVAL_SECONDS
    value: "3600"           # How often to check (1 hour)
  - name: BATCH_SIZE
    value: "10"             # Resources per cycle
  - name: MAX_FIX_ATTEMPTS
    value: "3"              # Fix attempts per resource
  - name: LLM_PROVIDER
    value: "gemini"         # gemini, claude, or openai
```

Then apply:

```bash
kubectl apply -f deploy/deployment.yaml
```

### 4. Verify deployment

```bash
# Check pod status
kubectl get pods -n tektonit

# View logs
kubectl logs -n tektonit -l app.kubernetes.io/name=tektonit -f

# Check health
kubectl port-forward -n tektonit svc/tektonit 8080:8080
curl http://localhost:8080/healthz
curl http://localhost:8080/readyz
curl http://localhost:8080/metrics
```

## Container image

Build the container image:

```bash
docker build -t tektonit:latest .
docker tag tektonit:latest quay.io/your-org/tektonit:latest
docker push quay.io/your-org/tektonit:latest
```

Update `deploy/deployment.yaml` with your image:

```yaml
image: quay.io/your-org/tektonit:latest
```

## Environment variables reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes (if using Gemini) | - | Gemini API key |
| `ANTHROPIC_API_KEY` | Yes (if using Claude) | - | Anthropic API key |
| `OPENAI_API_KEY` | Yes (if using OpenAI) | - | OpenAI API key |
| `GITHUB_TOKEN` | Yes | - | GitHub token with repo + PR permissions |
| `GITHUB_REPO` | Yes | `flacatus/tekton-integration-catalog` | Target GitHub repository (owner/repo) |
| `REPO_BRANCH` | No | `main` | Branch to monitor for changes |
| `POLL_INTERVAL_SECONDS` | No | `3600` | Seconds between monitoring cycles |
| `BATCH_SIZE` | No | `10` | Max resources to process per cycle |
| `MAX_FIX_ATTEMPTS` | No | `3` | Max fix attempts per resource |
| `LLM_PROVIDER` | No | `gemini` | LLM provider: gemini, claude, openai |
| `LLM_MODEL` | No | provider default | Override the LLM model name |
| `WORK_DIR` | No | `/workspace/catalog` | Working directory for cloned repos |
| `STATE_DB_PATH` | No | `/var/lib/tektonit/state.db` | SQLite database file path |
| `HEALTH_PORT` | No | `8080` | Port for health/metrics endpoints |

## Persistence

The agent uses SQLite for state persistence. In Kubernetes, this is backed by a PersistentVolumeClaim:

```yaml
volumes:
  - name: state
    persistentVolumeClaim:
      claimName: tektonit-state  # 100Mi PVC
```

The state database stores:
- Which resources have already been processed (avoid reprocessing)
- Episodic memory (failure patterns and fixes that worked)
- PR feedback (lessons from code reviews)

## Monitoring

### Prometheus metrics

The agent exposes metrics at `/metrics`:

| Metric | Type | Description |
|---|---|---|
| `tektonit_tests_generated_total` | Counter | Tests generated (by kind, language) |
| `tektonit_tests_fixed_total` | Counter | Tests that required fixing |
| `tektonit_prs_created_total` | Counter | PRs opened |
| `tektonit_cycle_duration_seconds` | Histogram | Time per monitoring cycle |
| `tektonit_errors_total` | Counter | Errors by type |
| `tektonit_resources_total` | Gauge | Total resources found |

### Health checks

| Endpoint | Purpose | Kubernetes probe |
|---|---|---|
| `/healthz` | Liveness — is the process alive? | `livenessProbe` |
| `/readyz` | Readiness — is it ready to process? | `readinessProbe` |

### Logs

The agent uses structured JSON logging. Example log line:

```json
{
  "timestamp": "2024-03-15T10:30:00Z",
  "level": "INFO",
  "message": "Generated tests for StepAction/push-oci-artifact",
  "resource": "push-oci-artifact",
  "kind": "StepAction",
  "fix_attempts": 2,
  "passed": true
}
```

## Resource requirements

Recommended resource limits for the Kubernetes pod:

```yaml
resources:
  requests:
    cpu: 100m
    memory: 256Mi
  limits:
    cpu: "1"
    memory: 1Gi
```

The agent is CPU-light (mostly waiting for LLM API responses) but needs memory for parsing large YAML catalogs and running BATS tests.
