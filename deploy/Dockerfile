# syntax=docker/dockerfile:1.7
# Platform image: `oge` CLI + knowledge MCP server, with the F´ knowledge-graph snapshot baked in at build
# time. Build on a connected machine; the resulting image needs no network at run time (air-gap friendly):
#   docker build -f deploy/Dockerfile -t onprem-genai/oge:0.1.0 .
#   docker save onprem-genai/oge:0.1.0 | gzip > oge.tar.gz     # transfer, then `docker load`

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

FROM python:3.12-slim
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
