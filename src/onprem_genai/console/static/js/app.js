// Application shell: black header with the main navigation, page surface in the HDS White or Dark palette,
// black footer, routing and the global status poll.
import { render } from "../vendor/htm-preact-standalone.mjs";
import { html, useEffect, useState, useRoute, useApi, api, go, href, Icon, Toasts, useKey, DEMO, SNAPSHOT } from "./lib.js";
import { Overview } from "./pages/overview.js";
import { Requirements } from "./pages/requirements.js";
import { Search } from "./pages/search.js";
import { Runs } from "./pages/runs.js";
import { Review } from "./pages/review.js";
import { Sizing } from "./pages/sizing.js";
import { Settings } from "./pages/settings.js";

const NAV = [
  ["overview", "Overview"],
  ["requirements", "Requirements"],
  ["search", "Code search"],
  ["runs", "Agent runs"],
  ["review", "Review"],
  ["sizing", "GPU sizing"],
];
const PAGES = { overview: Overview, requirements: Requirements, search: Search, runs: Runs, review: Review, sizing: Sizing, settings: Settings };
const TITLES = { overview: "Overview", requirements: "Requirements", search: "Code search", runs: "Agent runs", review: "Review", sizing: "GPU sizing", settings: "Settings" };

/** oge's own mark: four requirement ticks, the last one still open. Not a NASA mark. */
export function Mark() {
  return html`<svg class="wordmark-mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
    <rect x="3" y="5" width="4.5" height="22" fill="#fff" /><rect x="10.5" y="5" width="4.5" height="22" fill="#fff" />
    <rect x="18" y="5" width="4.5" height="22" fill="#fff" /><rect x="25.5" y="5" width="4.5" height="22" fill="#ea6f24" />
  </svg>`;
}

function useTheme() {
  const read = () => (document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light");
  const [theme, setTheme] = useState(read());
  const set = (t) => {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("oge-theme", t); } catch { /* storage unavailable: the choice lasts for this page */ }
    setTheme(t);
  };
  return [theme, set];
}

function Header({ page, status, counts, theme, setTheme }) {
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
  let model = html`<span class="light"></span><span class="label-text">Checking model server</span>`;
  if (DEMO) model = html`<span class="light ok"></span><span class="label-text">Recorded answers</span>`;
  else if (llm) {
    model = llm.configured
      ? html`<span class="light ok"></span><span class="label-text">${llm.label || llm.model}</span>`
      : html`<span class="light warn"></span><span class="label-text">No model server</span>`;
  }
  const dark = theme === "dark";
  return html`<header class="site-head">
    <div class="container">
      <a class="wordmark" href="#/overview" aria-label="oge engineering console, overview">
        <${Mark} /><span class="wordmark-name">oge</span><span class="wordmark-sub">Engineering<br />console</span>
      </a>
      <nav class="site-nav" aria-label="Main">
        ${NAV.map(([key, label]) => html`<a href=${href(key)} aria-current=${page === key ? "page" : undefined} key=${key}>
          ${label}
          ${key === "review" && counts.review ? html`<span class="count" title=${`${counts.review} tests wait for review`}>${counts.review}</span>` : null}
          ${key === "runs" && counts.live ? html`<span class="count live" title="A run is in progress">1</span>` : null}
        </a>`)}
      </nav>
      <div class="head-tools">
        <form class="head-search" role="search" onSubmit=${submit}>
          <${Icon} name="search" />
          <label class="sr-only" for="omni">Search requirements, code and tests</label>
          <input id="omni" type="search" autocomplete="off" placeholder="Search"
            value=${q} onInput=${(e) => setQ(e.target.value)} />
          <kbd aria-hidden="true">/</kbd>
        </form>
        <a class="model-status" href=${href("settings")} title="Model server used by agent runs">${model}</a>
        <button class="head-icon" type="button" aria-pressed=${dark} title=${dark ? "Use the light theme" : "Use the dark theme"}
          onClick=${() => setTheme(dark ? "light" : "dark")}><span class="sr-only">Dark theme</span><${Icon} name=${dark ? "sun" : "moon"} /></button>
        <a class="head-icon" href=${href("settings")} aria-current=${page === "settings" ? "page" : undefined} title="Settings"><span class="sr-only">Settings</span><${Icon} name="settings" /></a>
      </div>
    </div>
  </header>`;
}

const REPO = "https://github.com/djihad-elhak/onprem-genai-embedded";

function DemoBar() {
  return html`<section class="demo-bar" aria-label="About this demo">
    <div class="container">
      <span class="tag">Demo</span>
      <span>Read-only snapshot${SNAPSHOT ? ` from ${SNAPSHOT}` : ""}. Starting runs, settings and free-text search need the console on your own site.</span>
      <span class="demo-links"><a href=${href("runs", 1, { play: 1 })}>Replay the agent run</a><a href=${`${REPO}#engineering-console`} rel="noreferrer">Run it yourself</a></span>
    </div>
  </section>`;
}

function Footer({ status }) {
  const ws = status && status.workspace;
  return html`<footer class="site-foot">
    <div class="container">
      <div class="wordmark"><${Mark} /><span class="wordmark-name">oge</span></div>
      <div class="stack">
        <p>On-premises generative AI for flight software. Every model, index and repository runs on this site.
          ${DEMO && ws ? html` Static demo built from F´ at <span class="mono">${(ws.base_commit || "").slice(0, 7)}</span>.` : null}
          ${ws && !DEMO ? html` F´ workspace ${ws.ready ? "ready" : "not available"}${ws.base_commit ? html`, runs start from <span class="mono">${ws.base_commit.slice(0, 7)}</span>` : ""}.` : null}</p>
        <p>Built with the <a href="https://github.com/nasa/hds-core" rel="noreferrer">Horizon Design System</a>, released into the public domain.
          oge is an independent project, not affiliated with or endorsed by NASA.</p>
      </div>
      <p class="mono">${status && status.version ? `v${status.version}` : ""}</p>
    </div>
  </footer>`;
}

function App() {
  const route = useRoute();
  const [status, , reloadStatus] = useApi("/status");
  const [counts, setCounts] = useState({ review: 0, live: false });
  const [theme, setTheme] = useTheme();

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

  useEffect(() => {
    document.title = `${TITLES[route.page] || "Console"} | oge engineering console`;
    window.scrollTo(0, 0);
  }, [route.page]);
  const Page = PAGES[route.page] || Overview;
  const palette = theme === "dark" ? "hds-palette-dark" : "hds-palette-white";
  return html`<div class=${`app ${palette}`}>
    <a class="skip-link" href="#main" onClick=${(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>Skip to main content</a>
    <${Header} page=${route.page} status=${status} counts=${counts} theme=${theme} setTheme=${setTheme} />
    ${DEMO ? html`<${DemoBar} />` : null}
    <main id="main" class="page-surface" tabindex="-1"><${Page} route=${route} status=${status} /></main>
    <${Footer} status=${status} />
    <${Toasts} />
  </div>`;
}

render(html`<${App} />`, document.getElementById("app"));
