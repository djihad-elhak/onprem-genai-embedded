# Paper

**On-Premises LLM Assistance for Embedded Flight Software: Measured Sizing, Traceability Recovery and
Execution-Verified Test Generation** — 6-page IEEE conference paper (IEEEtran), `main.pdf`.

| File | Content |
|---|---|
| `main.tex`, `references.bib` | Paper source (IEEEtran `conference`, US letter) |
| `figures/architecture.tex`, `figures/agent_graph.tex` | TikZ diagrams |
| `figures/serving.tex`, `figures/failure_causes.tex` | pgfplots charts; data in `figures/*.dat` |
| `make_figure_data.py` | Writes `figures/*.dat` from `docs/results` (run 3 serving sweeps, agent v1/v2 records) |

Every number in the paper comes from `docs/results` (benchmark runs 2 and 3, probe run 2, sizing validation).

```bash
uv run python paper/make_figure_data.py      # regenerate the plot data
cd paper && latexmk -pdf main.tex            # needs TeX Live with IEEEtran, pgfplots, fancyvrb
```

On Overleaf: upload `onprem-genai-embedded-paper.zip` (New project → Upload project); it compiles with pdfLaTeX.
