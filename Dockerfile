FROM python:3.12-slim-bookworm

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      git \
      curl \
      jq \
      shellcheck && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install bats-core from source (Debian bats is outdated)
RUN git clone --depth 1 https://github.com/bats-core/bats-core.git /tmp/bats-core && \
    /tmp/bats-core/install.sh /usr/local && \
    rm -rf /tmp/bats-core

WORKDIR /app

COPY pyproject.toml .
COPY tektonit/ tektonit/
RUN pip install --no-cache-dir .

RUN mkdir -p /workspace /var/lib/tektonit && \
    useradd -m -s /bin/bash agent && \
    chown -R agent:agent /workspace /var/lib/tektonit /app

USER agent

ENV WORK_DIR=/workspace/catalog \
    STATE_DB_PATH=/var/lib/tektonit/state.db \
    POLL_INTERVAL_SECONDS=3600 \
    BATCH_SIZE=10 \
    MAX_FIX_ATTEMPTS=3 \
    LLM_PROVIDER=gemini \
    GITHUB_REPO=flacatus/tekton-integration-catalog \
    REPO_BRANCH=main \
    HEALTH_PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -sf http://localhost:8080/healthz || exit 1

CMD ["python", "-m", "tektonit.monitor"]
