# Design decisions

Each decision: context → choice → why → what would change it. Questions an interviewer is likely to ask are at
the end.

## D1 · Target code base: NASA F´ rather than a synthetic project
- **Choice**: F´ v4.4.1 (JPL flight software, C++, Apache-2.0), fetched at a pinned commit.
- **Why**: real aerospace code with real requirements (design-document tables) and *explicit* requirement → test
  tags (`REQUIREMENT("ID")`), i.e. measurable ground truth for traceability. Unit tests build and run in under a
  minute per component, which the M2 agent needs. Alternatives: NASA cFS apps (C, but requirements are almost
  never referenced from tests) and a synthetic library (full control, no credibility).
- **Would change if**: the target organisation's own code base becomes available.

## D2 · Two inference engines: llama.cpp and vLLM
- **Choice**: llama.cpp for CPU / single-GPU / quantized GGUF, vLLM for multi-GPU team serving.
- **Why**: llama.cpp runs everywhere (laptop, Turing GPUs, air-gapped hosts) with mature 4-bit quantization;
  vLLM brings continuous batching, paged KV cache, prefix caching and tensor parallelism. Comparing them on the
  same hardware is itself a sizing input. SGLang was not retained for the test hardware: its kernel wheel
  on Kaggle targets newer GPUs (a public T4 benchmark reports an import failure on SM 7.5), and vLLM covers
  the same role.
- **Would change if**: production hardware is Hopper/Blackwell-only (then vLLM or SGLang everywhere, FP8).

## D3 · Measure first: a probe notebook before any model choice
- **Why**: 2026 hybrid-attention models (Qwen3.6/3.8) needed source patches to run in vLLM on older GPUs; FP8 and
  BF16 are unavailable on T4. Model choices are made from the probe's compatibility matrix, not assumed.

## D4 · Sizing calculator with provenance and refusal of unknowns
- **Choice**: every GPU / quantization / architecture value carries its source; missing values raise
  `IncompleteSpecError`; specs are completed from official `config.json` / GGUF metadata.
- **Why**: sizing is a procurement decision. A wrong KV-cache size is a wrong budget. Hybrid models (linear
  attention) and MoE (expert traffic grows with batch) break naive "parameters × 2 bytes" estimates.
- **Validation**: efficiencies fitted on measured runs, reported leave-one-model-out.

## D5 · Graph store: Neo4j for persistence, in-process ranking for search
- **Choice**: `KnowledgeStore` interface; `InMemoryStore` (snapshot) and `Neo4jStore` (Cypher) pass the same
  contract tests; hybrid ranking runs in-process over the snapshot in both cases.
- **Why**: Neo4j gives a persistent, queryable graph (Cypher, Browser) that engineers and tools can use directly;
  keeping ranking in-process guarantees identical, reproducible search results whichever backend serves the
  graph, and keeps the laptop demo dependency-free.
- **Would change if**: the graph outgrows memory (then Neo4j full-text + vector indexes).

## D6 · Hybrid retrieval: graph tier first, text within tier
- **Why**: measured — graph alone MAP 0.249, BM25 alone 0.488, graph-constrained BM25 0.569. The graph encodes
  where a requirement is allocated; text decides which test. **Known failure mode**: tests that verify another
  module's requirement are pushed down (8 % of requirements); they are exactly the cases the audit flags.

## D7 · Embeddings: Qwen3-Embedding-0.6B
- **Why**: Apache-2.0 (deployable commercially and on a defence site), strong code-retrieval scores at 0.6 B,
  32 k context, GGUF available so the same model serves from llama.cpp on CPU. A code-specialised alternative
  scored higher on benchmarks but its license is not clearly permissive.

## D8 · MCP SDK v2 (`MCPServer`), streamable HTTP
- **Why**: current SDK major version; streamable HTTP lets one shared server serve every IDE and agent, stdio
  remains available for local use. Tools return structured content (JSON) rather than prose.

## D9 · Air gap as a tested property
- **Choice**: Compose overlay on an `internal` network + smoke test with an egress probe, run in CI.
- **Why**: "works offline" is easy to claim and easy to break (a model server fetching a tokenizer, a library
  phoning home). Making it a failing test keeps it true.

## D10 · Agent framework (M2): LangGraph
- **Why**: explicit state machine fits a deterministic engineering loop (retrieve → write test → build → fix →
  commit → CI); checkpointing and human-in-the-loop interrupts; MCP adapters; widely used.

## D11 · Kaggle as GPU lab
- **Why**: no local GPU; Kaggle's 2× T4 (32 GB) runs 4-bit 24–35 B models. Notebooks are batch jobs that write
  result files; everything else (graph, MCP, sizing, deploy) runs on a laptop CPU.

---

## Questions to expect (and where the answers are)

| Question | Answer |
|---|---|
| How many GPUs for 100 engineers? | `oge sizing plan …` — explicit workload assumptions, calibrated efficiencies; see D4 and `docs/results`. |
| Why not just use an API (Copilot, Claude)? | Data cannot leave the site; D9, security defaults in ARCHITECTURE §6. |
| How do you know the RAG works? | Traceability benchmark with ground truth, confidence intervals, ablation (D6). |
| What does "288 gaps" mean exactly? | Requirements specified as verified by test with no explicit test tag — candidates for review, not proof of missing tests. |
| What happens when the model is wrong? | Suggestions are ranked with evidence (file:line, scores); M2 agent output must compile and pass, then goes through CI and review. |
| Why these models? | Probe compatibility matrix + license + measured speed/quality on T4 (D3). DeepSeek-V4 is sized but does not fit the test hardware. |
| How would you scale it? | Profiles `gpu` → `vllm`; replicas behind a gateway; Neo4j for the graph; per-team MCP servers; see sizing report. |
