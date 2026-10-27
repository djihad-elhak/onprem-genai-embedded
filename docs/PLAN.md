# Project plan — On-premise GenAI platform for embedded software engineering

> Status: **draft for approval** · 2026-10-27 · Items marked ⏳ wait for your confirmation.

## 1. Goal

A reproducible, air-gap-ready reference implementation of an **on-premise GenAI platform for embedded /
aerospace software teams**, with measured results at every layer:

1. **Serving & sizing**: open-weight code models served locally, benchmarked, plus a sizing calculator
   validated against those measurements.
2. **Model evaluation**: open-weight models compared on embedded-style tasks (generation, unit tests, refactoring).
3. **Hybrid knowledge layer**: a knowledge graph of code + requirements + tests + documentation, with vector
   search, exposed to assistants through **MCP**. Includes a quantified requirement↔test **traceability** experiment.
4. **Agent + CI**: an agent that closes traceability gaps by writing requirement-based unit tests. It builds
   and runs them, and integrates with Git and **Jenkins** through MCP.
5. **Study & strategy**: productivity proxies, a pilot-measurement protocol and a scale-up strategy
   (bilingual EN/FR).

It is designed to match one target posting mission-for-mission, while every component remains a generic
GenAI-engineering skill (serving, eval, RAG, KG, MCP, agents, CI) reusable for similar roles.

| Posting mission | Covered by |
|---|---|
| Size GenAI infrastructure (CPU/GPU/RAM/storage) | WP1 sizing calculator + validation + team-size report |
| Deploy a local LLM platform | WP1 Docker Compose deployment (CPU and GPU profiles, offline mode) |
| Evaluate code models (Qwen, DeepSeek, Devstral) | WP0 probe + WP3 evaluation; DeepSeek-V4 covered in sizing (does not fit the test hardware) |
| Assistants for code / refactoring / docs / tests | WP3 task suite + Continue/Aider configs pointing at the platform |
| Agents interacting with engineering tools & repos | WP4 LangGraph agent ⏳ with Git + Jenkins MCP |
| RAG + MCP to docs, Git repos, CI | WP2 knowledge MCP server + official Jenkins MCP plugin |
| Measure performance & productivity, scale-up strategy | WP1/WP3/WP4 metrics + WP5 report |

## 2. Constraints (verified)

| Constraint | Consequence |
|---|---|
| GPU = Kaggle 2× Tesla T4 (SM 7.5, 2×15 GiB, FP16 only, no BF16/FP8/FlashAttention-2), 12 h sessions, weekly quota | GPU work runs as **batch notebooks** that write result files; 4-bit quantization (GGUF / AWQ / GPTQ) |
| Some 2026 architectures (hybrid linear-attention Qwen3.6/3.8) needed patches on older GPUs in vLLM | WP0 probe measures what really runs before any model is chosen |
| Dev machine: Windows, 16 GB RAM, i7-13th gen, Docker, no GPU | Laptop runs graph DB, MCP servers, Jenkins and a small CPU model; nothing GPU-bound |
| Defense-style context | No external APIs at runtime; offline mode is verified and documented; no employer branding in the repo |

## 3. Target codebase ⏳

**Recommended: NASA F´ (F Prime)**, JPL flight-software framework (flew on the Ingenuity Mars helicopter),
Apache-2.0, C++. Verified on the current repository:

- requirements live in component SDDs (`docs/sdd.md`) as tables `ID | Description | Verification method`;
- unit tests carry explicit tags `REQUIREMENT("CD-001")`: **163 tagged IDs, 152 matching documented
  requirements**, i.e. real ground truth for traceability;
- 200+ documented requirements have **no** test tag, i.e. real traceability gaps for the agent to close;
- ≈ 206 k lines of C/C++ in the core modules (`Svc`, `Fw`, `Os`, `Drv`, `Utils`).

Alternatives considered: NASA cFS apps (C, requirements in CSV but only 1 requirement referenced from tests:
too weak for traceability); a synthetic radio-link C library (full control, but not credible as real code).

## 4. Architecture

```
 Engineers ─ IDE (Continue) / CLI (Aider) ─┐
                                            │ OpenAI-compatible API
 Agent (LangGraph ⏳) ──────────────────────┤
                                            ▼
                     Inference server  (vLLM  |  llama.cpp server)
                     GPU profile: 2×T4 (benchmarks) · CPU profile: laptop (dev)
         │ MCP                          │ MCP                         │ git
         ▼                              ▼                             ▼
  knowledge-mcp (Python)         Jenkins + official MCP        F´ repository
  └─ Neo4j: code graph +         plugin: pipeline builds        (branches created
     requirements + tests +      and runs F´ unit tests          by the agent)
     doc chunks + vector index
```

Knowledge graph schema (initial):
`(:Requirement {id, text, method})-[:ALLOCATED_TO]->(:Component)`,
`(:TestCase)-[:VERIFIES]->(:Requirement)` (ground truth from `REQUIREMENT()` tags),
`(:Component)-[:CONTAINS]->(:File)-[:DEFINES]->(:Class|:Function)`, `(:Function)-[:CALLS]->(:Function)`,
`(:TestCase)-[:EXERCISES]->(:Function)`, `(:DocChunk {embedding})-[:DESCRIBES]->(:Component)`.
Neo4j holds graph and vectors in one store (fewer moving parts).

## 5. Work packages and measured outputs

| WP | Content | Measured outputs |
|---|---|---|
| **WP0 Probe** (Kaggle, ≈2–3 h) | Each candidate model × {llama.cpp, vLLM}: load, VRAM, TTFT, decode/prefill speed, 4× concurrency, compile-and-test smoke | Compatibility matrix → model shortlist |
| **WP1 Serving & sizing** | Load-test client (concurrency sweep, code-assistant traffic profiles); engine and quantization comparison; sizing calculator (weights + KV cache, including linear-attention state for hybrid models); Docker Compose deployment (CPU/GPU profiles, offline mode) | TTFT p50/p95, tokens/s vs concurrency; predicted-vs-measured error; sizing for 20 / 100 / 300 engineers |
| **WP2 Knowledge layer** | Tree-sitter ingestion of F´ (C++), SDD requirement parsing, test tagging, local embeddings, Neo4j; MCP server (`search`, `get_symbol`, `callers/callees`, `get_requirement`, `trace`, `coverage_gaps`) | Traceability recovery P/R/F1 on 152 ground-truth requirements: BM25 vs vector vs graph vs hybrid; retrieval recall@k on a curated question set |
| **WP3 Model evaluation** | ≈30 contamination-free embedded C tasks written for this project: generation (hidden tests, `-Wall -Werror`), unit-test generation (gcov coverage + mutation score), refactoring (tests still pass + complexity delta) | pass@1, coverage, mutation score, latency and tokens per task, per model |
| **WP4 Agent + CI** | LangGraph agent ⏳: pick an untested requirement from the KG → retrieve requirement, code and existing tester via MCP → write an F´ test with a `REQUIREMENT()` tag → build and run → fix loop → branch + commit → Jenkins run via MCP → update graph | On ≈20 untested requirements: compile rate, pass rate, iterations, coverage delta, manually reviewed relevance |
| **WP5 Study & strategy** (EN + FR) | Productivity proxies from WP3/WP4; controlled pilot protocol (SPACE-style metrics); phased scale-up, hardware tiers, model governance (eval gates in CI), security for air-gapped sites | Report + design-decision record for interviews |

**Milestone M1** (first public, CV-ready version): WP0 + WP1 + WP2.
**Milestone M2**: WP3 + WP4 + WP5.

## 6. Repository layout

```
<repo> ⏳/
├── README.md · README.fr.md
├── docs/            PLAN · ARCHITECTURE · DESIGN_DECISIONS · results/ · report (EN/FR)
├── kaggle/          00_probe · 01_serving_bench · 02_model_eval · 03_agent_eval
├── src/<pkg>/       sizing/ · bench/ · knowledge/ · mcp_server/ · agent/ · eval/
├── tasks/           embedded C evaluation suite
├── deploy/          docker-compose.yml (cpu / gpu profiles) · jenkins/ · continue & aider configs
├── tests/           pytest
└── .github/workflows/ci.yml   ruff · type checks · tests
```

Engineering standards: Python ≥ 3.11 with `uv`, ruff, pyright, pytest, pre-commit, GitHub Actions CI,
Apache-2.0 license (same as F´), every number in the README traceable to a committed result file.

## 7. Risks and fallbacks

| Risk | Fallback |
|---|---|
| vLLM cannot run hybrid-attention models on SM 7.5 | Serve those with llama.cpp; vLLM for compatible models; document as a sizing finding (production needs Ampere or newer) |
| F´ unit-test build too heavy for the agent loop | Restrict to a few `Svc` components with pre-generated build cache; pre-built Docker image |
| Small CPU model too weak for live agent demo | Agent evaluation runs on Kaggle with the large model; laptop demo uses recorded runs |
| Kaggle quota | Max 3 GPU runs planned (probe, serving+eval, agent eval), each resumable |

## 8. What you do (≈10 min per step)

1. Run `kaggle/00_probe_t4x2.ipynb` on Kaggle (instructions in its first cell) and put the downloaded
   `probe/` folder in this directory.
2. Create one **empty** GitHub repository with the agreed name.
3. Later: 2 more Kaggle runs (M1 benchmark, M2 evaluation).
