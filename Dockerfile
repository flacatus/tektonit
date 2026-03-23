FROM python:3.12-slim-bookworm

# Build-time prompt generation from .claude/ agents and skills
# This ensures the container ALWAYS has the latest agent instructions
# from the source of truth (.claude/), preventing drift between
# Claude Code (.claude/) and containerized agent (tektonit/prompts.py)

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

# Copy build dependencies first (for prompt generation from .claude/)
COPY .claude/ .claude/
COPY scripts/build_prompts_from_agents.py scripts/

# Create tektonit package structure
RUN mkdir -p tektonit

# Generate prompts.py from .claude/ agents and skills (single source of truth)
RUN python scripts/build_prompts_from_agents.py && \
    python -m py_compile tektonit/prompts.py && \
    echo "✓ Generated and validated prompts.py from .claude/ source"

# Copy the rest of the package
COPY pyproject.toml .
COPY tektonit/ tektonit/

# Install package
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
