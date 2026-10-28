// Overview: the traceability map of the whole code base, what needs a person, and the platform's health.
import { html, useState, useApi, href, go, STATES, STATE_ORDER, showTip, hideTip, esc, fmtInt, ago, RunStatus, Loading, ErrorNote, ArrowLink } from "../lib.js";

function Legend({ counts, active, toggle }) {
  return html`<div class="legend" role="group" aria-label="Show requirement states">
    ${STATE_ORDER.filter((s) => counts[s]).map((s) => html`<button type="button" key=${s} aria-pressed=${active.has(s)} onClick=${() => toggle(s)} title=${STATES[s].help}>
      <i class=${`s-${s}`}></i><span>${STATES[s].label}</span><span class="n">${fmtInt(counts[s])}</span>
    </button>`)}
  </div>`;
}

function TraceMap({ modules, active }) {
  const open = (id) => go("requirements", null, { id });
  const tip = (it) => `<b>${esc(it.req_id)}</b><br>${esc(STATES[it.state].label)}`;
  return html`<div class="tmap">
    ${modules.map((m) => html`<div class="tmap-row" key=${m.module}>
      <div class="tmap-name">
        <a href=${href("requirements", null, { module: m.module })} title=${`Open the requirements of ${m.module}`}>${m.module}</a>
        <span class="n">${m.items.length}</span>
      </div>
      <div class="ticks">
        ${m.items.map((it) => html`<button type="button" key=${it.req_id} class=${`tick s-${it.state} ${active.has(it.state) ? "" : "dim"}`}
          aria-label=${`${it.req_id}: ${STATES[it.state].label}`}
          onMouseEnter=${(e) => showTip(e, tip(it))} onFocus=${(e) => showTip(e, tip(it))}
          onMouseLeave=${hideTip} onBlur=${hideTip} onClick=${() => { hideTip(); open(it.req_id); }}></button>`)}
      </div>
    </div>`)}
  </div>`;
}

function Platform({ status }) {
  if (!status) return html`<${Loading} lines=${3} />`;
  const ws = status.workspace, llm = status.llm, g = status.graph;
  const rows = [
    [llm.configured ? "ok" : "warn", "Model server", llm.configured ? `${llm.label || llm.model} at ${llm.base_url}` : "Not set. Agent runs can still replay recorded answers.", href("settings")],
    ["ok", "Knowledge graph", `${fmtInt(g.requirements)} requirements, ${fmtInt(g.tests)} tests, ${fmtInt(g.functions)} functions`, null],
    [ws.ready ? "ok" : "bad", "F´ workspace", ws.ready ? `Builds and runs unit tests. Runs start from ${ws.base_commit ? ws.base_commit.slice(0, 7) : "HEAD"}.` : ws.problems.join("; "), null],
    [status.replay.requirements ? "ok" : "warn", "Recorded answers", status.replay.requirements ? `${status.replay.requirements} requirements can be replayed without a model server` : "None loaded", null],
  ];
  return html`<div class="status-list">
    ${rows.map(([cls, what, detail, link]) => html`<div class="status-row" key=${what}>
      <span class=${`light ${cls}`}></span>
      <div><div class="what">${what}</div><div class="detail">${detail}</div></div>
      ${link ? html`<a href=${link}>Change</a>` : html`<span></span>`}
    </div>`)}
  </div>`;
}

function Stat({ fig, state, children }) {
  return html`<div class="stat" role="listitem">
    <span class="fig">${fmtInt(fig)}</span>
    <span class="cap">${state ? html`<span class="key"><i class=${`s-${state}`}></i>${children}</span>` : children}</span>
  </div>`;
}

export function Overview({ status }) {
  const [data, error, reload] = useApi("/overview");
  const [active, setActive] = useState(new Set(STATE_ORDER));
  const toggle = (s) => {
    const next = new Set(active);
    if (next.size === STATE_ORDER.length) { next.clear(); next.add(s); }
    else if (next.has(s)) { next.delete(s); if (!next.size) STATE_ORDER.forEach((x) => next.add(x)); }
    else next.add(s);
    setActive(next);
  };
  if (error && !data) return html`<div class="container page"><${ErrorNote} error=${error} onRetry=${reload} /></div>`;
  if (!data) return html`<div class="container page"><${Loading} lines=${6} /></div>`;
  const c = data.counts;
  const open = c.gap + c.attempted + c.rejected;
  const testable = data.total - c.not_by_test;
  const evidence = c.covered + c.accepted;
  return html`<div class="container page">
    <div class="page-head">
      <div class="stack">
        <span class="overline">Traceability</span>
        <h1>Traceability of the code base</h1>
        <p class="lede">${fmtInt(data.total)} requirements in the design documents, ${fmtInt(testable)} of them to be verified by test.
          ${" "}${fmtInt(evidence)} have test evidence; ${fmtInt(open)} still have none.</p>
      </div>
      <div class="actions">
        ${data.review.pending ? html`<${ArrowLink} href=${href("review")}>Review ${data.review.pending} generated test${data.review.pending === 1 ? "" : "s"}<//>` : html`<${ArrowLink} href=${href("requirements", null, { state: "gap,attempted,rejected" })}>Find open gaps<//>`}
      </div>
    </div>

    <div class="stats" role="list" aria-label="Requirements to be verified by test">
      <${Stat} fig=${c.covered} state="covered">Cited by an existing unit test<//>
      <${Stat} fig=${c.accepted + c.generated} state="generated">Have a generated test, ${fmtInt(c.accepted)} accepted by a reviewer<//>
      <${Stat} fig=${open} state="gap">Still without test evidence${c.attempted ? `, ${fmtInt(c.attempted)} tried by the agent` : ""}<//>
      <${Stat} fig=${c.not_by_test} state="not_by_test">Verified by inspection or analysis instead<//>
    </div>

    <section class="stack" aria-labelledby="map-title">
      <div class="section-head">
        <h2 id="map-title">Requirements by component</h2>
        <span class="muted">One mark per requirement. Select a mark to open it.</span>
      </div>
      <${Legend} counts=${c} active=${active} toggle=${toggle} />
      <${TraceMap} modules=${data.modules} active=${active} />
    </section>

    <div class="cols-2">
      <section class="stack" aria-labelledby="needs-title">
        <div class="section-head"><h2 id="needs-title">Waiting for a person</h2></div>
        <div class="big-call">
          <span class="fig">${data.review.pending}</span>
          <div class="stack" style="gap:0.5rem">
            <span>generated test${data.review.pending === 1 ? "" : "s"} wait for a review verdict. ${data.review.reviewed} reviewed so far.</span>
            ${data.review.pending ? html`<${ArrowLink} href=${href("review")}>Start reviewing<//>` : null}
          </div>
        </div>
        <div class="section-head" style="border-bottom-width:1px"><h3>Recent agent runs</h3><span class="end"><a href=${href("runs")}>All runs</a></span></div>
        ${data.runs.length ? html`<div>
          ${data.runs.map((r) => html`<a class="run-line" href=${href("runs", r.id)} key=${r.id}>
            <${RunStatus} status=${r.status} />
            <span><span class="t">Run ${r.id}, ${r.req_ids.length} requirement${r.req_ids.length > 1 ? "s" : ""}</span><span class="s">${r.model_label}</span></span>
            <span class="meta">${ago(r.created_at)}</span>
          </a>`)}
        </div>` : html`<div class="empty"><p>No runs yet. Open a requirement with no test evidence and generate a test, or select several on the Requirements page.</p>
          <a class="btn" href=${href("requirements", null, { state: "gap" })}>Find gaps</a></div>`}
      </section>
      <section class="stack" aria-labelledby="health-title">
        <div class="section-head"><h2 id="health-title">Platform</h2><span class="muted">Everything runs on this site</span></div>
        <${Platform} status=${status} />
      </section>
    </div>
  </div>`;
}
