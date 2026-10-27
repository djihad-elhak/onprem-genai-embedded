---
sources:
  - src/onprem_genai/evalsuite/
  - scripts/evalsuite/
  - tests/test_evalsuite.py
---

# Embedded C evaluation suite

A small, executable benchmark for choosing a local code model for embedded work. It covers the four assistant
use cases of the platform (writing code, writing unit tests, refactoring, documenting) and scores every answer by
**running it**: compilation with strict warnings, hidden unit tests, AddressSanitizer / UBSan, gcov coverage,
mutation testing, cyclomatic complexity and Doxygen completeness. No LLM judges are involved.

```bash
oge eval list                                   # 27 tasks + suite fingerprint
oge eval validate                               # the suite checks itself (≈10 s)
oge eval run --reference                        # oracle answers: must score 100 %
oge eval run --base-url http://127.0.0.1:8080 --model default --label "Qwen3.8-27B Q4_K_M" \
             --out artifacts/eval/qwen.json --concurrency 4
oge eval report artifacts/eval/*.json --failures
```

## Why a custom suite

Public code benchmarks (HumanEval, MBPP, LiveCodeBench, SWE-bench) are Python-centric, contaminated in the
training data of recent models, and say nothing about C99 without heap or stdio, fixed-point arithmetic,
protocol framing or wraparound-safe timers. Every task here was written for this project, in the style of radio
and flight software, with references computed independently (Python models for checksums and coders, published
test vectors where they exist, e.g. CRC catalogue check values and the COBS examples).

The suite is intentionally small (27 tasks). It ranks models for one domain; it does not claim general coding
ability. Per-category pass rates come with 95 % bootstrap confidence intervals over tasks, and comparing two
reports from different suite versions is flagged (suite fingerprint = hash of task files and prompts).

## Categories and scoring

| Category | Model receives | Model returns | Pass criterion | Also reported |
|---|---|---|---|---|
| `generate` (12) | spec + `task.h` | `solution.c` | hidden tests pass under `-std=c99 -Wall -Wextra -Wpedantic`; no banned calls (`malloc`, `free`, `printf`, `exit`, ...) | compile rate, ASan/UBSan clean rate, warnings |
| `testgen` (6) | spec + `task.h` + `impl.c` | `tests.c` | tests pass on the correct implementation **and** fail on every seeded mutant (4–6 per task) | line / branch coverage (gcov), mutation score |
| `refactor` (5) | rules + `task.h` + `original.c` | refactored file | hidden tests still pass, max cyclomatic complexity strictly lower (lizard), no `goto`, no banned calls | CCN reduction |
| `document` (4) | rules + `task.h` + `original.c` | documented file | hidden tests pass, code tokens unchanged (only comments added), every function has `@brief`, one `@param` per parameter, `@return` if non-void | completeness ratio |

Tests use a single-header C framework (`include/oge_test.h`: `CHECK`, `CHECK_EQ_U`, `CHECK_EQ_I`, `CHECK_MEM`), so
model-written tests and hidden tests share one convention and nothing has to be installed.

## Self-validation

`oge eval validate` (and the CI test `test_every_task_is_valid`) checks the suite before trusting any score:

* every reference passes its hidden tests; generation references are also sanitizer-clean;
* an automatically generated all-zero stub of each `task.h` compiles **and fails** (hidden tests are not vacuous);
* reference tests of each test-generation task kill **every** mutant, and each task has at least 3 mutants;
* the original code of refactor / document tasks passes its tests but does **not** already count as a pass;
* prompts never contain hidden material (tests, references, mutants) — `test_prompts_contain_inputs_but_never_hidden_material`.

The tasks are produced by two generator scripts (`scripts/evalsuite/gen_*_tasks.py`), so a fix to a task is a
reviewed code change and the files are reproducible byte for byte.

## Protocol

* One system prompt, one user message, no few-shot examples, temperature 0.2, top-p 0.95 (identical for every
  model). Reasoning models may think; `<think>` blocks are stripped before extracting the code block.
* `--samples N` gives pass@1 averaged over N samples and the unbiased pass@N estimator (Chen et al., 2021).
* A failed request counts as a failed sample (reported separately as `request_errors`); answers cut by
  `max_tokens` are counted in `truncated`.
* Runs append each finished job to `<out>.partial.jsonl` and resume from it, so a Kaggle session that is
  interrupted loses at most the jobs in flight.

## Tasks

| Id | Category | Domain | Title | Seeded faults |
|---|---|---|---|---|
| `gen-ccsds-header` | generate | space telemetry and telecommand | CCSDS Space Packet primary header parse / build | |
| `gen-cobs` | generate | serial / radio link framing | COBS framing (Consistent Overhead Byte Stuffing) | |
| `gen-conv-encoder` | generate | radio channel coding | Rate-1/2, K=3 convolutional encoder (generators 7, 5 octal) | |
| `gen-crc16-ccitt` | generate | integrity checks | CRC-16/CCITT-FALSE with incremental update | |
| `gen-crc32` | generate | integrity checks | CRC-32 (ISO-HDLC / IEEE 802.3) | |
| `gen-debounce` | generate | discrete I/O | Switch / discrete-input debouncer | |
| `gen-endian-codec` | generate | protocol encoding | Portable big/little-endian field codec | |
| `gen-hamming74` | generate | forward error correction | Hamming(7,4) encoder / single-error-correcting decoder | |
| `gen-lfsr-scrambler` | generate | radio physical layer | Additive scrambler x^7 + x^4 + 1 | |
| `gen-q15-arith` | generate | fixed-point DSP | Q15 fixed-point multiply and saturating add | |
| `gen-ring-buffer` | generate | driver buffering | Fixed-capacity byte ring buffer | |
| `gen-tick-elapsed` | generate | RTOS timers / watchdogs | Wraparound-safe timeout on a 32-bit tick counter | |
| `tst-ccsds-parse` | testgen | space telemetry | Unit tests for a CCSDS primary-header parser | 6 |
| `tst-fletcher16` | testgen | integrity checks | Unit tests for Fletcher-16 checksum and frame check | 5 |
| `tst-moving-average` | testgen | signal conditioning | Unit tests for an integer moving-average filter | 5 |
| `tst-ring-buffer` | testgen | driver buffering | Unit tests for a byte ring buffer | 5 |
| `tst-saturating-arith` | testgen | fixed-point DSP | Unit tests for saturating 16-bit arithmetic | 5 |
| `tst-tick-elapsed` | testgen | RTOS timers | Unit tests for wraparound-safe timeouts | 4 |
| `ref-command-dispatch` | refactor | payload command handling | Nested command dispatcher → handler table | |
| `ref-config-validate` | refactor | radio configuration | Long validation if-chain → rule table | |
| `ref-frame-parser` | refactor | link-layer framing | goto-based frame parser → small functions | |
| `ref-mode-manager` | refactor | instrument modes | Nested mode manager → state-transition table | |
| `ref-telemetry-pack` | refactor | housekeeping telemetry | Repetitive bit packing → helpers and constants | |
| `doc-ccsds-parse` | document | space telemetry | Document a CCSDS header parser | |
| `doc-pid` | document | control loops | Document a fixed-point PID controller | |
| `doc-ring-buffer` | document | driver buffering | Document a ring-buffer API | |
| `doc-saturating-arith` | document | fixed-point DSP | Document saturating arithmetic helpers | |

## Limits

* 27 tasks give wide confidence intervals: differences of a few points between models are noise; the report
  shows the intervals so they are not over-read.
* Documentation is scored for completeness, not for the accuracy of what the comments say.
* Refactoring is scored by complexity reduction with behaviour preserved; naming and readability beyond that
  are not measured.
* Single-file, single-function-family tasks. Repository-level work (navigating F´, editing several files,
  running its build) is evaluated separately by the test-generation agent.
