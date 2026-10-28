# Demo recordings

The GIFs in the main README are terminal sessions recorded from these scripts, on the real F´ v4.4.1 checkout,
with the real knowledge graph, MCP server, `fprime-util` build, gtest run, git and mutation analysis.

| Scene | What runs | Model |
|---|---|---|
| `scenes/agent.sh` | `oge agent run --trace` closes SVC-COMSTUB-007: context over MCP, answer, policy check, build, 3 test runs + full suite, commit on a review branch, 4 mutants | **Replay** of Qwen3-Coder-30B-A3B's real answer from benchmark run 3 (`qwen3-coder-run3-replay.json`); it verified this requirement at its first attempt, so the replayed text is its whole output |
| `scenes/repair.sh` | The repair loop: compiler error → did-you-mean hint → second answer → pass | **Scripted** answers with a deliberate mistake (`tests/data/scripted_agent_answers.json`) |
| `scenes/mcp.sh` | `mcp_tour.py`: the knowledge MCP server's tools, called over the MCP protocol | none |
| `scenes/eval.sh` | `oge eval validate`, then the two models measured on Kaggle | stored run-2 reports |

No GPU is needed: a model is replayed because the recording machine has none. With a served model, replace
`--scripted …` by `--base-url http://localhost:8080 --label <model>`; everything else is identical.

Re-record (needs `asciinema` and [`agg`](https://github.com/asciinema/agg), and `scripts/setup_fprime_ut.sh`):

```bash
demo/record.sh               # all scenes → demo/casts/*.cast and docs/assets/demo-*.gif
demo/record.sh agent         # one scene
```

Long waits are shortened to 1.5 s in the recordings (asciinema idle-time limit); the timings printed by the
tools are the real ones.
