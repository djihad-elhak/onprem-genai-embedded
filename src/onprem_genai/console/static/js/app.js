// Application shell: navigation rail, top bar, routing and the global status poll.
import { render } from "../vendor/htm-preact-standalone.mjs";
import { html, useEffect, useState, useRoute, useApi, api, go, href, Icon, Toasts, useKey } from "./lib.js";
import { Overview } from "./pages/overview.js";
import { Requirements } from "./pages/requirements.js";
import { Search } from "./pages/search.js";
import { Runs } from "./pages/runs.js";
import { Review } from "./pages/review.js";
import { Sizing } from "./pages/sizing.js";
import { Settings } from "./pages/settings.js";

const NAV = [
  ["overview", "Overview", "overview"],
  ["requirements", "Requirements", "requirements"],
  ["search", "Code search", "search"],
  ["runs", "Agent runs", "runs"],
  ["review", "Review", "review"],
  ["sizing", "GPU sizing", "sizing"],
];
const PAGES = { overview: Overview, requirements: Requirements, search: Search, runs: Runs, review: Review, sizing: Sizing, settings: Settings };
const TITLES = { overview: "Overview", requirements: "Requirements", search: "Code search", runs: "Agent runs", review: "Review", sizing: "GPU sizing", settings: "Settings" };

function ThemeSwitch() {
  const read = () => document.documentElement.getAttribute("data-theme") || "system";
  const [mode, setMode] = useState(read());
  const set = (m) => {
    if (m === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", m);
    try { m === "system" ? localStorage.removeItem("oge-theme") : localStorage.setItem("oge-theme", m); } catch { /* ignore */ }
    setMode(m);
  };
  return html`<div class="theme-switch" role="group" aria-label="Colour theme">
    ${["light", "system", "dark"].map((m) => html`<button type="button" aria-pressed=${mode === m} onClick=${() => set(m)}>${m[0].toUpperCase() + m.slice(1)}</button>`)}
  </div>`;
}

function Rail({ page, status, counts }) {
  const ws = status && status.workspace;
  return html`<nav class="rail" aria-label="Main">
    <a class="brand" href="#/overview">
      <img class="brand-mark" src="/static/img/mark.svg" alt="" />
      <span><span class="brand-name">oge</span><br /><span class="brand-sub">Engineering console</span></span>
    </a>
    <div class="nav">
      ${NAV.map(([key, label, icon]) => html`<a href=${href(key)} aria-current=${page === key ? "page" : undefined}>
        <${Icon} name=${icon} /><span>${label}</span>
        ${key === "review" && counts.review ? html`<span class="count" title=${`${counts.review} tests await review`}>${counts.review}</span>` : null}
        ${key === "runs" && counts.live ? html`<span class="count live" title="A run is in progress">1</span>` : null}
      </a>`)}
      <div class="nav-sep"></div>
      <a href=${href("settings")} aria-current=${page === "settings" ? "page" : undefined}><${Icon} name="settings" /><span>Settings</span></a>
    </div>
    <div class="rail-foot">
      ${ws ? html`<div class="ws">
        <span>Workspace</span>
        <b>F´ checkout ${ws.base_commit ? html`<span class="mono">${ws.base_commit.slice(0, 7)}</span>` : ""}</b>
        <span>${ws.ready ? "Ready for agent runs" : "Agent runs unavailable"}</span>
      </div>` : null}
      <${ThemeSwitch} />
    </div>
  </nav>`;
}

function TopBar({ status }) {
  const [q, setQ] = useState("");
  const submit = (e) => {
    e.preventDefault();
    const v = q.trim();
    if (!v) return;
    if (/^[A-Z][A-Z0-9]*(-[A-Z0-9]+)*-\d+$/.test(v)) go("requirements", null, { id: v });
    else go("search", null, { q: v });
    setQ("");
  };
  useKey((e) => { if (e.key === "/") { e.preventDefault(); document.getElementById("omni")?.focus(); } }, []);
  const llm = status && status.llm;
  let chip = html`<span class="dot"></span><span class="label-text">Checking…</span>`;
  if (llm) {
    chip = llm.configured
      ? html`<span class="dot ok"></span><span class="label-text">${llm.label || llm.model}</span>`
      : html`<span class="dot warn"></span><span class="label-text">No model server set</span>`;
  }
  return html`<header class="topbar">
    <form class="omni" role="search" onSubmit=${submit}>
      <${Icon} name="search" />
      <label class="sr-only" for="omni">Search requirements, code and tests</label>
      <input id="omni" type="search" autocomplete="off" placeholder="Requirement ID, function, test or a question about the code"
        value=${q} onInput=${(e) => setQ(e.target.value)} />
      <kbd>/</kbd>
    </form>
    <a class="model-chip" href=${href("settings")} title="Model server used for agent runs">${chip}</a>
  </header>`;
}

function App() {
  const route = useRoute();
  const [status, , reloadStatus] = useApi("/status");
  const [counts, setCounts] = useState({ review: 0, live: false });

  useEffect(() => {
    const tick = () => {
      api("/overview").then((o) => setCounts({ review: o.review.pending, live: o.runs.some((r) => r.status === "running" || r.status === "queued") }), () => {});
      reloadStatus();
    };
    tick();
    const t = setInterval(tick, 8000);
    window.addEventListener("oge:changed", tick);
    return () => { clearInterval(t); window.removeEventListener("oge:changed", tick); };
  }, []);

  useEffect(() => { document.title = `${TITLES[route.page] || "Console"} | Engineering console`; }, [route.page]);
  const Page = PAGES[route.page] || Overview;
  return html`<div class="shell">
    <${Rail} page=${route.page} status=${status} counts=${counts} />
    <div class="main">
      <${TopBar} status=${status} />
      <main id="main" tabindex="-1"><${Page} route=${route} status=${status} /></main>
    </div>
    <${Toasts} />
  </div>`;
}

render(html`<${App} />`, document.getElementById("app"));
