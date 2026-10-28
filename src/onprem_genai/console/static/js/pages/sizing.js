// GPU sizing: how many GPUs of each type a team needs, from the calibrated performance model.
import { html, useEffect, useMemo, useRef, useState } from "../../vendor/htm-preact-standalone.mjs";
import { useApi, api, Loading, ErrorNote, fmtInt } from "../lib.js";

const WEIGHT_LABEL = { q4_k_m: "4-bit (Q4_K_M)", awq_int4_g128: "4-bit (AWQ)", gptq_int4_g128: "4-bit (GPTQ)", q5_k_m: "5-bit (Q5_K_M)", q6_k: "6-bit (Q6_K)", q8_0: "8-bit (Q8_0)", fp8: "FP8", f16: "FP16", bf16: "BF16" };
const KV_LABEL = { f16: "FP16", bf16: "BF16", fp8: "FP8", q8_0: "8-bit", q4_0: "4-bit" };
const SCENARIO_LABEL = { chat: "IDE chat", chat_agents: "Chat and agents", full: "Chat, agents and completion" };
const CLASS_LABEL = { chat: "Chat", agent_step: "Agent step", completion: "Completion" };

function Num({ id, value, onChange, min, max, step = 1 }) {
  return html`<input id=${id} class="input num" type="number" min=${min} max=${max} step=${step} value=${value}
    onChange=${(e) => { const v = Number(e.target.value); if (!Number.isNaN(v)) onChange(Math.min(max, Math.max(min, v))); }} />`;
}

function GpuRow({ p, best }) {
  const feasible = p.feasible;
  const cells = [];
  if (feasible) for (let r = 0; r < p.replicas; r++) for (let g = 0; g < p.gpus_per_replica; g++) cells.push(html`<i key=${`${r}-${g}`} class=${r % 2 ? "r2" : ""} title=${`replica ${r + 1}`}></i>`);
  return html`<div class=${`gpu-row ${feasible ? "" : "infeasible"} ${best ? "best" : ""}`}>
    <div class="name">${p.gpu_name}<small>${feasible ? `${p.replicas} × ${p.gpus_per_replica} GPU${p.gpus_per_replica > 1 ? "s" : ""}, ${p.per_sequence_tps.toFixed(0)} tok/s per user` : p.reason}</small></div>
    <div class="cells" aria-hidden="true">${cells.length > 48 ? html`<span class="muted">${cells.length} GPUs</span>` : cells}</div>
    <div class="num-big">${feasible ? p.total_gpus : "–"}<small>${feasible ? (p.total_gpus === 1 ? "GPU" : "GPUs") : "not possible"}</small></div>
  </div>`;
}

export function Sizing() {
  const [opts, error] = useApi("/sizing/options");
  const [form, setForm] = useState(null);
  const [plan, setPlan] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);

  useEffect(() => {
    if (!opts || form) return;
    const sc = opts.scenarios.find((s) => s.key === "chat_agents") || opts.scenarios[0];
    setForm({
      model: opts.models.find((m) => m.key === "qwen3-coder-30b-a3b") ? "qwen3-coder-30b-a3b" : opts.models[0].key,
      weights: "q4_k_m", kv: "f16", scenario: sc.key, engineers: 100, calibration: "llamacpp_t4",
      classes: sc.request_classes.map((c) => ({ ...c })), active: sc.peak_active_fraction, slo: sc.min_decode_tps_per_sequence, headroom: sc.headroom,
      gpus: opts.gpus.filter((g) => g.key !== "t4").map((g) => g.key),
    });
  }, [opts]);

  useEffect(() => {
    if (!form) return undefined;
    const n = ++seq.current;
    const t = setTimeout(async () => {
      setBusy(true);
      try {
        const res = await api("/sizing/plan", { method: "POST", body: {
          model: form.model, weights: form.weights, kv: form.kv, scenario: form.scenario, engineers: form.engineers,
          calibration: form.calibration, gpus: form.gpus,
          overrides: { request_classes: form.classes, peak_active_fraction: form.active, min_decode_tps_per_sequence: form.slo, headroom: form.headroom },
        } });
        if (n === seq.current) { setPlan(res); setErr(null); }
      } catch (e) { if (n === seq.current) setErr(e.message); }
      if (n === seq.current) setBusy(false);
    }, 180);
    return () => clearTimeout(t);
  }, [form]);

  const best = useMemo(() => {
    if (!plan) return null;
    const ok = plan.plans.filter((p) => p.feasible);
    if (!ok.length) return null;
    const min = Math.min(...ok.map((p) => p.total_gpus));
    const tied = ok.filter((p) => p.total_gpus === min);
    return { min, tied, first: tied[0] };
  }, [plan]);

  if (error) return html`<div class="page"><${ErrorNote} error=${error} /></div>`;
  if (!opts || !form) return html`<div class="page"><div class="panel panel-body"><${Loading} lines=${8} /></div></div>`;
  const up = (patch) => setForm({ ...form, ...patch });
  const pickScenario = (key) => {
    const sc = opts.scenarios.find((s) => s.key === key);
    up({ scenario: key, classes: sc.request_classes.map((c) => ({ ...c })), active: sc.peak_active_fraction, slo: sc.min_decode_tps_per_sequence, headroom: sc.headroom });
  };
  const setClass = (i, k, v) => up({ classes: form.classes.map((c, j) => (j === i ? { ...c, [k]: v } : c)) });
  const model = opts.models.find((m) => m.key === form.model);
  const toggleGpu = (k) => up({ gpus: form.gpus.includes(k) ? form.gpus.filter((x) => x !== k) : [...form.gpus, k] });
  const plans = plan ? [...plan.plans].sort((a, b) => (a.feasible === b.feasible ? a.total_gpus - b.total_gpus : a.feasible ? -1 : 1)) : [];

  return html`<div class="page">
    <div class="page-head"><div><h1>GPU sizing</h1>
      <p class="lede">How many GPUs a team needs for a model and a way of working. The performance model is calibrated on
        measurements, and every assumption below can be changed.</p></div></div>
    <div class="sizing-layout">
      <section class="panel" aria-label="Assumptions"><div class="panel-body form">
        <div class="field"><label for="sz-model">Model</label>
          <select id="sz-model" class="select" value=${form.model} onChange=${(e) => up({ model: e.target.value })}>
            ${opts.models.map((m) => html`<option value=${m.key}>${m.name}</option>`)}</select>
          ${model ? html`<span class="hint">${(model.params_total / 1e9).toFixed(1)} B parameters${model.moe ? `, ${(model.params_active / 1e9).toFixed(1)} B active per token (mixture of experts)` : ", dense"}</span>` : null}</div>
        <div class="form-row">
          <div class="field"><label for="sz-w">Weights</label>
            <select id="sz-w" class="select" value=${form.weights} onChange=${(e) => up({ weights: e.target.value })}>
              ${opts.weights.map((w) => html`<option value=${w.key}>${WEIGHT_LABEL[w.key] || w.key}</option>`)}</select></div>
          <div class="field"><label for="sz-kv">KV cache</label>
            <select id="sz-kv" class="select" value=${form.kv} onChange=${(e) => up({ kv: e.target.value })}>
              ${opts.kv.map((k) => html`<option value=${k.key}>${KV_LABEL[k.key] || k.key}</option>`)}</select></div>
        </div>
        <div class="field"><label for="sz-eng">Engineers in the team</label>
          <div class="row"><input class="slider grow" type="range" min="5" max="1000" step="5" value=${form.engineers} aria-label="Engineers" onInput=${(e) => up({ engineers: Number(e.target.value) })} />
            <div style="width:96px"><${Num} id="sz-eng" value=${form.engineers} min=${1} max=${100000} onChange=${(v) => up({ engineers: v })} /></div></div></div>
        <div class="field"><label for="sz-sc">Way of working</label>
          <select id="sz-sc" class="select" value=${form.scenario} onChange=${(e) => pickScenario(e.target.value)}>
            ${opts.scenarios.map((s) => html`<option value=${s.key}>${SCENARIO_LABEL[s.key] || s.key}</option>`)}</select>
          <table class="classes"><thead><tr><th>Request</th><th>Per engineer per hour</th><th>Prompt tokens</th><th>Answer tokens</th></tr></thead>
            <tbody>${form.classes.map((c, i) => html`<tr key=${c.name}>
              <td>${CLASS_LABEL[c.name] || c.name}</td>
              <td><${Num} value=${c.requests_per_engineer_hour} min=${0} max=${1000} onChange=${(v) => setClass(i, "requests_per_engineer_hour", v)} /></td>
              <td><${Num} value=${c.prompt_tokens} min=${1} max=${200000} step=${100} onChange=${(v) => setClass(i, "prompt_tokens", v)} /></td>
              <td><${Num} value=${c.output_tokens} min=${1} max=${32000} step=${10} onChange=${(v) => setClass(i, "output_tokens", v)} /></td>
            </tr>`)}</tbody></table></div>
        <div class="form-row">
          <div class="field"><label for="sz-act">Active at peak hour</label><${Num} id="sz-act" value=${Math.round(form.active * 100)} min=${1} max=${100} onChange=${(v) => up({ active: v / 100 })} /><span class="hint">Percent of the team</span></div>
          <div class="field"><label for="sz-slo">Speed per user</label><${Num} id="sz-slo" value=${form.slo} min=${1} max=${200} onChange=${(v) => up({ slo: v })} /><span class="hint">Tokens per second, at least</span></div>
        </div>
        <div class="form-row">
          <div class="field"><label for="sz-head">Headroom</label><${Num} id="sz-head" value=${form.headroom} min=${1} max=${4} step=${0.05} onChange=${(v) => up({ headroom: v })} /><span class="hint">Margin for bursts and failover</span></div>
          <div class="field"><label for="sz-cal">Efficiency</label>
            <select id="sz-cal" class="select" value=${form.calibration} onChange=${(e) => up({ calibration: e.target.value })}>
              ${opts.calibrations.map((c) => html`<option value=${c.key}>${c.label}</option>`)}</select></div>
        </div>
        <fieldset class="field" style="border:0;padding:0;margin:0"><legend class="label" style="margin-bottom:6px">GPUs to compare</legend>
          <div class="stack" style="gap:6px">${opts.gpus.map((g) => html`<label class="check" key=${g.key}><input type="checkbox" checked=${form.gpus.includes(g.key)} onChange=${() => toggleGpu(g.key)} />
            <span>${g.name} <span class="muted">${g.memory_gb} GB, ${fmtInt(g.bandwidth_gbs)} GB/s</span></span></label>`)}</div></fieldset>
      </div></section>

      <section class="panel" aria-live="polite" aria-busy=${busy}>
        <div class="panel-body stack" style="gap:8px">
          ${err ? html`<div class="callout bad">${err}</div>` : null}
          ${!plan ? html`<${Loading} lines=${3} />` : best ? html`<p class="verdict-line">${fmtInt(plan.engineers)} engineers need ${best.min} GPU${best.min > 1 ? "s" : ""}<span class="soft">${best.tied.length === 1 ? ` of type ${best.first.gpu_name}` : `, with any of ${best.tied.length} GPU types below`}.</span></p>
              <p class="ink2">Each user then sees about ${best.first.per_sequence_tps.toFixed(0)} tokens per second on ${best.first.gpu_name}. ${Object.entries(best.first.ttft_s).map(([k, v]) => `${CLASS_LABEL[k] || k} answers start after about ${v < 1 ? v.toFixed(2) : v.toFixed(1)} s`).join("; ")}.</p>`
            : html`<p class="verdict-line">No selected GPU can serve this workload.<span class="soft"> Lower the speed per user, choose smaller weights or add larger GPUs.</span></p>`}
        </div>
        ${plan ? html`<div class="gpu-rows">${plans.map((p) => html`<${GpuRow} key=${p.gpu} p=${p} best=${best && best.tied.includes(p)} />`)}</div>` : null}
        <div class="panel-body" style="border-top:1px solid var(--line)">
          <p class="muted" style="font-size:12.5px">Throughput per GPU comes from a roofline model whose efficiency factors were measured on 2× Tesla T4.
            Other GPU generations can behave differently: before buying, run the probe notebook on the candidate GPU and calibrate with it.</p>
        </div>
      </section>
    </div>
  </div>`;
}
