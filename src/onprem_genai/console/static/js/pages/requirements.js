// Requirements: browse every requirement by component and state, open one to see its evidence, start the agent.
import { html, useEffect, useMemo, useRef, useState } from "../../vendor/htm-preact-standalone.mjs";
import { useApi, api, go, href, State, STATES, STATE_ORDER, ResultTag, Loading, ErrorNote, Icon, fmtInt, ago, duration, useDialog, useKey } from "../lib.js";
import { RunDialog } from "../run-dialog.js";

const FILTERS = [
  ["", "All"],
  ["gap,attempted,rejected", "Open gaps"],
  ["generated", "Awaiting review"],
  ["covered,accepted", "Have a test"],
  ["not_by_test", "Verified otherwise"],
];

function ModuleList({ modules, current, onPick, total }) {
  return html`<nav class="panel modlist" aria-label="Components">
    <button type="button" aria-pressed=${!current} onClick=${() => onPick("")}><span>All components</span><span class="n">${fmtInt(total)}</span></button>
    ${modules.map((m) => html`<div key=${m.module}>
      <button type="button" aria-pressed=${current === m.module} onClick=${() => onPick(m.module)} title=${m.module}>
        <span>${m.module}</span><span class="n">${m.total}</span>
      </button>
      ${current === m.module ? html`<div class="mini" aria-hidden="true">${STATE_ORDER.filter((s) => m.counts[s]).map((s) =>
        html`<i class=${`s-${s}`} style=${`width:${(100 * m.counts[s]) / m.total}%`}></i>`)}</div>` : null}
    </div>`)}
  </nav>`;
}

function Evidence({ items, empty, render }) {
  if (!items || !items.length) return html`<div class="empty-inline">${empty}</div>`;
  return html`<div class="evidence">${items.map(render)}</div>`;
}

function Drawer({ id, status, onClose, onRun }) {
  const ref = useRef(null);
  useDialog(ref, onClose);
  const [data, error, reload] = useApi(`/requirements/${encodeURIComponent(id)}`);
  const t = data && data.trace;
  const agent = data && data.agent;
  let action = null;
  if (data) {
    if (!agent.eligible) action = html`<span class="muted">${data.base === "covered" ? "A test already cites this requirement." : "This requirement is not verified by test."}</span>`;
    else if (agent.support) action = html`<span class="muted">The agent cannot work on this component: ${agent.support}.</span>`;
    else action = html`<button class="btn primary" type="button" onClick=${() => onRun(data)}><${Icon} name="play" size=${15} />Generate a test</button>`;
  }
  return html`<div class="scrim" onClick=${onClose}></div>
  <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title" ref=${ref}>
    <div class="drawer-head">
      <div class="stack" style="gap:6px;flex:1;min-width:0">
        <span class="id" id="drawer-title">${id}</span>
        ${data ? html`<div class="row"><${State} s=${data.state} big=${true} /><span class="tag">${data.module}</span></div>` : null}
      </div>
      <button class="btn quiet small" type="button" onClick=${onClose} aria-label="Close" data-autofocus><${Icon} name="x" size=${16} /></button>
    </div>
    <div class="drawer-body">
      ${error ? html`<${ErrorNote} error=${error} onRetry=${reload} />` : null}
      ${!data ? html`<${Loading} lines=${8} />` : html`
        <p class="req-text">${data.text}</p>
        <dl class="kv">
          ${data.rationale ? html`<dt>Rationale</dt><dd>${data.rationale}</dd>` : null}
          <dt>Verification</dt><dd>${data.verification || "not stated"}</dd>
          <dt>Defined in</dt><dd class="mono">${data.file}${data.line ? `:${data.line}` : ""}</dd>
        </dl>
        <section class="section">
          <h3>Tests that cite it<span class="muted">${t.explicit_tests.length}</span></h3>
          <${Evidence} items=${t.explicit_tests} empty="No test carries this requirement's tag." render=${(x) => html`<div key=${x.id}>
            <span class="t">${x.title}</span><span class="s">${x.location}</span></div>`} />
        </section>
        ${data.results.length ? html`<section class="section">
          <h3>Agent results<span class="muted">${data.results.length}</span></h3>
          <div class="evidence">${data.results.map((r) => html`<div key=${r.id}>
            <span class="row" style="gap:8px"><${ResultTag} status=${r.status} /><b>${r.model_label}</b><span class="muted">${r.source === "console" ? `run ${r.run_id}` : r.source}</span></span>
            <span class="s">${r.attempts} attempt${r.attempts === 1 ? "" : "s"}, ${duration(r.wall_seconds)}${r.mutants_valid ? `, ${r.mutants_killed}/${r.mutants_valid} mutants killed` : ""}
              ${r.verdict ? html`<span class="tag ok">reviewed: ${r.verdict.replace("_", " ")}</span>` : null}
              ${r.status === "passed" ? html`<a href=${href("review", r.id)}>${r.verdict ? "Open review" : "Review it"}</a>` : r.run_id ? html`<a href=${href("runs", r.run_id)}>Open run</a>` : null}</span>
          </div>`)}</div>
        </section>` : null}
        <section class="section">
          <h3>Candidate tests<span class="muted">ranked by the traceability model</span></h3>
          <${Evidence} items=${t.suggested_tests} empty="No candidate tests." render=${(x) => html`<div key=${x.id}>
            <span class="t">${x.title.split("::").slice(-1)[0]}</span>
            <span class="s"><span>${x.location}</span><span>${x.graph_relation === "same-module" ? "same component" : x.graph_relation === "calls-into-module" ? "calls into the component" : "other component"}</span>
              <span title="Text similarity"><span class="bar"><i style=${`width:${Math.round(100 * Math.max(0, Math.min(1, x.text_similarity)))}%`}></i></span></span>
              <a href=${href("search", null, { node: x.id, q: x.title.split("::").slice(-1)[0] })}>View code</a></span>
          </div>`} />
        </section>
        <section class="section">
          <h3>Related implementation</h3>
          <${Evidence} items=${t.related_code} empty="No related functions found." render=${(x) => html`<div key=${x.id}>
            <span class="t">${x.title}</span><span class="s"><span>${x.location}</span><a href=${href("search", null, { node: x.id, q: x.title.split("::").slice(-1)[0] })}>View code</a></span></div>`} />
        </section>`}
    </div>
    <div class="drawer-foot">${action}</div>
  </aside>`;
}

export function Requirements({ route, status }) {
  const p = route.params;
  const module = p.get("module") || "";
  const stateFilter = p.get("state") || "";
  const openId = p.get("id");
  const [q, setQ] = useState(p.get("q") || "");
  const [mods] = useApi("/modules");
  const [rows, error, reload] = useApi(`/requirements${module ? `?module=${encodeURIComponent(module)}` : ""}`);
  const [selected, setSelected] = useState(new Set());
  const [dialog, setDialog] = useState(null);
  const set = (patch) => go("requirements", null, { module, state: stateFilter, q, id: openId, ...patch }, { replace: true });

  useEffect(() => { setSelected(new Set()); }, [module]);
  useEffect(() => {
    const on = () => reload();
    window.addEventListener("oge:changed", on);
    return () => window.removeEventListener("oge:changed", on);
  }, [reload]);

  const shown = useMemo(() => {
    if (!rows) return [];
    const wanted = stateFilter ? new Set(stateFilter.split(",")) : null;
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    return rows.filter((r) => (!wanted || wanted.has(r.state)) && terms.every((t) => `${r.req_id} ${r.text}`.toLowerCase().includes(t)));
  }, [rows, stateFilter, q]);
  const counts = useMemo(() => {
    const c = {};
    for (const [key] of FILTERS) c[key] = rows ? (key ? rows.filter((r) => key.split(",").includes(r.state)).length : rows.length) : 0;
    return c;
  }, [rows]);
  const selectable = shown.filter((r) => r.agent_ready);
  const allSelected = selectable.length > 0 && selectable.every((r) => selected.has(r.req_id));
  const toggle = (id) => { const n = new Set(selected); n.has(id) ? n.delete(id) : n.add(id); setSelected(n); };
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(selectable.map((r) => r.req_id)));
  const total = mods ? mods.reduce((a, m) => a + m.total, 0) : 0;
  useKey((e) => { if (e.key === "Escape" && selected.size) setSelected(new Set()); }, [selected]);

  return html`<div class="page">
    <div class="page-head">
      <div><h1>${module || "Requirements"}</h1>
        <p class="lede">${module ? "Requirements allocated to this component and the evidence that verifies them." : "Every requirement of the design documents, with the evidence that verifies it."}</p></div>
    </div>
    <div class="req-layout">
      ${mods ? html`<${ModuleList} modules=${mods} current=${module} total=${total} onPick=${(m) => go("requirements", null, { module: m, state: stateFilter })} />` : html`<div class="panel panel-body"><${Loading} /></div>`}
      <section class="panel" aria-label="Requirement list">
        <div class="toolbar">
          <input class="input" type="search" placeholder="Filter by ID or text" aria-label="Filter requirements" value=${q}
            onInput=${(e) => setQ(e.target.value)} />
          <div class="seg" role="group" aria-label="State">
            ${FILTERS.map(([key, label]) => html`<button type="button" aria-pressed=${stateFilter === key} onClick=${() => set({ state: key })}>${label}<span class="n">${counts[key]}</span></button>`)}
          </div>
        </div>
        ${error ? html`<div class="panel-body"><${ErrorNote} error=${error} onRetry=${reload} /></div>` : null}
        ${!rows ? html`<div class="panel-body"><${Loading} lines=${8} /></div>` : shown.length === 0 ? html`<div class="empty">
          <h3>No requirement matches</h3><p>Change the filter or the component to see more.</p>
          <button class="btn" type="button" onClick=${() => { setQ(""); set({ state: "", q: "" }); }}>Clear filters</button></div>` : html`
        <div class="table-wrap">
          <table class="grid">
            <thead><tr>
              <th class="sel"><label class="check" title="Select every gap the agent can work on"><input type="checkbox" checked=${allSelected} disabled=${!selectable.length} onChange=${toggleAll} aria-label="Select all gaps the agent can work on" /></label></th>
              <th>ID</th><th>Requirement</th>${module ? null : html`<th>Component</th>`}<th>State</th>
            </tr></thead>
            <tbody>
              ${shown.map((r) => html`<tr key=${r.req_id} aria-selected=${openId === r.req_id} onClick=${() => set({ id: r.req_id })}>
                <td class="sel" onClick=${(e) => e.stopPropagation()}>${r.agent_ready ? html`<label class="check"><input type="checkbox" checked=${selected.has(r.req_id)} onChange=${() => toggle(r.req_id)} aria-label=${`Select ${r.req_id}`} /></label>` : null}</td>
                <td class="id"><a href=${href("requirements", null, { module, state: stateFilter, id: r.req_id })} onClick=${(e) => e.stopPropagation()}>${r.req_id}</a></td>
                <td class="text">${r.text}</td>
                ${module ? null : html`<td class="mono muted">${r.module}</td>`}
                <td><${State} s=${r.state} /></td>
              </tr>`)}
            </tbody>
          </table>
        </div>`}
      </section>
    </div>
    ${selected.size ? html`<div class="selection-bar" role="region" aria-label="Selection">
      <span>${selected.size} selected</span>
      <button class="btn quiet small" type="button" onClick=${() => setSelected(new Set())}>Clear</button>
      <button class="btn primary" type="button" onClick=${() => setDialog(rows.filter((r) => selected.has(r.req_id)))}><${Icon} name="play" size=${15} />Generate tests</button>
    </div>` : null}
    ${openId ? html`<${Drawer} id=${openId} status=${status} onClose=${() => set({ id: "" })} onRun=${(d) => setDialog([{ req_id: d.req_id, replay: d.agent.replay }])} />` : null}
    ${dialog ? html`<${RunDialog} reqs=${dialog} status=${status} onClose=${() => setDialog(null)} />` : null}
  </div>`;
}
