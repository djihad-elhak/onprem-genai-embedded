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
- **Measured (probe run 2, 2× T4)**: llama.cpp ran all four candidates; vLLM 0.32 ran Qwen3-Coder-30B-A3B well
  (101 tok/s single stream, 245 tok/s at 4 streams vs 82 / 151 for llama.cpp) but its AWQ prefill on SM 7.5 is 5×
  slower (283 vs 1,445 tok/s), and the hybrid Qwen3.8-27B only loaded in eager GPTQ at 4.6 tok/s. Consequence:
  llama.cpp serves agents and evaluation (long prompts), vLLM is kept for high-concurrency chat on MoE models.
- **Would change if**: production hardware is Hopper/Blackwell-only (then vLLM or SGLang everywhere, FP8).

## D3 · Measure first: a probe notebook before any model choice
- **Why**: 2026 hybrid-attention models (Qwen3.6/3.8) needed source patches to run in vLLM on older GPUs; FP8 and
  BF16 are unavailable on T4. Model choices are made from the probe's compatibility matrix, not assumed.
- **It paid off twice**: run 1 exposed a llama.cpp build failure specific to the Kaggle image (no linkable CUDA
  driver library; fixed with an alias and a no-VMM fallback); run 2 showed that the dense 27 B model, attractive
  on paper, decodes at 14 tok/s on T4 while a 30 B MoE reaches 82–101 tok/s.

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
- **Why**: an explicit state machine fits a deterministic engineering loop (retrieve → write test → check →
  build → test → commit, with a bounded repair loop); every node and edge is visible, testable and logged.
  LangGraph adds no model wrapper: the agent calls the platform's OpenAI-compatible endpoint and MCP directly.

## D11 · Kaggle as GPU lab
- **Why**: no local GPU; Kaggle's 2× T4 (32 GB) runs 4-bit 24–35 B models. Notebooks are batch jobs that write
  result files; everything else (graph, MCP, sizing, deploy) runs on a laptop CPU.

## D12 · Agent with bounded authority: the model writes test code, nothing else
- **Choice**: the model returns Tester methods and `TEST()` cases; retrieval, patching (tree-sitter anchors),
  policy, build, run, coverage, git and CI are deterministic nodes whose arguments come from the requirement.
- **Why**: flight-software teams cannot let a model run commands or edit flight code. Confining the edit to three
  test files, enforcing the `REQUIREMENT` tag and rejecting process control / skipped tests makes the agent's
  worst case a bad unit test on a review branch. It also makes runs reproducible and models comparable (same
  context, same tools, same budget).
- **Trade-off**: no free exploration (a tool-calling agent could look up more context); compensated by
  error-driven retrieval (unknown identifiers → *did-you-mean* + definitions over MCP).
- **Would change if**: a sandbox with stronger isolation is available and measured gains justify tool calling.

## D13 · Evaluation by execution, on purpose-written embedded C tasks
- **Choice**: 27 C99 tasks (generation, unit-test generation, refactoring, documentation) scored by compiling and
  running: hidden tests, sanitizers, gcov, mutants, cyclomatic complexity, Doxygen completeness. The suite
  validates itself (references pass, stubs fail, reference tests kill every mutant).
- **Why**: public benchmarks are Python-centric and in the training data; an LLM judge would grade style, not
  behaviour. Embedded constraints (no heap, no stdio, fixed-point, wraparound) are what the target teams need.
- **Limit**: 27 tasks → wide confidence intervals, reported as such.

## D14 · Test quality is measured by fault detection, not by passing
- **Choice**: each verified test is run against gcov-guided mutants of the code it executes (inverted conditions,
  bounds, swapped statuses, deleted port calls / events); score = killed / valid.
- **Why**: a test that passes may assert nothing useful; coverage counts lines, not checks. Mutants answer "would
  this test catch a bug here?". Relevance to the requirement still gets a human verdict (review sheet).

## D15 · CI through the official Jenkins MCP Server plugin
- **Choice**: Jenkins LTS + `mcp-server` plugin, configured as code; the agent uses a service account with
  Overall/Read, Job/Read, Job/Build only; the pipeline tests the agent's branch from a read-only mount.
- **Why**: the target environment already runs Jenkins; the plugin exposes builds, queue, test results and logs
  as MCP tools and filters them by the caller's permissions, so the same server also serves IDE assistants.
  A custom REST client would duplicate that and bypass the permission model.

## D16 · Benchmark shortlist: Qwen3-Coder-30B-A3B and Devstral-Small-2-24B
- **Choice**: the two code-specialised families named in the target role; quality stages
  (`oge eval`, agent) on llama.cpp for both, same 4-bit format family and context budget.
- **Why**: one Kaggle session (≈ 5 h) instead of two; the pair contrasts a fast MoE with a dense model of similar
  memory footprint. Qwen3.6-35B-A3B and Qwen3.8-27B remain in the probe and the sizing data.

## D17 · Agent iterations are driven by classified failures and re-measured on the same targets
- **Choice**: after each model run, every failed attempt gets a primary cause (`agent.runner.failure_causes`,
  first matching rule over the build / policy / test diagnostics); the agent is changed only where a cause
  points at the agent itself, and the new version runs on the same 28 requirements with the same models.
- **Why**: in run 2, 54 % of failed attempts came from the agent's own context (a dispatch rule stated without
  the component kind, a did-you-mean hint offering a method F´ v4 lacks) and 8 from a patcher bug. Tuning on
  anecdotes would not have found that; tuning on the test set's answers would be overfitting, so v2 changes
  general rules (component kind, block reuse, assertion sources), never per-requirement content.

## D18 · Serving benchmark: every concurrency level on new prompts
- **Choice**: each level of a sweep sends requests that no earlier level sent, starting at random lines of the
  corpus; the warm-up uses a disjoint range. Only the agent profile's repository prefix is shared, by design.
- **Why**: run 2 re-sent the same 8 prompts at 1, 2 and 4 streams, so the prefix / prompt caches answered
  levels 2 and 4 (vLLM: time to first token 8.8 s → 0.26 s on 9.7k-token prompts). A capacity plan built on
  cached throughput would under-buy hardware.

## D19 · Sizing calibrated per engine and per architecture class, validated against load tests
- **Choice**: decode / prefill efficiencies are fitted on probe measurements per engine, with dense and MoE
  models fitted separately (`oge sizing calibrate`); every calibration is checked leave-one-model-out and
  against an independent load test (`oge sizing capacity` vs the serving sweep).
- **Why**: on llama.cpp / T4 dense models reach 77 % of peak bandwidth when decoding and MoE models 59 %
  (prefill 51 % vs 20 % of peak FP16); one shared value mispredicted MoE prefill by up to +239 %. Split by class,
  decode is within ±11 % and one server's chat capacity within 7 % of the measurement. vLLM on Turing is
  calibrated separately because its kernel path there (no Marlin, no FlashAttention 2) is not representative.

## D20 · A web console for the site, built from the platform's own pieces
- **Choice**: `oge console` serves a web application on the same machine as the model servers: traceability
  map, requirement evidence, code search, agent runs with live steps, a review queue and GPU sizing. Starlette
  and server-sent events (already MCP SDK dependencies), SQLite, and a no-build Preact front end on the NASA
  Horizon Design System (public domain), vendored with its fonts; oge keeps its own mark and uses no NASA
  insignia. Runs are queued on one F´ working copy, each on its own branch from a fixed base commit; a
  stop request finishes the current requirement. The model server's API key is write-only.
- **Why**: the agent's output is only worth something once a person has reviewed it, and engineers will not
  review from a terminal. Building on the existing graph, MCP server, agent and planner keeps one source of
  truth, and having no CDN, build step or extra service keeps the air-gap promise (D9). Replay of recorded
  answers is limited to self-contained ones: in the live test of this feature, a repair answer that resent
  only one block could not pass on its own.

---

## Questions to expect (and where the answers are)

| Question | Answer |
|---|---|
| How many GPUs for 100 engineers? | `oge sizing plan …` — explicit workload assumptions, calibrated efficiencies; see D4 and `docs/results`. |
| Why not just use an API (Copilot, Claude)? | Data cannot leave the site; D9, security defaults in ARCHITECTURE §6. |
| How do you know the RAG works? | Traceability benchmark with ground truth, confidence intervals, ablation (D6). |
| What does "288 gaps" mean exactly? | Requirements specified as verified by test with no explicit test tag — candidates for review, not proof of missing tests. |
| What happens when the model is wrong? | Suggestions are ranked with evidence (file:line, scores); agent output must pass policy, build and tests (3 runs, no regression), then CI and human review; it can only ever touch test files (D12). |
| Can the agent break flight code? | No path exists: it writes only into `test/ut` of one component, on a branch, and its CI account cannot administer Jenkins (D12, D15). |
| How do you know generated tests are useful? | Fault detection on mutants of the code they execute (D14) + a human relevance verdict per test, given in the console's review queue (D20). |
| How do you choose a model for code? | `oge eval` on embedded C tasks scored by execution (D13) + agent metrics on real F´ gaps; speed from the probe and serving benchmark. |
| Why these models? | Probe compatibility matrix + license + measured speed/quality on T4 (D3). DeepSeek-V4 is sized but does not fit the test hardware. |
| How would you scale it? | Profiles `gpu` → `vllm`; replicas behind a gateway; Neo4j for the graph; per-team MCP servers; see sizing report. |
