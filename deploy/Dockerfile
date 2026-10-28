# syntax=docker/dockerfile:1.7
# Platform image: `oge` CLI + knowledge MCP server, with the F´ knowledge-graph snapshot baked in at build
# time. Build on a connected machine; the resulting image needs no network at run time (air-gap friendly):
#   docker build -f deploy/Dockerfile -t onprem-genai/oge:0.1.0 .
#   docker save onprem-genai/oge:0.1.0 | gzip > oge.tar.gz     # transfer, then `docker load`
#
# Console image (`--target console`): the engineering console, plus a C++ toolchain and an F´ checkout
# prepared for unit-test builds, so the test-generation agent can build, run and commit tests:
#   docker build -f deploy/Dockerfile --target console -t onprem-genai/console:0.1.0 .

FROM python:3.12-slim AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY src ./src
RUN uv venv /opt/venv \
 && uv pip install --python /opt/venv/bin/python --no-cache ".[knowledge]"
COPY scripts/fetch_fprime.sh ./scripts/
RUN scripts/fetch_fprime.sh /opt/fprime \
 && /opt/venv/bin/oge knowledge ingest /opt/fprime --out /data/fprime_graph.jsonl.gz \
      --audit-out /data/traceability_audit.json

# ------------------------------------------------------------------------------------------- console
FROM python:3.12-slim AS console-build
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY src ./src
RUN uv venv /opt/venv \
 && uv pip install --python /opt/venv/bin/python --no-cache ".[console]"

FROM python:3.12-slim AS console
LABEL org.opencontainers.image.title="onprem-genai-embedded console" \
      org.opencontainers.image.description="Engineering console with the test-generation agent and an F´ workspace" \
      org.opencontainers.image.licenses="Apache-2.0"
# C++ toolchain for F´ unit tests (gcc, gcov) and git for the review branches
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential git ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 oge \
 && mkdir -p /opt/fprime-ut /var/lib/oge \
 && chown oge:oge /opt/fprime-ut /var/lib/oge
COPY --from=console-build /opt/venv /opt/venv
COPY --from=build /data /data
COPY --chown=oge:oge scripts/fetch_fprime.sh scripts/setup_fprime_ut.sh /opt/scripts/
COPY docs/results/bench/run3-2026-10-28/agent-v2/qwen3-coder-30b-a3b__llamacpp.jsonl \
     docs/results/bench/run3-2026-10-28/agent-v2/devstral-small-2-24b__llamacpp.jsonl \
     docs/results/bench/run3-2026-10-28/agent-v2/ai-prereview.md /data/benchmark/
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1
USER oge
# F´ v4.4.1 with googletest, its build tools and the unit-test build cache (network needed at build only)
RUN /opt/scripts/setup_fprime_ut.sh /opt/fprime-ut/fprime
EXPOSE 8770
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=10 \
  CMD ["curl", "-fsS", "http://127.0.0.1:8770/api/status"]
ENTRYPOINT ["oge"]
CMD ["console", "serve", "--host", "0.0.0.0", "--port", "8770", \
     "--graph", "/data/fprime_graph.jsonl.gz", \
     "--fprime", "/opt/fprime-ut/fprime", \
     "--db", "/var/lib/oge/console.db", \
     "--no-benchmark-defaults", \
     "--import-results", "/data/benchmark/qwen3-coder-30b-a3b__llamacpp.jsonl", \
     "--import-results", "/data/benchmark/devstral-small-2-24b__llamacpp.jsonl", \
     "--replay", "/data/benchmark/qwen3-coder-30b-a3b__llamacpp.jsonl", \
     "--replay", "/data/benchmark/devstral-small-2-24b__llamacpp.jsonl", \
     "--prereview", "/data/benchmark/ai-prereview.md"]

# ------------------------------------------------------------------------------------------- platform (default target)
FROM python:3.12-slim AS platform
LABEL org.opencontainers.image.title="onprem-genai-embedded" \
      org.opencontainers.image.description="Knowledge MCP server and platform CLI" \
      org.opencontainers.image.licenses="Apache-2.0"
RUN useradd --create-home --uid 10001 oge
COPY --from=build /opt/venv /opt/venv
COPY --from=build /data /data
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1
USER oge
EXPOSE 8765
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=10 \
  CMD ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8765), 3)"]
ENTRYPOINT ["oge"]
CMD ["mcp", "serve", "--graph", "/data/fprime_graph.jsonl.gz", "--transport", "streamable-http", \
     "--host", "0.0.0.0", "--port", "8765"]
