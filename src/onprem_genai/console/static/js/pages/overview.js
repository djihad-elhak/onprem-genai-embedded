// Overview: the traceability map of the whole code base, what needs a person, and the platform's health.
import { html, useState, useApi, href, go, State, STATES, STATE_ORDER, showTip, hideTip, esc, fmtInt, ago, RunStatus, Loading, ErrorNote, Icon } from "../lib.js";

function Legend({ counts, active, toggle }) {
  return html`<div class="legend" role="group" aria-label="Show requirement states">
    ${STATE_ORDER.filter((s) => counts[s]).map((s) => html`<button type="button" aria-pressed=${active.has(s)} onClick=${() => toggle(s)} title=${STATES[s].help}>
      <i class=${`s-${s}`}></i><span>${STATES[s].label}</span><span class="n">${fmtInt(counts[s])}</span>
    </button>`)}
  </div>`;
}

function TraceMap({ modules, active }) {
  const open = (id) => go("requirements", null, { id });
  return html`<div class="tmap">
    ${modules.map((m) => html`<div class="tmap-row" key=${m.module}>
      <div class="tmap-name">
        <a href=${href("requirements", null, { module: m.module })} title=${`Open the requirements of ${m.module}`}>${m.module}</a>
        <span class="n">${m.items.length}</span>
      </div>
      <div class="ticks">
        ${m.items.map((it) => html`<button type="button" class=${`tick s-${it.state} ${active.has(it.state) ? "" : "dim"}`}
          aria-label=${`${it.req_id}: ${STATES[it.state].label}`}
          onMouseEnter=${(e) => showTip(e, `<b>${esc(it.req_id)}</b><br>${esc(STATES[it.state].label)}`)}
          onFocus=${(e) => showTip(e, `<b>${esc(it.req_id)}</b><br>${esc(STATES[it.state].label)}`)}
          onMouseLeave=${hideTip} onBlur=${hideTip} onClick=${() => { hideTip(); open(it.req_id); }}></button>`)}
      </div>
    </div>`)}
  </div>`;
}

function Health({ status }) {
  if (!status) return html`<div class="panel-body"><${Loading} lines=${3} /></div>`;
  const ws = status.workspace, llm = status.llm, g = status.graph;
  const rows = [
    [llm.configured ? "ok" : "warn", "Model server", llm.configured ? `${llm.label || llm.model} at ${llm.base_url}` : "Not set. Agent runs can still replay recorded answers.", href("settings")],
    ["ok", "Knowledge graph", `${fmtInt(g.requirements)} requirements, ${fmtInt(g.tests)} tests, ${fmtInt(g.functions)} functions`, null],
    [ws.ready ? "ok" : "bad", "F´ workspace", ws.ready ? `Builds and runs unit tests; runs start from ${ws.base_commit ? ws.base_commit.slice(0, 7) : "HEAD"}` : ws.problems.join("; "), null],
    [status.replay.requirements ? "ok" : "warn", "Recorded answers", status.replay.requirements ? `${status.replay.requirements} requirements can be replayed without a model server` : "None loaded", null],
  ];
  return html`<div class="health">
    ${rows.map(([cls, what, detail, link]) => html`<div class="health-row">
      <span class=${`dot ${cls}`}></span>
      <div><div class="what">${what}</div><div class="detail">${detail}</div></div>
      ${link ? html`<a class="btn small quiet" href=${link}>Change</a>` : html`<span></span>`}
    </div>`)}
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
  if (error && !data) return html`<div class="page"><${ErrorNote} error=${error} onRetry=${reload} /></div>`;
  if (!data) return html`<div class="page"><div class="panel panel-body"><${Loading} lines=${6} /></div></div>`;
  const c = data.counts;
  const open = c.gap + c.attempted + c.rejected;
  const testable = data.total - c.not_by_test;
  return html`<div class="page">
    <div class="page-head">
      <div>
        <h1>Traceability of the code base</h1>
        <p class="summary-line">${"Of "}<b>${fmtInt(testable)}</b>${" requirements to be verified by test, "}<b>${fmtInt(c.covered)}</b>${c.covered === 1 ? " is" : " are"}${" cited by a unit test"}${c.accepted ? html`${", "}<b>${fmtInt(c.accepted)}</b>${c.accepted === 1 ? " has" : " have"}${" an accepted generated test"}` : ""}${" and "}<b>${fmtInt(c.generated)}</b>${c.generated === 1 ? " has" : " have"}${" a generated test awaiting review. "}<b>${fmtInt(open)}</b>${open === 1 ? " still has" : " still have"}${" no test evidence."}</p>
      </div>
      <div class="actions">
        <a class="btn" href=${href("requirements", null, { state: "gap" })}>Show open gaps</a>
        <a class="btn primary" href=${href("review")}><${Icon} name="review" />Review tests</a>
      </div>
    </div>

    <section class="panel" aria-labelledby="map-title">
      <div class="panel-head">
        <h2 id="map-title">Requirements by component</h2>
        <span class="sub">One mark per requirement. Select a mark to open it.</span>
      </div>
      <div class="panel-body" style="padding-bottom:0"><${Legend} counts=${c} active=${active} toggle=${toggle} /></div>
      <${TraceMap} modules=${data.modules} active=${active} />
    </section>

    <div class="cols-2">
      <section class="panel" aria-labelledby="needs-title">
        <div class="panel-head"><h2 id="needs-title">Waiting for you</h2></div>
        <div class="panel-body attention">
          <div class="row" style="align-items:flex-end;gap:16px">
            <span class="big">${data.review.pending}</span>
            <span class="ink2">generated tests wait for a review verdict.<br />${data.review.reviewed} reviewed so far.</span>
            <a class="btn primary" style="margin-left:auto" href=${href("review")}>Start reviewing</a>
          </div>
        </div>
        <div class="panel-head" style="border-top:1px solid var(--line)"><h3>Recent agent runs</h3><span class="end"><a class="btn small quiet" href=${href("runs")}>All runs</a></span></div>
        ${data.runs.length ? html`<div class="list-plain">
          ${data.runs.map((r) => html`<a class="run-line" href=${href("runs", r.id)} key=${r.id}>
            <${RunStatus} status=${r.status} />
            <span><span class="t">Run ${r.id}, ${r.req_ids.length} requirement${r.req_ids.length > 1 ? "s" : ""}</span><br /><span class="s">${r.model_label}</span></span>
            <span class="s">${ago(r.created_at)}</span>
          </a>`)}
        </div>` : html`<div class="empty"><p>No runs yet. Open a requirement with no test evidence and generate a test, or select several on the Requirements page.</p>
          <a class="btn" href=${href("requirements", null, { state: "gap" })}>Find gaps</a></div>`}
      </section>
      <section class="panel" aria-labelledby="health-title">
        <div class="panel-head"><h2 id="health-title">Platform</h2><span class="sub">Everything runs on this site</span></div>
        <${Health} status=${status} />
      </section>
    </div>
  </div>`;
}
