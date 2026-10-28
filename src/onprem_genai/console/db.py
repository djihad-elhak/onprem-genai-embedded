"""SQLite persistence of the console: settings, agent runs, their step events, results and review verdicts.

One file, created on first use; every write is a short transaction, so the console can be stopped at any time.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at REAL NOT NULL,
  started_at REAL,
  finished_at REAL,
  status TEXT NOT NULL,              -- queued | running | done | failed | cancelled
  model_kind TEXT NOT NULL,          -- endpoint | replay
  model_label TEXT NOT NULL,
  options TEXT NOT NULL,             -- JSON: attempts, mutants, base_url, model
  req_ids TEXT NOT NULL,             -- JSON list
  branch TEXT,
  error TEXT
);
CREATE TABLE IF NOT EXISTS events (
  run_id INTEGER NOT NULL,
  seq INTEGER NOT NULL,
  ts REAL NOT NULL,
  payload TEXT NOT NULL,
  PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER,                    -- NULL for imported benchmark results
  source TEXT NOT NULL,              -- 'console' or the imported file's label
  model_label TEXT NOT NULL,
  req_id TEXT NOT NULL,
  module TEXT,
  status TEXT NOT NULL,
  created_at REAL NOT NULL,
  record TEXT NOT NULL,              -- the agent's JSON record (history, metrics, diff, answer)
  ai_verdict TEXT,                   -- optional pre-review verdict, shown as a suggestion only
  ai_note TEXT,
  UNIQUE (source, model_label, req_id)
);
CREATE TABLE IF NOT EXISTS verdicts (
  result_id INTEGER PRIMARY KEY REFERENCES results(id),
  verdict TEXT NOT NULL,             -- relevant | partial | not_relevant
  note TEXT NOT NULL DEFAULT '',
  reviewer TEXT NOT NULL DEFAULT '',
  updated_at REAL NOT NULL
);
"""

VERDICTS = ("relevant", "partial", "not_relevant")


class ConsoleDb:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        # A run left 'running' or 'queued' by a stopped console did not finish.
        self._conn.execute(
            "UPDATE runs SET status='failed', error='the console stopped during the run', finished_at=? "
            "WHERE status IN ('running', 'queued')",
            (time.time(),),
        )

    def _q(self, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def _x(self, sql: str, args: tuple[Any, ...] = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, args)
            return int(cur.lastrowid or 0)

    # -- settings
    def settings(self) -> dict[str, Any]:
        return {r["key"]: json.loads(r["value"]) for r in self._q("SELECT key, value FROM settings")}

    def set_settings(self, values: dict[str, Any]) -> None:
        for k, v in values.items():
            self._x(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, json.dumps(v)),
            )

    # -- runs
    def create_run(
        self, model_kind: str, model_label: str, options: dict[str, Any], req_ids: list[str]
    ) -> int:
        return self._x(
            "INSERT INTO runs(created_at, status, model_kind, model_label, options, req_ids) "
            "VALUES (?,?,?,?,?,?)",
            (time.time(), "queued", model_kind, model_label, json.dumps(options), json.dumps(req_ids)),
        )

    def update_run(self, run_id: int, **fields: Any) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        self._x(f"UPDATE runs SET {cols} WHERE id=?", (*fields.values(), run_id))

    def run(self, run_id: int) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM runs WHERE id=?", (run_id,))
        return _run(rows[0]) if rows else None

    def runs(self, limit: int = 50) -> list[dict[str, Any]]:
        return [_run(r) for r in self._q("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]

    def add_event(self, run_id: int, seq: int, payload: dict[str, Any]) -> None:
        self._x(
            "INSERT INTO events(run_id, seq, ts, payload) VALUES (?,?,?,?)",
            (run_id, seq, time.time(), json.dumps(payload)),
        )

    def events(self, run_id: int, after: int = -1) -> list[dict[str, Any]]:
        rows = self._q(
            "SELECT seq, payload FROM events WHERE run_id=? AND seq>? ORDER BY seq", (run_id, after)
        )
        return [{"seq": r["seq"], **json.loads(r["payload"])} for r in rows]

    # -- results
    def add_result(
        self,
        record: dict[str, Any],
        *,
        source: str,
        model_label: str,
        run_id: int | None = None,
        ai_verdict: str | None = None,
        ai_note: str | None = None,
    ) -> int:
        return self._x(
            "INSERT INTO results(run_id, source, model_label, req_id, module, status, created_at, record, "
            "ai_verdict, ai_note) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(source, model_label, req_id) DO UPDATE SET run_id=excluded.run_id, "
            "status=excluded.status, created_at=excluded.created_at, record=excluded.record, "
            "module=excluded.module",
            (
                run_id,
                source,
                model_label,
                record["req_id"],
                record.get("module"),
                record["status"],
                time.time(),
                json.dumps(record),
                ai_verdict,
                ai_note,
            ),
        )

    def results(
        self,
        *,
        req_id: str | None = None,
        status: str | None = None,
        run_id: int | None = None,
        with_record: bool = False,
    ) -> list[dict[str, Any]]:
        where, args = [], []
        for col, val in (("r.req_id", req_id), ("r.status", status), ("r.run_id", run_id)):
            if val is not None:
                where.append(f"{col}=?")
                args.append(val)
        sql = (
            "SELECT r.*, v.verdict, v.note, v.reviewer, v.updated_at AS verdict_at FROM results r "
            "LEFT JOIN verdicts v ON v.result_id = r.id"
            + (" WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY r.created_at DESC, r.id DESC"
        )
        return [_result(r, with_record) for r in self._q(sql, tuple(args))]

    def result(self, result_id: int) -> dict[str, Any] | None:
        rows = self._q(
            "SELECT r.*, v.verdict, v.note, v.reviewer, v.updated_at AS verdict_at FROM results r "
            "LEFT JOIN verdicts v ON v.result_id = r.id WHERE r.id=?",
            (result_id,),
        )
        return _result(rows[0], True) if rows else None

    def set_verdict(self, result_id: int, verdict: str | None, note: str = "", reviewer: str = "") -> None:
        if verdict is None:
            self._x("DELETE FROM verdicts WHERE result_id=?", (result_id,))
            return
        if verdict not in VERDICTS:
            raise ValueError(f"verdict must be one of {VERDICTS}")
        self._x(
            "INSERT INTO verdicts(result_id, verdict, note, reviewer, updated_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(result_id) DO UPDATE SET verdict=excluded.verdict, note=excluded.note, "
            "reviewer=excluded.reviewer, updated_at=excluded.updated_at",
            (result_id, verdict, note, reviewer, time.time()),
        )

    def has_source(self, source: str, model_label: str) -> bool:
        return bool(
            self._q("SELECT 1 FROM results WHERE source=? AND model_label=? LIMIT 1", (source, model_label))
        )


def _run(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    d["options"] = json.loads(d["options"])
    d["req_ids"] = json.loads(d["req_ids"])
    return d


def _result(r: sqlite3.Row, with_record: bool) -> dict[str, Any]:
    d = dict(r)
    rec = json.loads(d.pop("record"))
    d["attempts"] = rec.get("attempts")
    d["wall_seconds"] = rec.get("wall_seconds")
    d["commit"] = rec.get("commit")
    mut = (rec.get("metrics") or {}).get("mutation") or {}
    d["mutants_killed"] = mut.get("killed")
    d["mutants_valid"] = mut.get("valid")
    d["test_names"] = (rec.get("metrics") or {}).get("test_names") or []
    if with_record:
        d["record"] = rec
    return d
