// Agent runs: every run with its live step stream, per requirement.
import { html, useEffect, useMemo, useRef, useState } from "../../vendor/htm-preact-standalone.mjs";
import { useApi, api, go, href, toast, RunStatus, ResultTag, Loading, ErrorNote, Icon, ago, duration } from "../lib.js";
import { Timeline } from "../parts.js";

const LIVE = new Set(["queued", "running", "stopping"]);
const RESULT_COLOR = { passed: "var(--ok)", failed: "var(--bad)" };

function RunList({ runs, current }) {
  if (!runs.length) return html`<div class="empty"><h3>No runs yet</h3>
    <p>Runs start from a requirement with no test evidence, or from a selection on the Requirements page.</p>
    <a class="btn" href=${href("requirements", null, { state: "gap,attempted,rejected" })}>Find gaps</a></div>`;
  return html`<div class="run-list">${runs.map((r) => html`<a class="run-item" key=${r.id} href=${href("runs", r.id)} aria-current=${current === r.id}>
    <span class="top"><b>Run ${r.id}</b><${RunStatus} status=${r.status} /><span class="when">${ago(r.created_at)}</span></span>
    <span class="sub">${r.model_label}</span>
    <span class="sub">${r.finished} of ${r.req_ids.length} finished, ${r.passed} verified</span>
  </a>`)}</div>`;
}

function useRunStream(id, run) {
  const [events, setEvents] = useState([]);
  const [status, setStatus] = useState(null);
  const lastSeq = useRef(-1);
  useEffect(() => {
    setEvents([]); setStatus(null); lastSeq.current = -1;
  }, [id]);
  useEffect(() => {
    if (!run || run.id !== id) return undefined;
    // stored events first; the stream then delivers only newer ones
    setEvents(run.events);
    lastSeq.current = run.events.length ? run.events[run.events.length - 1].seq : -1;
    setStatus(run.status);
    if (!LIVE.has(run.status)) return undefined;
    const es = new EventSource(`/api/runs/${id}/events?after=${lastSeq.current}`);
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      if (ev.seq <= lastSeq.current) return;
      lastSeq.current = ev.seq;
      setEvents((xs) => [...xs, ev]);
      if (ev.type === "run") setStatus(ev.status);
      if (ev.type === "result" || ev.type === "run") window.dispatchEvent(new Event("oge:changed"));
      if (ev.type === "run" && ["done", "failed", "cancelled"].includes(ev.status)) es.close();
    };
    es.onerror = () => { /* the browser reconnects with Last-Event-ID */ };
    return () => es.close();
  }, [id, run && run.id]);
  return [events, status];
}

function RunDetail({ id }) {
  const [run, error, reload] = useApi(`/runs/${id}`);
  const [events, liveStatus] = useRunStream(id, run);
  const [open, setOpen] = useState({});
  const status = liveStatus || (run && run.status);
  useEffect(() => { if (run && LIVE.has(run.status) && liveStatus && !LIVE.has(liveStatus)) reload(); }, [liveStatus]);
  const groups = useMemo(() => {
    const by = {};
    for (const ev of events) if (ev.req_id) (by[ev.req_id] = by[ev.req_id] || []).push(ev);
    return by;
  }, [events]);
  if (error && !run) return html`<div class="panel panel-body"><${ErrorNote} error=${error} onRetry=${reload} /></div>`;
  if (!run) return html`<div class="panel panel-body"><${Loading} lines=${8} /></div>`;
  const results = {};
  for (const ev of events) if (ev.type === "result") results[ev.req_id] = ev;
  const done = Object.keys(results).length;
  const verified = Object.values(results).filter((r) => r.status === "passed").length;
  const current = LIVE.has(status) ? run.req_ids.find((r) => !results[r] && groups[r]) : null;
  const runErr = [...events].reverse().find((e) => e.type === "run" && e.error);
  const started = run.started_at, finished = run.finished_at;
  const stop = async () => {
    try { const r = await api(`/runs/${id}/stop`, { method: "POST" }); toast(r.status === "stopping" ? "The run stops after the current requirement." : "Run stopped."); }
    catch (e) { toast(e.message, { kind: "bad" }); }
  };
  return html`<section class="panel" aria-labelledby="run-title">
    <div class="panel-head" style="flex-wrap:wrap">
      <div class="stack" style="gap:4px">
        <h2 id="run-title">Run ${run.id}</h2>
        <span class="sub">${run.model_label}</span>
      </div>
      <div class="end">
        <${RunStatus} status=${status} />
        ${LIVE.has(status) && status !== "stopping" ? html`<button class="btn small" type="button" onClick=${stop}><${Icon} name="stop" size=${14} />${status === "queued" ? "Cancel" : "Stop after this requirement"}</button>` : null}
      </div>
    </div>
    <div class="panel-body stack" style="gap:14px">
      <div class="facts">
        <span><b>${done}</b> of <b>${run.req_ids.length}</b> finished</span>
        <span><b>${verified}</b> verified</span>
        ${started ? html`<span>${finished ? "Took" : "Running for"} <b>${duration((finished || Date.now() / 1000) - started)}</b></span>` : null}
        ${run.branch ? html`<span class="row" style="gap:6px"><${Icon} name="branch" size=${14} /><b class="mono">${run.branch}</b></span>` : null}
        <span>Attempts <b>${run.options.attempts}</b>, mutants <b>${run.options.mutants}</b></span>
      </div>
      <div class="progress" aria-hidden="true">${run.req_ids.map((r) => html`<i key=${r} style=${`flex:1;margin-right:2px;background:${results[r] ? RESULT_COLOR[results[r].status] || "var(--muted)" : r === current ? "var(--accent)" : "var(--line-2)"}`}></i>`)}</div>
      ${runErr ? html`<div class="callout bad"><b>The run stopped with an error.</b><span>${runErr.error}</span></div>` : null}
      ${status === "queued" ? html`<div class="callout info">Waiting for the run in progress to finish. Runs share one F´ workspace, so they go one at a time.</div>` : null}
    </div>
    ${run.req_ids.map((r) => {
      const evs = groups[r] || [];
      const res = results[r];
      const prep = evs.find((e) => e.node === "prepare");
      const isOpen = open[r] !== undefined ? open[r] : r === current || (run.req_ids.length <= 3 && evs.length > 0);
      return html`<div class="req-run" key=${r}>
        <div class="req-run-head" role="button" tabindex="0" aria-expanded=${isOpen}
          onClick=${() => setOpen({ ...open, [r]: !isOpen })} onKeyDown=${(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setOpen({ ...open, [r]: !isOpen }))}>
          ${res ? html`<${ResultTag} status=${res.status} />` : r === current ? html`<span class="tag accent">In progress</span>` : html`<span class="tag">Waiting</span>`}
          <div style="min-width:0"><div class="rid">${r}</div><div class="rtext">${prep && prep.requirement ? prep.requirement.text : ""}</div></div>
          <span class="row" style="gap:12px">
            ${res ? html`<span class="muted num">${res.attempts} attempt${res.attempts === 1 ? "" : "s"}, ${duration(res.wall_seconds)}</span>` : null}
            ${res && res.status === "passed" ? html`<a class="btn small" href=${href("review", res.result_id)} onClick=${(e) => e.stopPropagation()}>Review</a>` : null}
            <a class="btn small quiet" href=${href("requirements", null, { id: r })} onClick=${(e) => e.stopPropagation()}>Requirement</a>
          </span>
        </div>
        ${isOpen && evs.length ? html`<${Timeline} events=${evs.filter((e) => e.type === "step")} live=${r === current} />` : null}
        ${isOpen && !evs.length ? html`<div class="panel-body muted">${LIVE.has(status) ? "Not started yet." : "This requirement was not reached."}</div>` : null}
      </div>`;
    })}
  </section>`;
}

export function Runs({ route }) {
  const id = route.arg ? Number(route.arg) : null;
  const [runs, error, reload] = useApi("/runs");
  useEffect(() => {
    const t = setInterval(reload, 5000);
    window.addEventListener("oge:changed", reload);
    return () => { clearInterval(t); window.removeEventListener("oge:changed", reload); };
  }, [reload]);
  useEffect(() => { if (!id && runs && runs.length && window.innerWidth > 900) go("runs", runs[0].id, null, { replace: true }); }, [runs, id]);
  return html`<div class="page">
    <div class="page-head"><div><h1>Agent runs</h1>
      <p class="lede">Each run works through its requirements one at a time on its own branch. Steps appear as they happen.</p></div>
      <div class="actions"><a class="btn primary" href=${href("requirements", null, { state: "gap,attempted,rejected" })}><${Icon} name="play" size=${15} />New run</a></div>
    </div>
    <div class="runs-layout">
      <section class="panel" aria-label="Runs">${error && !runs ? html`<div class="panel-body"><${ErrorNote} error=${error} onRetry=${reload} /></div>` : runs ? html`<${RunList} runs=${runs} current=${id} />` : html`<div class="panel-body"><${Loading} /></div>`}</section>
      ${id ? html`<${RunDetail} id=${id} key=${id} />` : runs && runs.length ? null : html`<div></div>`}
    </div>
  </div>`;
}
