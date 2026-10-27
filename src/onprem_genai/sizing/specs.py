"""Model and hardware specifications for the sizing calculator.

Specs are loaded from versioned YAML files whose every value carries a source. Unknown values stay ``None``;
calculations that need them raise :class:`IncompleteSpecError` instead of silently guessing.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

DATA_PACKAGE = "onprem_genai.sizing.data"


class IncompleteSpecError(ValueError):
    """Raised when a calculation needs a spec field that has not been verified yet."""


class Artifact(BaseModel):
    """A concrete, measured weight artifact (e.g. a GGUF file or a safetensors checkpoint)."""

    format: str
    bytes: float
    source: str


class ModelSpec(BaseModel):
    key: str
    display_name: str
    family: str | None = None
    hf_repo: str | None = None
    license: str | None = None
    params_total: float | None = None
    params_active: float | None = None
    n_layers: int | None = None
    hidden_size: int | None = None
    vocab_size: int | None = None
    num_attention_heads: int | None = None
    # Standard (softmax) attention layers that keep a per-token KV cache
    full_attn_layers: int | None = None
    kv_heads: int | None = None
    head_dim: int | None = None
    # Multi-head latent attention (DeepSeek-V2/V3 style): cached elements per token per layer
    mla_kv_dim: int | None = None
    # Linear-attention (Gated DeltaNet) layers: fixed-size recurrent state per sequence
    linear_attn_layers: int = 0
    linear_k_heads: int = 0
    linear_v_heads: int = 0
    linear_k_dim: int = 0
    linear_v_dim: int = 0
    linear_conv_kernel: int = 0
    linear_state_bytes: int = 4
    # Mixture of experts
    num_experts: int | None = None
    experts_per_token: int | None = None
    moe_intermediate_size: int | None = None
    moe_layers: int | None = None
    max_context: int | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    sources: dict[str, str] = Field(default_factory=dict)

    # ------------------------------------------------------------------ derived quantities
    def require(self, *fields: str) -> None:
        missing = [f for f in fields if getattr(self, f) is None]
        if missing:
            raise IncompleteSpecError(
                f"{self.key}: missing verified value(s) {missing}. Import the official config.json with "
                "`oge sizing import-config` before using this model."
            )

    @property
    def is_moe(self) -> bool:
        return bool(self.num_experts and self.experts_per_token)

    @property
    def expert_params(self) -> float | None:
        """Parameters stored in routed experts (gate, up, down projections), if derivable."""
        if not (self.is_moe and self.moe_intermediate_size and self.hidden_size):
            return None
        layers = self.moe_layers if self.moe_layers is not None else self.n_layers
        if layers is None or self.num_experts is None:
            return None
        return float(layers * self.num_experts * 3 * self.hidden_size * self.moe_intermediate_size)


class GpuSpec(BaseModel):
    key: str
    name: str
    arch: str
    compute_capability: str
    memory_gb: float
    bandwidth_gbs: float
    fp16_dense_tflops: float
    tdp_w: float
    supports_bf16: bool
    supports_fp8: bool
    source: str


class WeightFormat(BaseModel):
    key: str
    bits_per_weight: float
    source: str


class KvFormat(BaseModel):
    key: str
    bytes_per_element: float
    source: str


# ---------------------------------------------------------------------------------------------- loading
def _read_yaml(name: str) -> dict[str, Any]:
    text = resources.files(DATA_PACKAGE).joinpath(name).read_text(encoding="utf-8")
    return yaml.safe_load(text)


def load_models(path: Path | None = None) -> dict[str, ModelSpec]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path else _read_yaml("models.yaml")
    return {k: ModelSpec(key=k, **v) for k, v in raw["models"].items()}


def load_gpus() -> dict[str, GpuSpec]:
    raw = _read_yaml("gpus.yaml")
    return {k: GpuSpec(key=k, **v) for k, v in raw["gpus"].items()}


def load_formats() -> tuple[dict[str, WeightFormat], dict[str, KvFormat]]:
    raw = _read_yaml("quantization.yaml")
    weights = {k: WeightFormat(key=k, **v) for k, v in raw["weight_formats"].items()}
    kv = {k: KvFormat(key=k, **v) for k, v in raw["kv_cache_formats"].items()}
    return weights, kv


# ---------------------------------------------------------------------------------------------- importers
def _text_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Multimodal checkpoints nest the language model config under ``text_config``."""
    inner = cfg.get("text_config")
    return {**cfg, **inner} if isinstance(inner, dict) else cfg


def spec_from_hf_config(
    key: str,
    config: dict[str, Any],
    *,
    hf_repo: str | None = None,
    display_name: str | None = None,
    params_total: float | None = None,
    params_active: float | None = None,
    source: str = "config.json",
) -> ModelSpec:
    """Build a :class:`ModelSpec` from a Hugging Face ``config.json`` (dense, MoE, hybrid or MLA models)."""
    c = _text_config(config)
    n_layers = c.get("num_hidden_layers")
    heads = c.get("num_attention_heads")
    hidden = c.get("hidden_size")
    kv_heads = c.get("num_key_value_heads", heads)
    head_dim = c.get("head_dim") or (hidden // heads if hidden and heads else None)

    layer_types: list[str] | None = c.get("layer_types")
    linear_layers = 0
    if layer_types:
        linear_layers = sum(1 for t in layer_types if "linear" in t)
    elif c.get("full_attention_interval") and n_layers:
        interval = int(c["full_attention_interval"])
        linear_layers = n_layers - n_layers // interval
    full_layers = (n_layers - linear_layers) if n_layers is not None else None

    mla_dim = None
    if c.get("kv_lora_rank") is not None:
        mla_dim = int(c["kv_lora_rank"]) + int(c.get("qk_rope_head_dim") or 0)

    num_experts = c.get("num_experts") or c.get("num_local_experts") or c.get("n_routed_experts")
    moe_layers = None
    if num_experts and n_layers is not None:
        first_dense = int(c.get("first_k_dense_replace") or 0)
        moe_layers = n_layers - first_dense

    ssm_dtype = str(c.get("mamba_ssm_dtype", "float32"))
    return ModelSpec(
        key=key,
        display_name=display_name or key,
        hf_repo=hf_repo,
        params_total=params_total,
        params_active=params_active if params_active is not None else (None if num_experts else params_total),
        n_layers=n_layers,
        hidden_size=hidden,
        vocab_size=c.get("vocab_size"),
        num_attention_heads=heads,
        full_attn_layers=full_layers,
        kv_heads=kv_heads if mla_dim is None else None,
        head_dim=head_dim if mla_dim is None else None,
        mla_kv_dim=mla_dim,
        linear_attn_layers=linear_layers,
        linear_k_heads=int(c.get("linear_num_key_heads") or 0),
        linear_v_heads=int(c.get("linear_num_value_heads") or 0),
        linear_k_dim=int(c.get("linear_key_head_dim") or 0),
        linear_v_dim=int(c.get("linear_value_head_dim") or 0),
        linear_conv_kernel=int(c.get("linear_conv_kernel_dim") or 0),
        linear_state_bytes=2 if ssm_dtype in ("float16", "bfloat16") else 4,
        num_experts=num_experts,
        experts_per_token=c.get("num_experts_per_tok"),
        moe_intermediate_size=c.get("moe_intermediate_size"),
        moe_layers=moe_layers,
        max_context=c.get("max_position_embeddings"),
        sources={"architecture": source},
    )


def params_from_safetensors_index(index: dict[str, Any], dtype_bytes: float = 2.0) -> float | None:
    """Parameter count from ``model.safetensors.index.json`` (``metadata.total_size`` is in bytes)."""
    total = (index.get("metadata") or {}).get("total_size")
    return float(total) / dtype_bytes if total else None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
