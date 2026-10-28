// Pieces shared by the run and review pages: mutant tables, step timelines and attempt histories.
import { html, useState } from "../vendor/htm-preact-standalone.mjs";
import { Code, Answer, Icon, pct } from "./lib.js";

export function MutantTable({ mutation }) {
  if (!mutation || !mutation.mutants || !mutation.mutants.length) return html`<div class="empty-inline">No mutation analysis for this test.</div>`;
  return html`<div class="evidence" style="padding:0"><div style="padding:0;display:block;overflow:auto">
    <table class="mut">
      <thead><tr><th>Line</th><th>Seeded bug</th><th>Change</th><th>Result</th></tr></thead>
      <tbody>${mutation.mutants.map((m, i) => html`<tr key=${i}>
        <td class="mono num">${m.line}</td>
        <td>${m.operator}</td>
        <td><code class="was">${m.original.trim()}</code><code>${m.mutated.trim()}</code></td>
        <td>${m.outcome === "killed" ? html`<span class="tag ok">caught</span>` : m.outcome === "survived" ? html`<span class="tag warn">missed</span>` : html`<span class="tag">${m.outcome}</span>`}</td>
      </tr>`)}</tbody>
    </table></div></div>`;
}

const NODE_LABEL = { prepare: "baseline", gather: "context", generate: "model", check: "policy", build: "build", test: "test", commit: "commit", evaluate: "mutants", give_up: "result" };

function stepDetail(ev) {
  if (ev.node === "generate" && ev.answer) return { label: "Show answer", body: html`<${Answer} text=${ev.answer} />` };
  if (ev.detail) return { label: ev.node === "check" ? "Show policy finding" : ev.node === "build" ? "Show compiler output" : "Show test output", body: html`<${Code} title=${ev.node === "build" ? "Compiler output" : ev.node === "test" ? "Test output" : "Policy"} text=${ev.detail} kind="log" />` };
  if (ev.node === "gather" && ev.sections) return { label: "Show context", body: html`<div class="evidence">${ev.sections.map((s, i) => html`<div key=${i}><span class="t">${s}</span></div>`)}${ev.dropped && ev.dropped.length ? html`<div><span class="s">Left out to fit the budget: ${ev.dropped.join(", ")}</span></div>` : null}</div>` };
  if (ev.node === "commit" && ev.diff) return { label: "Show diff", body: html`<${Code} title="Changes to the test files" text=${ev.diff} kind="diff" />` };
  if (ev.node === "evaluate" && ev.mutation) return { label: "Show mutants", body: html`<${MutantTable} mutation=${ev.mutation} />` };
  return null;
}

function Step({ ev, defaultOpen }) {
  const d = stepDetail(ev);
  const [open, setOpen] = useState(defaultOpen);
  const cls = ev.node === "gather" || ev.node === "generate" ? "info" : ev.ok ? "ok" : "bad";
  const icon = cls === "info" ? "dot" : ev.ok ? "check" : "x";
  return html`<li class=${`step ${cls} ${ev.node === "generate" && ev.attempt > 1 ? "attempt-start" : ""}`}>
    <span class="step-mark"><${Icon} name=${icon} size=${12} /></span>
    <span class="step-node">${NODE_LABEL[ev.node] || ev.node}</span>
    <div class="step-body">
      <div class="step-line">${ev.line}${d ? html`<button type="button" aria-expanded=${open} onClick=${() => setOpen(!open)}>${open ? "Hide" : d.label}</button>` : null}</div>
      ${open && d ? d.body : null}
    </div>
  </li>`;
}

export function Timeline({ events, live }) {
  const lastBad = events.map((e, i) => (!e.ok ? i : -1)).filter((i) => i >= 0).pop();
  return html`<ol class="timeline">
    ${events.map((ev, i) => html`<${Step} key=${ev.seq} ev=${ev} defaultOpen=${i === lastBad && live} />`)}
    ${live ? html`<li class="step live"><span class="step-mark"></span><span class="step-node">working</span><div class="step-body"><div class="step-line muted">The agent is on the next step…</div></div></li>` : null}
  </ol>`;
}

/** Attempt history of a stored result (imported results have no step events). */
export function History({ record }) {
  const items = record.history || [];
  if (!items.length) return null;
  const label = { build: "Build failed", test: "Test failed", policy: "Policy rejected", regression: "Broke another test", passed: "Passed" };
  return html`<ol class="timeline" style="padding:0">
    ${items.map((h, i) => html`<${HistoryStep} key=${i} h=${h} ok=${h.stage === "passed"} label=${label[h.stage] || h.stage} />`)}
  </ol>`;
}

function HistoryStep({ h, ok, label }) {
  const [open, setOpen] = useState(false);
  return html`<li class=${`step ${ok ? "ok" : "bad"}`}>
    <span class="step-mark"><${Icon} name=${ok ? "check" : "x"} size=${12} /></span>
    <span class="step-node">attempt ${h.attempt}</span>
    <div class="step-body">
      <div class="step-line">${label}${ok ? html`: <span class="mono">${h.detail}</span>` : null}
        ${!ok ? html`<button type="button" aria-expanded=${open} onClick=${() => setOpen(!open)}>${open ? "Hide" : "Show output"}</button>` : null}</div>
      ${open ? html`<${Code} title="Output sent back to the model" text=${h.detail} kind="log" />` : null}
    </div>
  </li>`;
}

export function Coverage({ metrics }) {
  const m = metrics || {};
  return html`<div class="facts">
    ${m.tests_total ? html`<span>Suite <b>${m.tests_total}</b> tests</span>` : null}
    ${m.new_test_coverage ? html`<span>New test alone covers <b>${pct(m.new_test_coverage.line_coverage)}</b> of the lines</span>` : null}
    ${m.coverage_before ? html`<span>Component coverage <b>${pct(m.coverage_before.line_coverage)}</b></span>` : null}
  </div>`;
}
