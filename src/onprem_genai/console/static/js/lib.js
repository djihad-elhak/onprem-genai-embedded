// Shared helpers and components of the console: API access, routing, formatting, icons, code rendering.
import { html, useEffect, useRef, useState, useCallback } from "../vendor/htm-preact-standalone.mjs";

export { html, useEffect, useRef, useState, useCallback };

/* ------------------------------------------------------------------ API */
export class ApiError extends Error {}

export async function api(path, { method = "GET", body } = {}) {
  let res;
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("The console server is not reachable. Check that it is still running.");
  }
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new ApiError((data && data.error) || `The server answered ${res.status}.`);
  return data;
}

/** Load data for a view; returns [data, error, reload]. */
export function useApi(path, deps = []) {
  const [state, setState] = useState({ data: null, error: null });
  const seq = useRef(0);
  const load = useCallback(() => {
    if (!path) return;
    const n = ++seq.current;
    api(path).then(
      (data) => n === seq.current && setState({ data, error: null }),
      (error) => n === seq.current && setState((s) => ({ data: s.data, error })),
    );
  }, [path]);
  useEffect(load, [path, ...deps]);
  return [state.data, state.error, load];
}

/* ------------------------------------------------------------------ routing (hash) */
export function parseRoute() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [pathPart, query = ""] = raw.split("?");
  const parts = pathPart.split("/").filter(Boolean).map(decodeURIComponent);
  return { page: parts[0] || "overview", arg: parts[1] || null, params: new URLSearchParams(query) };
}

export function href(page, arg, params) {
  let h = `#/${page}`;
  if (arg !== undefined && arg !== null && arg !== "") h += `/${encodeURIComponent(arg)}`;
  if (params) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, v);
    const s = q.toString();
    if (s) h += `?${s}`;
  }
  return h;
}

export function go(page, arg, params, { replace = false } = {}) {
  const h = href(page, arg, params);
  if (replace) history.replaceState(null, "", h);
  else location.hash = h;
  if (replace) window.dispatchEvent(new HashChangeEvent("hashchange"));
}

export function useRoute() {
  const [route, setRoute] = useState(parseRoute());
  useEffect(() => {
    const on = () => setRoute(parseRoute());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

/* ------------------------------------------------------------------ toasts */
const toastListeners = new Set();
export function toast(message, { kind = "info", link = null, ms = 4200 } = {}) {
  const t = { id: Math.random(), message, kind, link };
  toastListeners.forEach((fn) => fn(t, ms));
}
export function Toasts() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    const fn = (t, ms) => {
      setItems((xs) => [...xs, t]);
      setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== t.id)), ms);
    };
    toastListeners.add(fn);
    return () => toastListeners.delete(fn);
  }, []);
  return html`<div class="toasts" role="status" aria-live="polite">
    ${items.map((t) => html`<div class=${`toast ${t.kind === "bad" ? "bad" : ""}`} key=${t.id}>
      <span>${t.message}</span>${t.link ? html`<a href=${t.link.href}>${t.link.text}</a>` : null}
    </div>`)}
  </div>`;
}

/* ------------------------------------------------------------------ tooltip (one, positioned at the pointer) */
let tipEl = null;
export function showTip(e, content) {
  if (!tipEl) { tipEl = document.createElement("div"); tipEl.className = "tip"; document.body.appendChild(tipEl); }
  tipEl.innerHTML = content;
  tipEl.hidden = false;
  const r = (e.currentTarget || e.target).getBoundingClientRect();
  const w = tipEl.offsetWidth, h = tipEl.offsetHeight;
  let x = r.left + r.width / 2 - w / 2, y = r.top - h - 8;
  x = Math.max(8, Math.min(x, innerWidth - w - 8));
  if (y < 8) y = r.bottom + 8;
  tipEl.style.left = `${x}px`; tipEl.style.top = `${y}px`;
}
export function hideTip() { if (tipEl) tipEl.hidden = true; }
export const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ------------------------------------------------------------------ formatting */
export const fmtInt = (n) => (n === null || n === undefined ? "–" : Number(n).toLocaleString("en-US"));
export const pct = (x) => (x === null || x === undefined ? "–" : `${Math.round(x * 100)}%`);
export function ago(ts) {
  if (!ts) return "";
  const s = Date.now() / 1000 - ts;
  if (s < 50) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
export function duration(sec) {
  if (sec === null || sec === undefined) return "–";
  if (sec < 60) return `${Math.round(sec)} s`;
  const m = Math.floor(sec / 60), s = Math.round(sec % 60);
  return `${m} min ${String(s).padStart(2, "0")} s`;
}
export const short = (sha) => (sha ? sha.slice(0, 10) : "");

/* ------------------------------------------------------------------ traceability states */
export const STATES = {
  covered: { label: "Cited by a test", help: "A unit test carries this requirement's REQUIREMENT tag." },
  accepted: { label: "Generated, accepted", help: "The agent wrote a test and a reviewer judged it relevant." },
  generated: { label: "Awaiting review", help: "The agent wrote a passing test; a person has not reviewed it yet." },
  attempted: { label: "Agent could not verify", help: "The agent tried and no test passed; the gap is still open." },
  rejected: { label: "Generated, rejected", help: "A reviewer judged the generated test not relevant." },
  gap: { label: "No test evidence", help: "The design says it is verified by test, but no test cites it." },
  not_by_test: { label: "Verified otherwise", help: "Verified by inspection or analysis, not by test." },
};
export const STATE_ORDER = ["covered", "accepted", "generated", "attempted", "rejected", "gap", "not_by_test"];

export function State({ s, big = false }) {
  const st = STATES[s] || { label: s };
  return html`<span class=${`state ${big ? "big" : ""}`} title=${st.help || ""}><i class=${`s-${s}`}></i>${st.label}</span>`;
}

export const RUN_STATUS = {
  queued: ["Queued", "warn"], running: ["Running", "live"], stopping: ["Stopping", "live"], done: ["Finished", "ok"],
  failed: ["Failed", "bad"], cancelled: ["Stopped", ""],
};
export function RunStatus({ status }) {
  const [label, cls] = RUN_STATUS[status] || [status, ""];
  return html`<span class="row" style="gap:7px"><span class=${`dot ${cls}`}></span>${label}</span>`;
}

export const RESULT = {
  passed: ["Verified", "ok"], failed: ["Not verified", "bad"], not_testable: ["Not testable", ""],
  suspected_defect: ["Suspected defect", "warn"], unsupported: ["Unsupported", ""], env_error: ["Environment error", "bad"],
  llm_error: ["Model error", "bad"], error: ["Error", "bad"],
};
export function ResultTag({ status }) {
  const [label, cls] = RESULT[status] || [status, ""];
  return html`<span class=${`tag ${cls}`}>${label}</span>`;
}

/* ------------------------------------------------------------------ icons (stroke, 24 grid) */
const P = {
  overview: "M4 5h7v6H4zM13 5h7v3h-7zM13 10h7v9h-7zM4 13h7v6H4z",
  requirements: "M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2",
  search: "M11 18a7 7 0 1 1 0-14 7 7 0 0 1 0 14zM20 20l-4-4",
  runs: "M5 4v16M5 6h9l-2 3 2 3H5M15 15l2 2 4-4",
  review: "M7 3h7l5 5v13H7zM14 3v5h5M10 14l2 2 4-4",
  sizing: "M4 5h16v5H4zM4 14h16v5H4zM8 7.5h.01M8 16.5h.01M12 7.5h5M12 16.5h5",
  settings: "M4 7h10M18 7h2M4 17h4M12 17h8M16 5v4M10 15v4",
  play: "M8 5l11 7-11 7z",
  stop: "M7 7h10v10H7z",
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6L6 18",
  dot: "M12 12h.01",
  arrowLeft: "M15 6l-6 6 6 6",
  download: "M12 4v11M7 10l5 5 5-5M5 20h14",
  external: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6",
  copy: "M8 8h11v12H8zM5 16V4h11",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  bolt: "M13 3L5 13h6l-1 8 8-10h-6z",
  branch: "M6 4v12M6 16a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM18 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 8c0 5-12 3-12 8",
};
export function Icon({ name, size = 18 }) {
  return html`<svg viewBox="0 0 24 24" width=${size} height=${size} fill="none" stroke="currentColor" stroke-width="1.7"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d=${P[name] || P.dot} /></svg>`;
}

/* ------------------------------------------------------------------ code rendering */
const CPP = /(\/\/[^\n]*|\/\*[\s\S]*?\*\/)|("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)')|\b(ASSERT_\w+|EXPECT_\w+|REQUIREMENT|TEST_CASE|COMMENT|TEST|FW_ASSERT|ASSERT_TRUE|ASSERT_EQ)\b|\b(void|const|static|bool|true|false|this|return|if|else|for|while|switch|case|break|auto|int|char|sizeof|reinterpret_cast|static_cast|U8|U16|U32|U64|I8|I16|I32|F32|F64|FwSizeType|FwIndexType|namespace|class|public|private|protected|enum|struct|final|override|nullptr|new|delete|include|define)\b|\b(0x[0-9A-Fa-f]+|\d+(?:\.\d+)?[uUlLfF]*)\b/g;

export function highlightCpp(src) {
  let out = "", last = 0;
  src.replace(CPP, (m, cm, st, mac, kw, num, i) => {
    out += esc(src.slice(last, i));
    const cls = cm ? "c" : st ? "s" : mac ? "m" : kw ? "k" : "n2";
    out += `<span class="${cls}">${esc(m)}</span>`;
    last = i + m.length;
    return m;
  });
  return out + esc(src.slice(last));
}
export function highlightLog(src) {
  return String(src).split("\n").map((ln) => {
    const e = esc(ln);
    if (/\berror:|Assert(ion)?[: ]|exited with code|FAILED|\bfailed\b/.test(ln)) return `<span class="e">${e}</span>`;
    if (/^\s*\d+ \||^\s*\|/.test(ln)) return `<span class="k">${e}</span>`;
    return e;
  }).join("\n");
}
export function highlightDiff(src) {
  return String(src).split("\n").map((ln) => {
    if (/^(diff |index |\+\+\+|---)/.test(ln)) return `<span class="d-hunk">${esc(ln)}</span>`;
    if (ln.startsWith("@@")) return `<span class="d-hunk">${esc(ln)}</span>`;
    if (ln.startsWith("+")) return `<span class="d-add">${highlightCpp(ln)}</span>`;
    if (ln.startsWith("-")) return `<span class="d-del">${esc(ln)}</span>`;
    return highlightCpp(ln);
  }).join("\n");
}

export function CopyButton({ text }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1400); }
    catch { toast("Copying is blocked here; select the text instead.", { kind: "bad" }); }
  };
  return html`<button class="btn quiet small" type="button" onClick=${copy}>${done ? "Copied" : "Copy"}</button>`;
}

export function Code({ title, text, kind = "cpp", wrap = false, actions = null }) {
  const body = kind === "diff" ? highlightDiff(text) : kind === "log" ? highlightLog(text) : kind === "plain" ? esc(text) : highlightCpp(text);
  return html`<div class="code">
    ${title !== undefined ? html`<div class="code-head"><span>${title}</span><span class="end">${actions}<${CopyButton} text=${text} /></span></div>` : null}
    <pre class=${wrap ? "wrap" : ""} dangerouslySetInnerHTML=${{ __html: body }}></pre>
  </div>`;
}

/** Text with `inline code` spans rendered as code. */
export function inlineCode(text) {
  return String(text).split(/(`[^`\n]+`)/g).map((part, i) =>
    part.length > 2 && part.startsWith("`") && part.endsWith("`") ? html`<code key=${i}>${part.slice(1, -1)}</code>` : part);
}

/** A model answer: prose paragraphs plus fenced code blocks, each labelled with where it goes. */
export function Answer({ text }) {
  const parts = [];
  const re = /```(\w+)?(?:[ \t]+(\w+))?\n([\s\S]*?)```/g;
  let last = 0, m, i = 0;
  const where = { tester: "Tester class", main: "Test main (TEST case)", header: "Tester header" };
  while ((m = re.exec(text))) {
    const prose = text.slice(last, m.index).trim();
    if (prose) parts.push(html`<div class="prose" key=${`p${i}`}>${prose.split(/\n\s*\n/).map((p) => html`<p>${inlineCode(p.trim())}</p>`)}</div>`);
    const tag = m[2] || m[1] || "code";
    parts.push(html`<${Code} key=${`c${i}`} title=${where[tag] || tag} text=${m[3].replace(/\s+$/, "")} />`);
    last = re.lastIndex; i += 1;
  }
  const tail = text.slice(last).trim();
  if (tail) parts.push(html`<div class="prose" key="tail"><p>${inlineCode(tail)}</p></div>`);
  return html`<div class="stack">${parts}</div>`;
}

export function Spinner() { return html`<span class="spinner" role="status" aria-label="Loading"></span>`; }

export function Loading({ lines = 4 }) {
  return html`<div class="stack" aria-busy="true">${Array.from({ length: lines }, (_, i) =>
    html`<div class="skel" style=${`height:${i === 0 ? 22 : 14}px;width:${[42, 88, 76, 64, 80][i % 5]}%`}></div>`)}</div>`;
}

export function ErrorNote({ error, onRetry }) {
  if (!error) return null;
  return html`<div class="callout bad"><b>${error.message}</b>${onRetry ? html`<div><button class="link-btn" onClick=${onRetry}>Try again</button></div>` : null}</div>`;
}

/** Keyboard shortcut that ignores typing in fields. */
export function useKey(handler, deps) {
  useEffect(() => {
    const on = (e) => {
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      handler(e);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, deps);
}

/** Close on Escape and keep focus inside a dialog while it is open. */
const dialogStack = [];
export function useDialog(ref, onClose) {
  useEffect(() => {
    const prev = document.activeElement;
    const me = {};
    dialogStack.push(me);
    const first = ref.current && ref.current.querySelector("[data-autofocus], button, input, select, textarea, a[href]");
    if (first) first.focus();
    const on = (e) => {
      if (dialogStack[dialogStack.length - 1] !== me) return; // only the top dialog reacts
      if (e.key === "Escape") { e.preventDefault(); onClose(); }
      if (e.key === "Tab" && ref.current) {
        const f = [...ref.current.querySelectorAll("button:not([disabled]), input:not([disabled]), select, textarea, a[href]")];
        if (!f.length) return;
        const [a, z] = [f[0], f[f.length - 1]];
        if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
        else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
      }
    };
    document.addEventListener("keydown", on);
    return () => {
      document.removeEventListener("keydown", on);
      dialogStack.splice(dialogStack.indexOf(me), 1);
      if (prev && prev.focus) prev.focus();
    };
  }, []);
}
