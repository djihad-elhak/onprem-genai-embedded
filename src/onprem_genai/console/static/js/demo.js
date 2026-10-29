// Static demo (GitHub Pages): answers the console's API from the files written by `oge console export-demo`.
// Reads are exact copies of the real console's answers. Review verdicts are kept in this browser and folded
// back into the requirement states, so the overview reacts to them. Runs, settings, free-text search and
// non-default sizing assumptions need the real console and say so.
import { ApiError, DEMO } from "./lib.js";

const MSG = {
  run: "This demo cannot start agent runs: they build and test C++ code in an F´ workspace on your own site. Watch the recorded run instead.",
  settings: "Settings are read-only in this demo. In the console on your site, this is where you point agent runs at your model server.",
  search: "The demo answers the example searches only. On your site, the console searches anything, by meaning and by name.",
  node: "This symbol is not part of the demo snapshot. On your site, the console opens every function and test.",
  sizing: "The demo has precomputed plans for these team sizes and the default workload. On your site, the console recomputes for any value.",
};

const cache = new Map();
async function file(rel, notFound) {
  if (!cache.has(rel)) {
    cache.set(rel, fetch(DEMO + rel).then(async (r) => {
      if (!r.ok) throw new ApiError(r.status === 404 && notFound ? notFound : `The demo data answered ${r.status}.`);
      return rel.endsWith(".md") ? r.text() : r.json();
    }));
  }
  try {
    return structuredClone(await cache.get(rel));
  } catch (e) {
    cache.delete(rel);
    if (e instanceof ApiError) throw e;
    throw new ApiError("The demo data could not be loaded. Check your connection and reload the page.");
  }
}

async function sha1(text) {
  const buf = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 20);
}

/* ------------------------------------------------------------------ verdicts kept in this browser */
const VKEY = "oge-demo-verdicts";
let memory = {};
function loadVerdicts() {
  try { return JSON.parse(localStorage.getItem(VKEY) || "{}"); } catch { return memory; }
}
function saveVerdicts(v) {
  memory = v;
  try { localStorage.setItem(VKEY, JSON.stringify(v)); } catch { /* private mode: kept for this page only */ }
}
function overlay(r) {
  const v = loadVerdicts()[r.id];
  if (v === undefined) return r;
  return { ...r, verdict: v ? v.verdict : null, note: v ? v.note : null, reviewer: v ? v.reviewer : null, verdict_at: v ? v.at : null };
}

async function passedByReq() {
  const by = {};
  for (const r of (await file("reviews.json")).map(overlay)) (by[r.req_id] = by[r.req_id] || []).push(r);
  return by;
}
function stateOf(row, by) {
  const passed = by[row.req_id];
  if (row.base === "covered" || !passed) return row.state;
  if (passed.some((r) => r.verdict === "relevant" || r.verdict === "partial")) return "accepted";
  if (passed.some((r) => !r.verdict)) return "generated";
  return "rejected";
}
async function requirementRows() {
  const [rows, by] = await Promise.all([file("requirements.json"), passedByReq()]);
  return rows.map((r) => ({ ...r, state: stateOf(r, by) }));
}

/* ------------------------------------------------------------------ routes */
async function get(seg, q) {
  switch (seg[0]) {
    case "status":
    case "settings":
      return file(`${seg[0]}.json`);
    case "overview": {
      const [o, rows, reviews] = await Promise.all([file("overview.json"), requirementRows(), file("reviews.json")]);
      const state = Object.fromEntries(rows.map((r) => [r.req_id, r.state]));
      o.counts = Object.fromEntries(Object.keys(o.counts).map((k) => [k, 0]));
      for (const r of rows) o.counts[r.state] = (o.counts[r.state] || 0) + 1;
      for (const m of o.modules) for (const it of m.items) it.state = state[it.req_id] || it.state;
      const marked = reviews.map(overlay).filter((r) => r.verdict).length;
      o.review = { pending: reviews.length - marked, reviewed: marked };
      return o;
    }
    case "modules": {
      const [mods, rows] = await Promise.all([file("modules.json"), requirementRows()]);
      for (const m of mods) {
        m.counts = {};
        for (const r of rows) if (r.module === m.module) m.counts[r.state] = (m.counts[r.state] || 0) + 1;
      }
      return mods;
    }
    case "requirements": {
      if (seg[1]) {
        const [d, by] = await Promise.all([file(`req/${seg[1]}.json`, `No requirement ${seg[1]}.`), passedByReq()]);
        d.results = d.results.map(overlay);
        d.state = stateOf(d, by);
        return d;
      }
      const module = q.get("module");
      return (await requirementRows()).filter((r) => !module || r.module === module);
    }
    case "search": {
      const text = (q.get("q") || "").trim();
      if (!text) return [];
      const all = await file("search.json");
      const hits = all[`${q.get("kind") || ""}|${text}`];
      if (!hits) throw new ApiError(MSG.search);
      return hits;
    }
    case "nodes":
      return file(`nodes/${await sha1(seg[1])}.json`, MSG.node);
    case "runs":
      return seg[1] ? file(`runs/${seg[1]}.json`, "No such run.") : file("runs.json");
    case "reviews": {
      if (seg[1]) return overlay(await file(`reviews/${seg[1]}.json`, "No such test."));
      const which = q.get("filter") || "pending";
      const rows = (await file("reviews.json")).map(overlay);
      return which === "pending" ? rows.filter((r) => !r.verdict) : which === "reviewed" ? rows.filter((r) => r.verdict) : rows;
    }
    case "sizing":
      if (seg[1] === "options") return file("sizing/options.json");
      break;
    default:
      break;
  }
  throw new ApiError("Not part of the demo.");
}

async function plan(body) {
  const meta = await file("meta.json");
  if (!meta.engineers.includes(Number(body.engineers)) || (body.kv && body.kv !== meta.kv)) throw new ApiError(MSG.sizing);
  const grid = await file(`sizing/${body.model}__${body.calibration}.json`);
  const res = grid[`${body.weights}|${body.scenario}|${body.engineers}`];
  if (!res) throw new ApiError(MSG.sizing);
  if (res.error) throw new ApiError(res.error);
  if (body.gpus && body.gpus.length) res.plans = res.plans.filter((p) => body.gpus.includes(p.gpu));
  return res;
}

export async function demoApi(path, { method = "GET", body } = {}) {
  const [p, qs] = path.split("?");
  const seg = p.split("/").filter(Boolean).map(decodeURIComponent);
  const q = new URLSearchParams(qs || "");
  if (method === "GET") return get(seg, q);
  if (seg[0] === "reviews" && seg[1] && method === "PUT") {
    const v = loadVerdicts();
    v[seg[1]] = body.verdict ? { verdict: body.verdict, note: body.note || "", reviewer: "you, in this browser", at: Date.now() / 1000 } : null;
    saveVerdicts(v);
    return get(seg, q);
  }
  if (seg[0] === "sizing" && seg[1] === "plan") return plan(body || {});
  if (seg[0] === "settings") throw new ApiError(MSG.settings);
  if (seg[0] === "runs") throw new ApiError(MSG.run);
  throw new ApiError("Not part of the demo.");
}

export const DEMO_MSG = MSG;
