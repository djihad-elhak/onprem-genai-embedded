---
sources:
  - src/onprem_genai/sizing/
  - src/onprem_genai/bench/
  - src/onprem_genai/knowledge/
  - src/onprem_genai/mcp_server/
  - src/onprem_genai/platform/
  - src/onprem_genai/evalsuite/
  - src/onprem_genai/agent/
  - deploy/compose.ci.yaml
  - deploy/jenkins/
  - deploy/
  - kaggle/
---

# Architecture

## 1. Context

Engineering teams building embedded flight / radio software want LLM assistance (code, refactoring,
documentation, tests) **without any data leaving the site**. The platform therefore runs open-weight models
locally, connects them to the team's own artefacts (code, tests, requirements, design documents, CI) through
the Model Context Protocol, and is sized from measurements rather than vendor claims.

## 2. Components

| Package | Responsibility | Key files |
|---|---|---|
| `sizing` | Model / GPU / quantization specs with provenance; memory model; roofline throughput; calibration and leave-one-model-out validation; team capacity planner | `specs.py`, `memory.py`, `performance.py`, `calibration.py`, `planner.py`, `data/*.yaml` |
| `bench` | Engine lifecycle (build llama.cpp, isolated vLLM, process groups, health, GPU sampling); closed-loop load generator; traffic profiles built from real code | `engines.py`, `loadgen.py`, `profiles.py` |
| `knowledge` | F´ ingestion (tree-sitter C++, requirement tables, test tags, design docs); typed graph + snapshots; BM25 / dense / fusion retrieval; traceability benchmark and audit; in-memory and Neo4j stores | `fprime/`, `model.py`, `retrieval.py`, `traceability.py`, `store.py`, `neo4j_store.py` |
| `mcp_server` | MCP server (SDK v2 `MCPServer`) over any `KnowledgeStore` | `server.py` |
| `evalsuite` | 27 purpose-written embedded C tasks (not taken from public benchmarks) (generate, unit-test generation, refactor, document) scored by execution: strict compile, hidden tests, sanitizers, gcov, mutation testing, complexity, Doxygen; OpenAI-compatible runner with pass@k and CIs ([EVALSUITE.md](EVALSUITE.md)) | `tasks/`, `scoring.py`, `validate.py`, `runner.py` |
| `agent` | LangGraph test-generation agent: MCP retrieval, policy-checked patching of F´ unit tests, build / run / coverage / mutants, git review branch, Jenkins CI over MCP ([AGENT.md](AGENT.md)) | `graph.py`, `patch.py`, `context.py`, `fprime.py`, `mutation.py`, `ci.py`, `runner.py` |
| `platform` | Deployment verification: LLM, embeddings, MCP over HTTP, egress probe | `smoke.py` |
| `deploy/` | Container image, Compose profiles, air-gap overlay, Jenkins add-on (`compose.ci.yaml`), client configs | `Dockerfile`, `compose.yaml`, `compose.offline.yaml`, `clients/` |
| `kaggle/` | GPU batch notebooks (2× T4) producing every hardware measurement | `00_probe_t4x2`, `01_m1_benchmark` |

## 3. Knowledge graph

```mermaid
erDiagram
  Module ||--o{ File : CONTAINS
  File ||--o{ Function : DEFINES
  File ||--o{ TestCase : DEFINES
  File ||--o{ Class : DEFINES
  Function }o--o{ Function : CALLS
  TestCase }o--o{ Function : CALLS
  TestCase }o--|| Module : TESTS
  TestCase }o--o{ Requirement : VERIFIES
  Requirement }o--|| Module : ALLOCATED_TO
  DocChunk }o--|| Module : DESCRIBES
```

- **Ids** are derived from source locations (`fn:<file>#<qualified>@<line>`, `req:<ID>`), so ingesting the
  same commit twice yields byte-identical snapshots (`.jsonl.gz`, sorted).
- **Requirements** come from Markdown tables detected by *content* (first column holds requirement IDs) since
  header names vary across F´ design documents.
- **VERIFIES** edges come only from explicit `REQUIREMENT("ID")` tags: the ground truth for evaluation and
  the evidence for audits. Tags pointing to undefined IDs or to another module's requirements are reported.
- **CALLS** are resolved by name: same-module targets first, otherwise a match unique enough globally (≤ 3).
  F´ autocoder conventions are encoded: a test calling `sendCmd_X` exercises `X_cmdHandler`, `invoke_to_p`
  exercises `p_handler`.
- **Neo4j** stores every node with an `:Entity` label (unique `id`) plus its type label; loading is batched
  `UNWIND … MERGE` and idempotent.

## 4. Retrieval and traceability

1. **Lexical**: Okapi BM25 over identifier-aware tokens (`runNominalDispatch` → run, nominal, dispatch; light
   stemming; code stop-words).
2. **Dense**: any OpenAI-compatible `/v1/embeddings` endpoint (the platform's own embedding server) or a local
   sentence-transformers model; queries carry a task instruction (Qwen3-Embedding convention); disk cache.
3. **Graph prior**: tests of the requirement's module first, then tests calling into that module.
4. **Hybrid**: rank by graph tier, then by the (fused) text score within each tier; reciprocal-rank fusion
   combines lexical and dense scores.
5. **LLM rerank** (optional): the platform's LLM scores the top-k (requirement, test) pairs 0–10.

Evaluation masks tags and IDs, ranks all test cases per requirement, reports MAP, MRR, Recall@k and nDCG@10
with bootstrap confidence intervals, and breaks score ties randomly (averaged) so no method benefits from
arbitrary ordering.

## 5. Sizing model

- **Memory** = weights (measured artifact size, else parameters × bits-per-weight) + KV cache
  (`full-attention layers × 2 × KV heads × head dim × bytes × tokens`, or MLA latent size) + linear-attention
  state per sequence (`v_heads × k_dim × v_dim` SSM state + convolution state) + calibrated runtime overhead.
- **Decode** is bandwidth bound: per step, weights touched (MoE: dense part + experts × `1 − (1 − k/E)^B`) +
  per-sequence KV and state traffic, divided by effective bandwidth. **Prefill** is compute bound.
  Tensor parallelism adds bandwidth; llama.cpp layer split does not (GPUs work in sequence).
- Two efficiency factors map datasheet peaks to engine reality; they are fitted on the Kaggle measurements and
  validated leave-one-model-out.
- **Capacity planning** uses Little's law on an explicit, editable workload model (requests per engineer per
  hour, prompt/output sizes, prefix-cache hit rate, per-user speed SLO).

## 6. Deployment

| Profile | Generation engine | Use |
|---|---|---|
| `cpu` | llama.cpp (CPU) | laptop, demo, CI |
| `gpu` | llama.cpp CUDA | single NVIDIA server |
| `vllm` | vLLM (tensor parallel, prefix caching) | multi-GPU team server |
| `neo4j` | + Neo4j and one-shot graph loader | persistent graph, Cypher exploration |

Security defaults: API key required by every model server (`--api-key`), host ports bound to `127.0.0.1`,
non-root platform image, graph snapshot baked at build time (no network at run time), optional DNS-rebinding
protection on the MCP endpoint (`--allowed-host`). The **offline overlay** moves every service onto an internal
Docker network and runs `oge platform smoke --expect-offline`, which fails if the LLM, embeddings or MCP
checks fail **or if any outbound connection succeeds** — this runs in CI on every push.
