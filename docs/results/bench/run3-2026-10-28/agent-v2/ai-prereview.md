# Relevance pre-review of the 36 verified tests (agent v2, run 3)

**Reviewer: an AI model (LLM), not an engineer.** For each verified test, the question of the review sheets
(`*.review.md`) was asked: *does the test exercise the behaviour the requirement states and check its outcome?*
These verdicts are a first pass to speed up the human review. They do not replace it: the review sheets keep an
empty `verdict` line for the engineer's own verdict.

**Result: 30 relevant, 6 partial, 0 not relevant.** Every partial verdict is about coverage of the requirement
(one of several cases tested), not about a wrong check. Two requirements' tests kill none of the 4 sampled
mutants (SVC-COMSTUB-002 for both models, SVC-ROUTER-007 for Devstral) although they check the right outputs:
the sampled mutants were on other paths, so the sample of 4 per test is too small to judge them.

## Qwen3-Coder-30B-A3B — 15 relevant, 3 partial

| Requirement | Verdict | Why |
|---|---|---|
| SVC-COMSTUB-001 | relevant | buffer on `dataIn` reaches `drvSendOut` (sync) and `drvAsyncSendOut` (async), buffer checked |
| SVC-COMSTUB-002 | relevant | `OP_OK` send → exactly one `SUCCESS` on `comStatusOut` |
| SVC-COMSTUB-003 | relevant | `OTHER_ERROR` send → exactly one `FAILURE` |
| SVC-COMSTUB-004 | relevant | `SEND_RETRY` with failing retries → `RETRY_LIMIT` sends, buffer returned, `FAILURE` |
| SVC-COMSTUB-005 | partial | the requirement mixes ByteStreamRead and ByteStreamSend; the test checks that the sent buffer is returned on `dataReturnOut` after success (sync and async) |
| SVC-COMSTUB-006 | relevant | driver connection → exactly one `SUCCESS` |
| SVC-COMSTUB-007 | relevant | failure, then reconnection → exactly one `SUCCESS` |
| SVC-COMRETRY-001 | relevant | `dataIn` → `dataOut` with the same buffer and context |
| SVC-COMRETRY-002 | relevant | the buffer and context received on `dataReturnIn` are the ones returned upstream on `SUCCESS` (black-box evidence of storage) |
| SVC-COMRETRY-005 | relevant | `SUCCESS` and `FAILURE` pass through when no buffer is pending |
| PRMDB-003 | relevant | `setPrm` then `getPrm` returns the value written |
| PRMDB-004 | relevant | `PRM_SAVE_FILE` → `OK` response and save-complete event with the parameter count |
| PRMDB-005 | relevant | empty file name → `VALIDATION_ERROR` and `PrmDbFileLoadFailed`, staging database unchanged, in both merge modes |
| SVC-ROUTER-001 | partial | routes a command packet only; routing *by type* needs several types |
| SVC-ROUTER-002 | relevant | command packet → `commandOut` only, ownership returned |
| SVC-ROUTER-003 | relevant | file packet → `fileOut` only |
| SVC-ROUTER-008 | partial | context restored across the `unknownDataOut` round-trip only (not `fileOut`, not the direct return) |
| SVC-ROUTER-009 | relevant | both the not-found and the table-full cases (note: heap allocation in the test, leaked if an assertion fails early) |

## Devstral-Small-2-24B — 15 relevant, 3 partial

| Requirement | Verdict | Why |
|---|---|---|
| SVC-COMSTUB-001 | relevant | buffer forwarded to the driver send port of the tester's mode |
| SVC-COMSTUB-002 | relevant | `OP_OK` send → exactly one `SUCCESS` |
| SVC-COMSTUB-003 | relevant | `OTHER_ERROR` send → exactly one `FAILURE` |
| SVC-COMSTUB-004 | relevant | `SEND_RETRY` → `RETRY_LIMIT` sends, buffer returned, final status |
| SVC-COMSTUB-005 | partial | same ambiguity as above; sync path only |
| SVC-COMSTUB-006 | relevant | driver connection → exactly one `SUCCESS` |
| SVC-COMSTUB-007 | relevant | exhausted retries → `FAILURE`, then reconnection → exactly one `SUCCESS` |
| SVC-COMRETRY-004 | relevant | `FAILURE` then `SUCCESS` with a retry available → the buffer is sent again |
| SVC-COMRETRY-005 | relevant | `SUCCESS` and `FAILURE` pass through, in order, when no buffer is pending |
| PRMDB-003 | relevant | `setPrm` emits `PrmIdAdded`; `getPrm` returns the value |
| PRMDB-004 | relevant | two parameters saved, save-complete event with count 2 |
| PRMDB-005 | relevant | empty file name rejected in both merge modes, staging database unchanged (some checks use `FW_ASSERT` instead of gtest macros) |
| SVC-ROUTER-001 | relevant | command, file and unknown packets each reach their own port |
| SVC-ROUTER-003 | relevant | file packet → `fileOut` only |
| SVC-ROUTER-004 | relevant | unknown packet → `unknownDataOut` only |
| SVC-ROUTER-007 | relevant | ownership returned on the command, file and unknown paths |
| SVC-ROUTER-008 | partial | `unknownDataOut` round-trip only |
| SVC-ROUTER-009 | partial | not-found case only; the table-full case is not tested |
