---
sources:
  - src/onprem_genai/sizing/
  - src/onprem_genai/evalsuite/
  - src/onprem_genai/agent/
  - deploy/
---

# Measuring productivity and scaling up

[Français](STRATEGY.fr.md)

This document turns the platform into a decision process: what to measure before rollout, how to run a pilot
that can actually show an effect, and how to grow from one GPU server to a department, with the controls an
air-gapped engineering site needs. Measured numbers come from the Kaggle runs (`docs/results/`) and the sizing
calibration; nothing here is extrapolated from vendor claims.

## 1. Three levels of evidence

| Level | Question | Instrument in this repository | When |
|---|---|---|---|
| **Capability** | Can a model / engine / hardware combination do the work, fast enough? | `oge eval` (27 embedded C tasks scored by execution), agent benchmark (28 F´ requirement gaps, fault detection), traceability benchmark (MAP / recall with CIs), serving benchmark (TTFT, TPOT, throughput vs concurrency), `oge sizing` | Before any rollout, and at every model or engine change |
| **Usage** | Is it used, and does it hold its service level? | Server metrics (`--metrics` on llama.cpp, vLLM Prometheus endpoint): requests, tokens, queue time, latency percentiles; MCP tool calls; agent runs and their review outcome | Continuously, aggregated per team |
| **Outcome** | Does it change delivery and quality? | Pilot protocol below | Pilot, then quarterly |

Capability numbers are *upper bounds on value*: a model that passes 60 % of unit-test-generation tasks will not
make engineers 60 % faster. Only the outcome level answers the productivity question, and it needs a protocol.

## 2. Productivity proxies

Single metrics are gamed or misleading (lines of code, number of suggestions accepted). The pilot tracks a
balanced set, following the SPACE framework (Forsgren et al., 2021: Satisfaction, Performance, Activity,
Communication, Efficiency) and DORA-style delivery metrics, adapted to embedded / flight software:

| Dimension | Proxy | Source |
|---|---|---|
| Performance (quality) | defects found in integration or later per change; review findings per change; unit-test coverage and mutation score of changed code | issue tracker, review tool, CI (gcov, mutants as in `oge eval`) |
| Performance (traceability) | share of requirements with a tagged, passing test; gaps closed per month | knowledge graph (`oge knowledge gaps`) |
| Efficiency | lead time from first commit to merge; time to first review; time spent on unit tests and documentation (survey) | Git, review tool, survey |
| Activity | assisted sessions per engineer, agent runs, accepted agent tests | platform metrics |
| Satisfaction | survey (perceived usefulness, trust, cognitive load), opt-out rate | quarterly survey |
| Communication | review discussion length, rework rounds | review tool |

Metrics are reported **per team and in aggregate only**, never per engineer.

## 3. Pilot protocol

**Design.** 8–12 weeks, 2–4 volunteer teams, stepped-wedge rollout: all teams start with a 4-week baseline
without the assistant, then teams switch on at staggered dates. Each team is its own control and the staggering
separates the effect of the tool from calendar effects (release crunches, holidays).

**Task study (inside the pilot).** A set of representative tasks taken from the teams' backlog (write unit tests
for a requirement, refactor a function under the coding standard, document a module, fix a static-analysis
finding), each done once with and once without the assistant by different engineers (crossover, randomised
order). Time is recorded; outputs are scored **blind** by reviewers with the same objective criteria as
`oge eval` (tests pass, coverage, mutants killed, complexity, documentation completeness).

**Guardrails.** Any security incident, confidential data leaving the site, or a quality regression (defect rate,
review findings) above an agreed threshold pauses the pilot.

**People and law.** The assistant is a tool for engineers, not a monitoring device: only aggregated data, a
documented retention period, GDPR information to participants, and in France the works council (CSE) is
involved before introduction, since new technologies affecting working conditions require its consultation.

**Decision.** Go to phase 2 if (a) quality proxies do not degrade, (b) at least one efficiency proxy improves
beyond the baseline's week-to-week variation, (c) satisfaction is positive and opt-out is low, and (d) the
service level (TTFT, tokens/s per user) held at the pilot's peak load. Small pilots give wide intervals: the
report states them and does not over-read differences inside them.

## 4. Scale-up path

| Phase | Users | Platform | Gate to next phase |
|---|---|---|---|
| 0 · Reference (this repository) | — | laptop CPU + test GPUs; air gap verified in CI | capability benchmarks ✅ (2 models measured) |
| 1 · Pilot | 20–40 | one GPU server: one code model + embeddings + knowledge MCP server; Jenkins MCP integration; IDE configs | pilot decision (§3) |
| 2 · Department | 100–400 | vLLM replicas behind a gateway (per-team API keys, quotas, routing), shared Neo4j graph, one knowledge MCP server per repository family, model registry | SLO held at measured peak; eval gate in place |
| 3 · Multi-site / larger models | 400+ | larger MoE models (DeepSeek-V4-Flash class) on high-memory GPUs, regional replicas | cost per active engineer within budget |

Hardware per phase comes from `oge sizing plan <model> --scenario <chat|chat_agents|full> --engineers N` with
efficiencies calibrated on measured runs (`--calibration`). The workload assumptions are explicit
(`src/onprem_genai/sizing/data/workloads.yaml`: 60 % of the team active at peak, 20 tokens/s per stream, 1.25
headroom, request rates per class) and are replaced by pilot telemetry as soon as it exists.

Calibrated team tables, Qwen3-Coder-30B-A3B, 4-bit weights (full table, Devstral and all scenarios:
[`docs/results/sizing/team_tables.md`](results/sizing/team_tables.md)):

| Scenario | Engineers | L4 | L40S | A100 80 GB | H100 SXM |
|---|---|---|---|---|---|
| chat | 100 | 2 | 1 | 1 | 1 |
| chat + agents | 100 | 6 | 2 | 1 | 1 |
| chat + agents | 400 | 16 | 6 | 4 | 2 |
| chat + agents + completion | 400 | 16 | 6 | 4 | 2 |

Agents dominate: an agent step re-sends ≈ 12k tokens of context, so at 400 engineers the agent scenario needs
2–4× the GPUs of chat alone, even with 70 % of each agent prompt served from the prefix cache. Devstral-Small-2-24B,
a dense model, needs up to 2× (typically 1.5×) the GPUs of the MoE Qwen3-Coder for the same team.

Why calibration matters, and how far it can be trusted
([`docs/results/sizing`](results/sizing/README.md)):

- On the same 2× T4, the engine and the architecture change speed by an order of magnitude: a 27 B dense model
  decodes at 13.9 tokens/s on llama.cpp and 4.6 on vLLM (eager GPTQ), a 30 B MoE with 3.3 B active parameters at
  82 (llama.cpp) to 101 (vLLM).
- Dense and MoE models reach very different fractions of the hardware peak (decode 77 % vs 59 % of bandwidth,
  prefill 51 % vs 20 % of FP16 compute on llama.cpp), so they are calibrated separately.
- Validated on the hardware we could measure: decode is predicted within ±11 % leave-one-model-out and within
  4 % on an independent run; the capacity of one 2× T4 llama.cpp server for chat is predicted within 7 % of the
  load test. Prefill of MoE models and time to first token are less accurate (−44 % to +79 %, −21 % to −36 %).
- The tables assume the T4 efficiencies carry over to the target GPU and engine. That is the weakest link, so
  the first step of the pilot is to re-run the probe notebook on the candidate server and regenerate the tables
  (`oge sizing calibrate` → `oge sizing report`) before ordering hardware.

## 5. Model governance

- **Admission**: open-weight models with a permissive licence (Apache-2.0 / MIT), downloaded from the official
  repository on a connected machine, checksummed (`scripts/download_models.sh` writes `SHA256SUMS`), transferred
  and verified on site.
- **Eval gate**: a new model, quantization, engine version or prompt template is promoted only if `oge eval` and
  the agent benchmark do not regress beyond their confidence intervals, and the serving benchmark holds the SLO.
  The suite fingerprint ties results to the exact task and prompt versions.
- **Pinning and rollback**: engine images pinned by digest, model files by hash, configuration in Git; the
  previous version stays deployable.
- **Context boundaries**: knowledge MCP servers are scoped per repository family and inherit its access rights;
  no credentials or classified material in indexed sources.

## 6. Security on an air-gapped site

- No outbound connection at runtime, verified by a failing test (egress probe on an internal Docker network).
- Services bound to the internal network or localhost; API keys on the LLM servers; per-team keys at the gateway.
- Agents have bounded authority: the test-generation agent writes only test files on a review branch; its Jenkins
  account can read jobs and start builds, nothing else; every agent commit carries an AI-use disclosure.
- Audit: who used which model, when, with which MCP tools — retained for a defined period; prompt content logged
  only where the data classification allows it.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Plausible but wrong code or tests | execution-based gates (build, tests, mutants), CI, mandatory human review |
| Over-reliance, skill erosion for junior engineers | assistant positioned for tests, documentation and exploration first; review training; survey tracking |
| Licence contamination of generated code | permissive-licence models only; similarity checks on large generated blocks where required |
| Model churn (new versions every few months) | eval gate + pinning makes upgrades a routine, measured change |
| Hardware lead times | sizing with calibrated efficiencies and explicit headroom; MoE models reduce the bandwidth needed per user |
