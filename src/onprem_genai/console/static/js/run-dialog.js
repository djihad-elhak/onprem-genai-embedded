// Dialog that starts an agent run on chosen requirements, with the live model server or recorded answers.
import { html, useRef, useState, api, go, toast, useDialog, Icon } from "./lib.js";

function Stepper({ id, value, min, max, onChange, label }) {
  return html`<div class="stepper" role="group" aria-labelledby=${id}>
    <button type="button" aria-label=${`Fewer ${label}`} onClick=${() => onChange(Math.max(min, value - 1))} disabled=${value <= min}>−</button>
    <output aria-live="polite">${value}</output>
    <button type="button" aria-label=${`More ${label}`} onClick=${() => onChange(Math.min(max, value + 1))} disabled=${value >= max}>+</button>
  </div>`;
}

export function RunDialog({ reqs, status, onClose }) {
  const ref = useRef(null);
  useDialog(ref, onClose);
  const [items, setItems] = useState(reqs);
  const llm = status && status.llm;
  const replayable = items.filter((r) => r.replay).length;
  const [kind, setKind] = useState(llm && llm.configured ? "endpoint" : "replay");
  const [attempts, setAttempts] = useState(3);
  const [mutants, setMutants] = useState(4);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const ready = status && status.workspace && status.workspace.ready;
  const replayOk = replayable === items.length && items.length > 0;
  const canStart = ready && items.length > 0 && (kind === "endpoint" ? llm && llm.configured : replayOk) && !busy;

  const start = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api("/runs", { method: "POST", body: { req_ids: items.map((x) => x.req_id), model_kind: kind, attempts, mutants } });
      toast(`Run ${r.id} started`, { link: { href: `#/runs/${r.id}`, text: "Watch" } });
      window.dispatchEvent(new Event("oge:changed"));
      onClose();
      go("runs", r.id);
    } catch (e) { setErr(e.message); setBusy(false); }
  };

  return html`<div class="scrim" onClick=${onClose}></div>
  <div class="modal" role="dialog" aria-modal="true" aria-labelledby="run-title" ref=${ref}>
    <div class="modal-head">
      <span class="overline">Agent run</span>
      <h2 id="run-title">Generate ${items.length === 1 ? "a test" : `tests for ${items.length} requirements`}</h2>
      <p>The agent writes one unit test per requirement, builds and runs it in the F´ workspace, repairs it from the
        compiler and test output, and commits each passing test on a review branch. Nothing reaches the main branch.</p>
    </div>
    <div class="modal-body">
      ${!ready ? html`<div class="note bad"><b>Agent runs are not available on this server.</b>
        <span>${(status && status.workspace.problems.join("; ")) || "The F´ workspace is not ready."}</span></div>` : null}
      <div class="field">
        <span class="usa-label">Requirements</span>
        <div class="chips">${items.map((r) => html`<span class="chip" key=${r.req_id}>${r.req_id}
          ${items.length > 1 ? html`<button type="button" aria-label=${`Remove ${r.req_id}`} onClick=${() => setItems(items.filter((x) => x !== r))}>×</button>` : null}</span>`)}</div>
      </div>
      <fieldset class="field" style="border:0;padding:0;margin:0">
        <legend class="usa-label" style="margin-bottom:0.5rem">Answers from</legend>
        <div class="tiles">
          <label class="tile">
            <input type="radio" name="model" value="endpoint" checked=${kind === "endpoint"} disabled=${!(llm && llm.configured)} onChange=${() => setKind("endpoint")} />
            <b>${llm && llm.configured ? llm.label || llm.model : "Model server"}</b>
            <span>${llm && llm.configured ? `Live answers from ${llm.base_url}.` : html`No model server is set. <a href="#/settings" onClick=${onClose}>Set one in Settings</a>.`}</span>
          </label>
          <label class="tile">
            <input type="radio" name="model" value="replay" checked=${kind === "replay"} disabled=${!replayOk} onChange=${() => setKind("replay")} />
            <b>Recorded answers</b>
            <span>${replayOk
              ? "Replays the answer a model gave in the benchmark run. The build, tests, commit and mutants run live here."
              : `Available for ${replayable} of ${items.length} selected requirement${items.length > 1 ? "s" : ""}.`}</span>
          </label>
        </div>
      </fieldset>
      <div class="form-row">
        <div class="field"><span class="usa-label" id="att-l">Attempts per requirement</span>
          <${Stepper} id="att-l" label="attempts" value=${attempts} min=${1} max=${6} onChange=${setAttempts} />
          <span class="usa-hint">Each failed build or test sends its output back for a repair.</span></div>
        <div class="field"><span class="usa-label" id="mut-l">Mutants for fault detection</span>
          <${Stepper} id="mut-l" label="mutants" value=${mutants} min=${0} max=${12} onChange=${setMutants} />
          <span class="usa-hint">Seeded bugs the new test should catch. 0 skips the check.</span></div>
      </div>
      ${err ? html`<div class="note bad" role="alert">${err}</div>` : null}
    </div>
    <div class="modal-foot">
      <button class="btn plain" type="button" onClick=${onClose}>Cancel</button>
      <button class="btn act" type="button" disabled=${!canStart} onClick=${start}><${Icon} name="play" />${busy ? "Starting…" : "Start run"}</button>
    </div>
  </div>`;
}
