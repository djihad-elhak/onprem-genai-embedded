// Code search: hybrid search over code, tests, requirements and design documents, with a symbol view.
import { html, useEffect, useState } from "../../vendor/htm-preact-standalone.mjs";
import { useApi, go, href, Code, Loading, ErrorNote, Icon, ArrowLink, DEMO } from "../lib.js";

const KINDS = [
  ["", "Everything"],
  ["Function", "Code"],
  ["TestCase", "Tests"],
  ["Requirement", "Requirements"],
  ["DocChunk", "Design documents"],
];
const KIND_LABEL = { Function: "Function", TestCase: "Test", Requirement: "Requirement", DocChunk: "Design document", Class: "Class" };
const EXAMPLES = ["retry sending when the driver asks for a retry", "parameter file load failure", "SVC-COMSTUB-004", "frame context restored on return"];

function Symbol({ id, onOpen }) {
  const [n, error] = useApi(`/nodes/${encodeURIComponent(id)}`);
  if (error) return html`<div class="panel-body"><${ErrorNote} error=${error} /></div>`;
  if (!n) return html`<div class="panel-body"><${Loading} lines=${10} /></div>`;
  const props = n.props || {};
  const text = props.text || props.doc || "";
  const isReq = n.kind === "Requirement";
  const rel = (items, label) => items && items.length ? html`<div class="section"><h3>${label}<span class="meta">${items.length}</span></h3>
    <div class="rel-list">${items.map((x) => html`<button type="button" key=${x.id} title=${x.location} onClick=${() => onOpen(x.id)}>${x.title.split("::").slice(-2).join("::")}</button>`)}</div></div>` : null;
  return html`<div class="panel-head"><div class="stack" style="gap:0.375rem;min-width:0">
      <span class="overline">${KIND_LABEL[n.kind] || n.kind}</span>
      <h2 class="mono" style="font-size:1rem;overflow-wrap:anywhere">${n.title}</h2>
      <span class="meta">${n.location}</span>
    </div></div>
    <div class="panel-body stack" style="gap:1.5rem">
      ${isReq ? html`<p class="req-text">${props.text}</p><${ArrowLink} href=${href("requirements", null, { id: props.req_id })}>Open the requirement<//>`
        : text ? html`<${Code} title=${n.location} text=${text} kind=${n.kind === "DocChunk" ? "plain" : "cpp"} wrap=${n.kind === "DocChunk"} />` : html`<div class="empty-line">No source text stored for this symbol.</div>`}
      ${rel(n.callers, "Called by")}
      ${rel(n.callees, "Calls")}
    </div>`;
}

export function Search({ route }) {
  const p = route.params;
  const q = p.get("q") || "";
  const kind = p.get("kind") || "";
  const node = p.get("node");
  const [text, setText] = useState(q);
  useEffect(() => setText(q), [q]);
  const [hits, error, reload] = useApi(q ? `/search?q=${encodeURIComponent(q)}&k=30${kind ? `&kind=${kind}` : ""}` : null);
  const set = (patch, replace = false) => go("search", null, { q, kind, node, ...patch }, { replace });
  useEffect(() => { if (hits && hits.length && !node && window.innerWidth > 1180) set({ node: hits[0].id }, true); }, [hits]);
  const submit = (e) => { e.preventDefault(); if (text.trim()) set({ q: text.trim(), node: "" }); };

  return html`<div class="container page">
    <div class="page-head"><div class="stack"><span class="overline">Knowledge graph</span><h1>Code search</h1>
      <p class="lede">Searches functions, unit tests, requirements and design documents by meaning and by name, the same way the assistants and the agent do over MCP.</p></div></div>
    <form class="stack" role="search" onSubmit=${submit}>
      <div class="search-big"><${Icon} name="search" />
        <label class="sr-only" for="q">Search the code base</label>
        <input id="q" type="search" value=${text} onInput=${(e) => setText(e.target.value)} placeholder="Describe a behaviour or type a name" autofocus /></div>
      <div class="seg" role="group" aria-label="Kind">${KINDS.map(([k, label]) => html`<button type="button" key=${k} aria-pressed=${kind === k} onClick=${() => set({ kind: k, node: "" })}>${label}</button>`)}</div>
    </form>
    ${DEMO && q ? html`<div class="row"><span class="muted">The demo answers these searches:</span>${EXAMPLES.map((ex) => html`<button class="btn small" type="button" key=${ex} onClick=${() => go("search", null, { q: ex, kind })}>${ex}</button>`)}</div>` : null}
    ${!q ? html`<div class="empty"><h2>Try a question about the code</h2>
      <p>Results combine keyword and semantic matching, ranked within the component they belong to.</p>
      <div class="row">${EXAMPLES.map((ex) => html`<button class="btn small" type="button" key=${ex} onClick=${() => go("search", null, { q: ex })}>${ex}</button>`)}</div></div>` : html`
    <div class="search-layout">
      <section class="hits" aria-label="Results">
        ${error ? (DEMO ? html`<div class="note info">${error.message}</div>` : html`<${ErrorNote} error=${error} onRetry=${reload} />`) : null}
        ${error ? null : !hits ? html`<div class="panel-body"><${Loading} lines=${8} /></div>` : !hits.length ? html`<div class="empty"><h2>Nothing found</h2><p>Use other words, or search everything instead of one kind.</p></div>` :
          hits.map((h) => html`<div class="hit" key=${h.id} role="button" tabindex="0" aria-current=${node === h.id}
            onClick=${() => set({ node: h.id })} onKeyDown=${(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), set({ node: h.id }))}>
            <div class="top"><span class="tag">${KIND_LABEL[h.kind] || h.kind}</span><span class="title">${h.title}</span></div>
            <span class="meta">${h.location}</span>
            <pre>${(h.snippet || "").split("\n").slice(1).filter((l) => l.trim() && !l.startsWith("// ---")).slice(0, 3).join("\n")}</pre>
          </div>`)}
      </section>
      <section class="panel symbol-panel" aria-label="Selected result">
        ${node ? html`<${Symbol} id=${node} key=${node} onOpen=${(id) => set({ node: id })} />` : html`<div class="panel-body empty"><p>Select a result to see its source, callers and callees.</p></div>`}
      </section>
    </div>`}
  </div>`;
}
