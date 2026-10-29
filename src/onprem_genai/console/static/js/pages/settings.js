// Settings: the model server used by agent runs, the reviewer's name, and what the console is connected to.
import { html, useEffect, useState } from "../../vendor/htm-preact-standalone.mjs";
import { useApi, api, toast, Loading, ErrorNote, fmtInt, DEMO } from "../lib.js";

export function Settings({ status }) {
  const [s, error, reload] = useApi("/settings");
  const [form, setForm] = useState(null);
  const [key, setKey] = useState("");
  const [test, setTest] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (s) setForm({ ...s.llm, extra_body: s.llm.extra_body ? JSON.stringify(s.llm.extra_body) : "", reviewer: s.reviewer });
  }, [s]);
  if (error && !s) return html`<div class="container page"><${ErrorNote} error=${error} onRetry=${reload} /></div>`;
  if (!form) return html`<div class="container page"><${Loading} lines=${6} /></div>`;
  const up = (patch) => setForm({ ...form, ...patch });
  const save = async (e) => {
    e && e.preventDefault();
    setBusy(true);
    try {
      const llm = { base_url: form.base_url, model: form.model, label: form.label, temperature: form.temperature, max_tokens: form.max_tokens, extra_body: form.extra_body };
      if (key) llm.api_key = key;
      await api("/settings", { method: "PUT", body: { llm, reviewer: form.reviewer } });
      setKey(""); toast("Settings saved"); reload(); window.dispatchEvent(new Event("oge:changed"));
      setBusy(false);
      return true;
    } catch (err) { toast(err.message, { kind: "bad" }); setBusy(false); return false; }
  };
  const runTest = async () => {
    if (!(await save())) return;
    setTest({ pending: true });
    try { setTest(await api("/settings/test", { method: "POST" })); } catch (err) { setTest({ ok: false, error: err.message }); }
  };
  const clearKey = async () => {
    try { await api("/settings", { method: "PUT", body: { llm: { clear_api_key: true } } }); toast("API key removed"); reload(); }
    catch (err) { toast(err.message, { kind: "bad" }); }
  };
  const ws = status && status.workspace, g = status && status.graph;
  return html`<div class="container page">
    <div class="page-head"><div class="stack"><span class="overline">Console</span><h1>Settings</h1><p class="lede">Where agent runs get their answers, and who signs review verdicts.</p></div></div>
    ${DEMO ? html`<div class="note info"><b>Read-only in this demo.</b><span>On your site, this is where you point agent runs at your model server: llama.cpp, vLLM or any OpenAI-compatible gateway.</span></div>` : null}
    <div class="split">
      <form class="panel" onSubmit=${save} aria-labelledby="llm-title">
        <div class="panel-head"><h2 id="llm-title">Model server</h2><span class="muted">Any OpenAI-compatible server: llama.cpp, vLLM, or a gateway</span></div>
        <div class="panel-body form">
          <div class="field"><label class="usa-label" for="st-url">Server address</label>
            <input id="st-url" class="usa-input mono" type="url" placeholder="http://gpu-server.local:8080" value=${form.base_url} onInput=${(e) => up({ base_url: e.target.value })} />
            <span class="usa-hint">The server root, without /v1. The platform's own servers listen on ports 8080 (llama.cpp) and 8000 (vLLM).</span></div>
          <div class="form-row">
            <div class="field"><label class="usa-label" for="st-model">Model name on the server</label>
              <input id="st-model" class="usa-input mono" value=${form.model} onInput=${(e) => up({ model: e.target.value })} /></div>
            <div class="field"><label class="usa-label" for="st-label">Name shown in reports</label>
              <input id="st-label" class="usa-input" placeholder="Qwen3-Coder-30B-A3B" value=${form.label} onInput=${(e) => up({ label: e.target.value })} /></div>
          </div>
          <div class="field"><label class="usa-label" for="st-key">API key</label>
            <div class="row"><input id="st-key" class="usa-input mono grow" type="password" autocomplete="new-password" placeholder=${form.api_key_set ? "A key is saved; type a new one to replace it" : "Leave empty if the server needs none"} value=${key} onInput=${(e) => setKey(e.target.value)} />
              ${form.api_key_set ? html`<button class="btn plain" type="button" onClick=${clearKey}>Remove key</button>` : null}</div>
            <span class="usa-hint">Stored on this server only and never sent back to a browser.</span></div>
          <div class="form-row">
            <div class="field"><label class="usa-label" for="st-temp">Temperature</label>
              <input id="st-temp" class="usa-input num" type="number" min="0" max="2" step="0.1" value=${form.temperature} onInput=${(e) => up({ temperature: Number(e.target.value) })} /></div>
            <div class="field"><label class="usa-label" for="st-max">Longest answer (tokens)</label>
              <input id="st-max" class="usa-input num" type="number" min="256" max="32768" step="256" value=${form.max_tokens} onInput=${(e) => up({ max_tokens: Number(e.target.value) })} /></div>
          </div>
          <div class="field"><label class="usa-label" for="st-extra">Extra request fields</label>
            <input id="st-extra" class="usa-input mono" placeholder='{"chat_template_kwargs": {"enable_thinking": false}}' value=${form.extra_body} onInput=${(e) => up({ extra_body: e.target.value })} />
            <span class="usa-hint">JSON merged into every request, for server-specific options.</span></div>
          ${test ? html`<div class=${`note ${test.pending ? "info" : test.ok ? "info" : "bad"}`} role="status">
            ${test.pending ? "Sending a test request…" : test.ok ? html`<b>The server answered in ${test.seconds} s.</b><span>Reply: <span class="mono">${test.reply}</span></span>` : html`<b>The test request failed.</b><span>${test.error}</span>`}
          </div>` : null}
          <div class="row"><button class="btn act" type="submit" disabled=${busy || !!DEMO}>Save</button>
            <button class="btn" type="button" disabled=${busy || !form.base_url || !!DEMO} onClick=${runTest}>Save and send a test request</button></div>
        </div>
      </form>
      <div class="stack" style="gap:2rem;align-content:start">
        <form class="panel" onSubmit=${save} aria-labelledby="rev-title">
          <div class="panel-head"><h2 id="rev-title">Reviewer</h2></div>
          <div class="panel-body form">
            <div class="field"><label class="usa-label" for="st-rev">Your name</label>
              <input id="st-rev" class="usa-input" value=${form.reviewer} onInput=${(e) => up({ reviewer: e.target.value })} placeholder="Name shown on review verdicts" />
              <span class="usa-hint">Shared by everyone using this console. Each verdict keeps the name it was saved with.</span></div>
            <div><button class="btn" type="submit" disabled=${busy || !!DEMO}>Save</button></div>
          </div>
        </form>
        <section class="panel" aria-labelledby="sys-title">
          <div class="panel-head"><h2 id="sys-title">Connected to</h2></div>
          <div class="panel-body">
            ${status ? html`<dl class="kv">
              <dt>Knowledge graph</dt><dd>${g.source}, ${fmtInt(g.requirements)} requirements, ${fmtInt(g.tests)} tests, loaded in ${g.load_seconds} s</dd>
              <dt>F´ workspace</dt><dd class="mono">${ws.path || "not configured"}</dd>
              <dt>Runs start from</dt><dd class="mono">${ws.base_commit || "–"}</dd>
              <dt>Agent runs</dt><dd>${ws.ready ? "Available" : ws.problems.join("; ")}</dd>
              <dt>Recorded answers</dt><dd>${status.replay.requirements} requirements</dd>
            </dl>` : html`<${Loading} lines=${4} />`}
          </div>
        </section>
      </div>
    </div>
  </div>`;
}
