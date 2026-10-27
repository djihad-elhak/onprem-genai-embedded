#!/usr/bin/env bash
# Download the GGUF models used by deploy/compose.yaml into deploy/models (run on a connected machine,
# then copy deploy/models to the air-gapped host).
#
#   scripts/download_models.sh            # laptop defaults: Qwen3.5-4B (chat/code) + Qwen3-Embedding-0.6B
#   LLM_REPO=unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF LLM_QUANT=Q4_K_M scripts/download_models.sh   # GPU host
set -euo pipefail

LLM_REPO="${LLM_REPO:-unsloth/Qwen3.5-4B-GGUF}"
LLM_QUANT="${LLM_QUANT:-Q4_K_M}"
EMBED_REPO="${EMBED_REPO:-Qwen/Qwen3-Embedding-0.6B-GGUF}"
EMBED_QUANT="${EMBED_QUANT:-Q8_0}"
DEST="${DEST:-deploy/models}"

OGE="${OGE:-oge}"
command -v "${OGE}" >/dev/null || OGE="uv run oge"

${OGE} bench pull-gguf "${LLM_REPO}" "${LLM_QUANT}" --out "${DEST}/llm.gguf"
${OGE} bench pull-gguf "${EMBED_REPO}" "${EMBED_QUANT}" --out "${DEST}/embed.gguf"
cat > "${DEST}/MODELS.txt" <<EOF
llm.gguf   ${LLM_REPO}:${LLM_QUANT}
embed.gguf ${EMBED_REPO}:${EMBED_QUANT}
downloaded $(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
( cd "${DEST}" && sha256sum llm.gguf embed.gguf > SHA256SUMS )
echo "models ready in ${DEST} (checksums in ${DEST}/SHA256SUMS)"
