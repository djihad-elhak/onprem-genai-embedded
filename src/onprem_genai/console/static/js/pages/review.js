// Review: a queue of verified generated tests; an engineer judges each one against its requirement.
import { html, useEffect, useMemo, useState } from "../../vendor/htm-preact-standalone.mjs";
import { useApi, api, go, href, toast, Code, Loading, ErrorNote, ArrowLink, duration, short, useKey, DEMO } from "../lib.js";
import { MutantTable, History, Coverage } from "../parts.js";

const VERDICTS = [
  ["relevant", "Relevant", "Exercises the stated behaviour and checks its outcome.", "1"],
  ["partial", "Partial", "Right idea, but covers only part of the requirement.", "2"],
  ["not_relevant", "Not relevant", "Does not verify what the requirement states.", "3"],
];
const FILTERS = [["pending", "To review"], ["reviewed", "Reviewed"], ["all", "All"]];

/** The test as written: the added lines of the diff, per file. */
function addedCode(diff) {
  const files = [];
  let cur = null;
  for (const line of String(diff || "").split("\n")) {
    const f = line.match(/^\+\+\+ b\/(.+)$/);
    if (f) { cur = { file: f[1], lines: [] }; files.push(cur); continue; }
    if (cur && line.startsWith("+") && !line.startsWith("+++")) cur.lines.push(line.slice(1));
  }
  return files.filter((f) => f.lines.some((l) => l.trim()));
}

function Detail({ id, onSaved, reviewer }) {
  const [r, error, reload] = useApi(`/reviews/${id}`);
  const [note, setNote] = useState("");
  const [full, setFull] = useState(false);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (r) setNote(r.note || ""); }, [r && r.id]);
  const save = async (verdict) => {
    setSaving(true);
    try {
      await api(`/reviews/${id}`, { method: "PUT", body: { verdict, note } });
      toast(verdict ? `Marked ${verdict.replace("_", " ")}` : "Verdict cleared");
      window.dispatchEvent(new Event("oge:changed"));
      onSaved(verdict);
      reload();
    } catch (e) { toast(e.message, { kind: "bad" }); }
    setSaving(false);
  };
  useKey((e) => {
    const v = VERDICTS.find((x) => x[3] === e.key);
    if (v && r && !saving) { e.preventDefault(); save(v[0]); }
  }, [r, note, saving]);
  if (error && !r) return html`<${ErrorNote} error=${error} onRetry=${reload} />`;
  if (!r) return html`<div class="panel panel-body"><${Loading} lines=${10} /></div>`;
  const rec = r.record || {};
  const m = rec.metrics || {};
  const code = addedCode(rec.diff);
  return html`<section class="panel" aria-labelledby="rv-title">
    <div class="panel-head" style="align-items:flex-start">
      <div class="stack" style="gap:0.625rem;min-width:0;flex:1">
        <span class="row"><h2 class="mono" id="rv-title"><a href=${href("requirements", null, { id: r.req_id })}>${r.req_id}</a></h2><span class="tag mod">${r.module}</span></span>
        <p class="req-text">${r.requirement ? r.requirement.text : ""}</p>
      </div>
    </div>
    <div class="panel-body stack" style="gap:2rem">
      <div class="facts">
        <span>Written by <b>${r.model_label}</b></span>
        <span>${r.source === "console" ? html`From <a href=${href("runs", r.run_id)}>run ${r.run_id}</a>` : html`From <b>${r.source}</b>`}</span>
        <span><b>${r.attempts}</b> attempt${r.attempts === 1 ? "" : "s"}, <b>${duration(r.wall_seconds)}</b></span>
        ${r.commit ? html`<span>Commit <b>${short(r.commit)}</b></span>` : null}
        ${r.mutants_valid ? html`<span>Caught <b>${r.mutants_killed} of ${r.mutants_valid}</b> seeded bugs</span>` : null}
      </div>
      ${r.ai_verdict ? html`<div class="suggestion"><span class="overline">AI pre-review, not a human verdict</span><span><b>${r.ai_verdict.replace("_", " ")}</b>: ${r.ai_note}</span></div>` : null}

      <div class="section">
        <div class="row"><h3 class="grow">The generated test</h3>
          <div class="seg" role="group" aria-label="Code view">
            <button type="button" aria-pressed=${!full} onClick=${() => setFull(false)}>Test code</button>
            <button type="button" aria-pressed=${full} onClick=${() => setFull(true)}>Full diff</button>
          </div></div>
        ${full ? html`<${Code} title="git diff" text=${rec.diff || ""} kind="diff" />`
          : code.length ? code.map((f) => html`<${Code} key=${f.file} title=${f.file} text=${f.lines.join("\n").replace(/^\n+|\n+$/g, "")} />`)
          : html`<div class="empty-line">No diff stored for this result.</div>`}
      </div>

      <div class="section"><h3>Does it catch bugs?</h3>
        <p>Lines of the implementation that the test executes were mutated, rebuilt and re-run against this test alone.</p>
        <${MutantTable} mutation=${m.mutation} />
        <${Coverage} metrics=${m} />
      </div>

      <div class="section"><h3>How it got there</h3><${History} record=${rec} /></div>

      <div class="section" id="verdict">
        <h3>Your verdict</h3>
        <div class="verdicts" role="group" aria-label="Verdict">
          ${VERDICTS.map(([key, label, help, k]) => html`<button type="button" class=${`verdict v-${key}`} aria-pressed=${r.verdict === key} disabled=${saving} onClick=${() => save(key)}>
            <b>${label}<kbd>${k}</kbd></b><span>${help}</span></button>`)}
        </div>
        <div class="field"><label class="usa-label" for="note">Note for the team <span class="muted" style="font-weight:400">(optional)</span></label>
          <textarea id="note" class="usa-textarea" value=${note} onInput=${(e) => setNote(e.target.value)} placeholder="What is missing, or what convinced you"></textarea></div>
        <div class="row">
          <span class="muted">${r.verdict ? `Saved${r.reviewer ? ` by ${r.reviewer}` : ""}.` : DEMO ? "In this demo, verdicts are kept in your browser only." : reviewer ? `Verdicts are signed ${reviewer}.` : html`Add your name in <a href="#/settings">Settings</a> to sign verdicts.`}</span>
          <span class="grow"></span>
          ${r.verdict ? html`<button class="btn plain small" type="button" onClick=${() => save(null)}>Clear verdict</button>` : null}
          ${r.verdict ? html`<button class="btn small" type="button" disabled=${saving} onClick=${() => save(r.verdict)}>Save note</button>` : null}
        </div>
      </div>
    </div>
  </section>`;
}

export function Review({ route }) {
  const filter = route.params.get("filter") || "pending";
  const id = route.arg ? Number(route.arg) : null;
  const [items, error, reload] = useApi(`/reviews?filter=${filter}`);
  const [settings] = useApi("/settings");
  useEffect(() => {
    window.addEventListener("oge:changed", reload);
    return () => window.removeEventListener("oge:changed", reload);
  }, [reload]);
  useEffect(() => { if (!id && items && items.length && window.innerWidth > 900) go("review", items[0].id, { filter }, { replace: true }); }, [items, id]);
  const idx = useMemo(() => (items ? items.findIndex((x) => x.id === id) : -1), [items, id]);
  const move = (d) => { if (items && items.length) { const n = items[Math.max(0, Math.min(items.length - 1, (idx < 0 ? 0 : idx) + d))]; go("review", n.id, { filter }); } };
  useKey((e) => { if (e.key === "j") move(1); if (e.key === "k") move(-1); }, [items, idx]);
  const onSaved = (verdict) => {
    if (filter !== "pending" || !verdict || !items) return;
    const rest = items.filter((x) => x.id !== id);
    const next = rest[Math.min(Math.max(idx, 0), rest.length - 1)];
    setTimeout(() => (next ? go("review", next.id, { filter }) : go("review", null, { filter })), 250);
  };
  return html`<div class="container page">
    <div class="page-head"><div class="stack"><span class="overline">Test generation</span><h1>Review generated tests</h1>
      <p class="lede">A generated test counts as evidence only once a person agrees it verifies its requirement. Use <kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd> for verdicts and <kbd>j</kbd> <kbd>k</kbd> to move through the queue.</p></div>
      <div class="actions"><${ArrowLink} href=${DEMO ? `${DEMO}review-sheet.md` : "/api/reviews/export"} download="review-sheet.md">Download the review sheet<//></div>
    </div>
    <div class="review-layout">
      <section class="queue" aria-label="Review queue">
        <div class="toolbar" style="padding-top:0"><div class="seg" role="group" aria-label="Show">${FILTERS.map(([k, label]) => html`<button type="button" key=${k} aria-pressed=${filter === k} onClick=${() => go("review", null, { filter: k })}>${label}</button>`)}</div></div>
        <div class="queue-list">
          ${error && !items ? html`<${ErrorNote} error=${error} onRetry=${reload} />` : null}
          ${!items ? html`<div class="panel-body"><${Loading} /></div>` : !items.length ? html`<div class="empty"><h3>${filter === "pending" ? "Nothing to review" : "No reviews yet"}</h3>
            <p>${filter === "pending" ? "Every generated test has a verdict. New ones appear here when an agent run verifies a requirement." : "Verdicts you give appear here."}</p></div>` :
            items.map((x) => html`<a class="queue-item" key=${x.id} href=${href("review", x.id, { filter })} aria-current=${x.id === id}>
              <span class="top"><span class="rid">${x.req_id}</span>${x.verdict ? html`<span class=${`tag ${x.verdict === "relevant" ? "ok" : x.verdict === "partial" ? "warn" : "bad"}`}>${x.verdict.replace("_", " ")}</span>` : null}<span class="who">${x.model_label}</span></span>
              <span class="txt">${x.text}</span>
            </a>`)}
        </div>
      </section>
      ${id ? html`<${Detail} id=${id} key=${id} onSaved=${onSaved} reviewer=${settings && settings.reviewer} />` : html`<div class="panel panel-body empty"><p>${items && items.length ? "Select a test to review." : "The queue is empty."}</p></div>`}
    </div>
  </div>`;
}
