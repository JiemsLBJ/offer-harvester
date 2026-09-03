"""本机求职控制台的持久化数据层。

SQLite 是网页和投递机器人共享的结构化事实源。现有 apply_log.json 与
job_search_tracker.csv 会在控制台启动时导入，但不会被删除或覆盖。
"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from . import config


STATUS_ORDER = {
    "discovered": 0,
    "drafted": 1,
    "blocked": 1,
    "filled": 2,
    "cancelled": 2,
    "applied": 3,
    "interview": 4,
    "offer": 5,
    "hired": 6,
    "rejected": 6,
    "no_response": 6,
    "offer_declined": 6,
    "withdrawn": 6,
}
FINAL_STATUSES = {"hired", "rejected", "no_response", "offer_declined", "withdrawn"}
STATUS_ALIASES = {
    "probe": "discovered",
    "new": "discovered",
    "drafting": "drafted",
    "submitted": "applied",
    "screening": "interview",
    "closed": "withdrawn",
}


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def normalize_status(value: str | None) -> str:
    raw = (value or "discovered").strip().lower()
    return STATUS_ALIASES.get(raw, raw if raw in STATUS_ORDER else "discovered")


def stable_application_id(portal: str, company: str, title: str, url: str) -> str:
    identity = url.strip().lower().rstrip("/") or f"{portal}|{company}|{title}".lower()
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or config.APPLICATION_DB
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS applications (
          id TEXT PRIMARY KEY,
          portal TEXT NOT NULL DEFAULT '',
          company TEXT NOT NULL,
          title TEXT NOT NULL,
          url TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'discovered',
          sector TEXT NOT NULL DEFAULT '',
          role_type TEXT NOT NULL DEFAULT '',
          location TEXT NOT NULL DEFAULT '',
          work_mode TEXT NOT NULL DEFAULT '',
          fit_rating TEXT NOT NULL DEFAULT '',
          deadline TEXT NOT NULL DEFAULT '',
          contact_person TEXT NOT NULL DEFAULT '',
          next_action TEXT NOT NULL DEFAULT '',
          next_action_date TEXT NOT NULL DEFAULT '',
          notes TEXT NOT NULL DEFAULT '',
          tags_json TEXT NOT NULL DEFAULT '[]',
          resume TEXT NOT NULL DEFAULT '',
          cover_letter TEXT NOT NULL DEFAULT '',
          receipt TEXT NOT NULL DEFAULT '',
          error TEXT NOT NULL DEFAULT '',
          steps_json TEXT NOT NULL DEFAULT '[]',
          applied_at TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS status_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          application_id TEXT NOT NULL,
          from_status TEXT NOT NULL DEFAULT '',
          to_status TEXT NOT NULL,
          note TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          FOREIGN KEY(application_id) REFERENCES applications(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS form_requirements (
          id TEXT PRIMARY KEY,
          portal TEXT NOT NULL,
          field_key TEXT NOT NULL,
          label TEXT NOT NULL,
          data_type TEXT NOT NULL DEFAULT 'text',
          required INTEGER NOT NULL DEFAULT 0,
          sensitive INTEGER NOT NULL DEFAULT 0,
          profile_path TEXT NOT NULL DEFAULT '',
          resolution_status TEXT NOT NULL DEFAULT 'observed',
          occurrences INTEGER NOT NULL DEFAULT 0,
          first_seen TEXT NOT NULL,
          last_seen TEXT NOT NULL,
          selector_meta_json TEXT NOT NULL DEFAULT '{}',
          sample_context_json TEXT NOT NULL DEFAULT '[]',
          last_issue TEXT NOT NULL DEFAULT ''
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS requirement_observations (
          application_id TEXT NOT NULL,
          requirement_id TEXT NOT NULL,
          outcome TEXT NOT NULL DEFAULT 'observed',
          observed_at TEXT NOT NULL,
          PRIMARY KEY(application_id, requirement_id),
          FOREIGN KEY(application_id) REFERENCES applications(id) ON DELETE CASCADE,
          FOREIGN KEY(requirement_id) REFERENCES form_requirements(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS source_runs (
          id TEXT PRIMARY KEY,
          portal TEXT NOT NULL,
          status TEXT NOT NULL,
          mode TEXT NOT NULL DEFAULT '',
          keyword TEXT NOT NULL DEFAULT '',
          location TEXT NOT NULL DEFAULT '',
          discovered_count INTEGER NOT NULL DEFAULT 0,
          new_count INTEGER NOT NULL DEFAULT 0,
          entry_url TEXT NOT NULL DEFAULT '',
          message TEXT NOT NULL DEFAULT '',
          started_at TEXT NOT NULL,
          finished_at TEXT NOT NULL,
          details_json TEXT NOT NULL DEFAULT '{}'
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_applications_status_updated ON applications(status, updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_applications_portal ON applications(portal)",
        "CREATE INDEX IF NOT EXISTS idx_status_events_application ON status_events(application_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_requirements_resolution ON form_requirements(resolution_status, required)",
        "CREATE INDEX IF NOT EXISTS idx_source_runs_portal_finished ON source_runs(portal, finished_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_source_runs_finished ON source_runs(finished_at DESC)",
    ]
    for statement in statements:
        conn.execute(statement)
    conn.execute("PRAGMA optimize")
    conn.commit()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _decode_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for source, target, fallback in [
        ("tags_json", "tags", []),
        ("steps_json", "steps", []),
        ("sample_context_json", "sample_context", []),
        ("selector_meta_json", "selector_meta", {}),
        ("details_json", "details", {}),
    ]:
        if source in out:
            try:
                out[target] = json.loads(out.pop(source) or _json(fallback))
            except Exception:
                out[target] = fallback
    for key in ("required", "sensitive"):
        if key in out:
            out[key] = bool(out[key])
    return out


def record_source_run(run: dict[str, Any], db_path: Path | None = None) -> dict[str, Any]:
    """记录一次岗位来源抓取；同一事件 ID 可安全重复导入。"""
    stamp = str(run.get("finished_at") or now())
    run_id = str(run.get("id") or hashlib.sha256(
        f"{run.get('portal')}|{run.get('started_at')}|{stamp}|{run.get('keyword')}".encode("utf-8")
    ).hexdigest()[:24])
    values = {
        "id": run_id,
        "portal": str(run.get("portal") or "other"),
        "status": str(run.get("status") or "error"),
        "mode": str(run.get("mode") or ""),
        "keyword": str(run.get("keyword") or ""),
        "location": str(run.get("location") or ""),
        "discovered_count": max(0, int(run.get("discovered_count") or 0)),
        "new_count": max(0, int(run.get("new_count") or 0)),
        "entry_url": str(run.get("entry_url") or ""),
        "message": str(run.get("message") or ""),
        "started_at": str(run.get("started_at") or stamp),
        "finished_at": stamp,
        "details_json": _json(run.get("details") if isinstance(run.get("details"), dict) else {}),
    }
    with connect(db_path) as conn:
        columns = list(values)
        conn.execute(
            f"INSERT INTO source_runs ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
            "ON CONFLICT(id) DO NOTHING",
            tuple(values[column] for column in columns),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM source_runs WHERE id = ?", (run_id,)).fetchone()
        return _decode_row(row)


def list_source_runs(limit: int = 100, db_path: Path | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM source_runs ORDER BY finished_at DESC LIMIT ?", (max(1, min(limit, 1000)),)
        ).fetchall()
        return [_decode_row(row) for row in rows]


def record_application(
    portal: str,
    company: str,
    title: str,
    url: str,
    status: str,
    *,
    resume: str | None = None,
    receipt: str | None = None,
    error: str | None = None,
    steps: list[str] | None = None,
    created_at: str | None = None,
    db_path: Path | None = None,
    **details: Any,
) -> dict[str, Any]:
    app_id = stable_application_id(portal, company, title, url)
    incoming = normalize_status(status)
    stamp = details.pop("updated_at", None) or now()
    with connect(db_path) as conn:
        old = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
        old_status = old["status"] if old else ""
        effective = incoming
        if old_status in FINAL_STATUSES or STATUS_ORDER.get(old_status, 0) > STATUS_ORDER.get(incoming, 0):
            effective = old_status
        created = old["created_at"] if old else (created_at or stamp)
        applied_at = (old["applied_at"] if old else "") or (stamp if effective == "applied" else "")
        values = {
            "id": app_id,
            "portal": portal,
            "company": company or "(未知公司)",
            "title": title or "(未知岗位)",
            "url": url or "",
            "status": effective,
            "sector": details.get("sector", old["sector"] if old else "") or "",
            "role_type": details.get("role_type", old["role_type"] if old else "") or "",
            "location": details.get("location", old["location"] if old else "") or "",
            "work_mode": details.get("work_mode", old["work_mode"] if old else "") or "",
            "fit_rating": str(details.get("fit_rating", old["fit_rating"] if old else "") or ""),
            "deadline": details.get("deadline", old["deadline"] if old else "") or "",
            "contact_person": details.get("contact_person", old["contact_person"] if old else "") or "",
            "next_action": details.get("next_action", old["next_action"] if old else "") or "",
            "next_action_date": details.get("next_action_date", old["next_action_date"] if old else "") or "",
            "notes": details.get("notes", old["notes"] if old else "") or "",
            "tags_json": _json(details.get("tags", json.loads(old["tags_json"]) if old else [])),
            "resume": resume if resume is not None else (old["resume"] if old else ""),
            "cover_letter": details.get("cover_letter", old["cover_letter"] if old else "") or "",
            "receipt": receipt if receipt is not None else (old["receipt"] if old else ""),
            "error": error if error is not None else (old["error"] if old else ""),
            "steps_json": _json(steps if steps is not None else (json.loads(old["steps_json"]) if old else [])),
            "applied_at": applied_at,
            "created_at": created,
            "updated_at": stamp,
        }
        columns = list(values)
        conn.execute(
            f"INSERT INTO applications ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
            f"ON CONFLICT(id) DO UPDATE SET {','.join(f'{c}=excluded.{c}' for c in columns if c != 'id')}",
            tuple(values[c] for c in columns),
        )
        if not old or old_status != effective:
            conn.execute(
                "INSERT INTO status_events(application_id, from_status, to_status, note, created_at) VALUES(?,?,?,?,?)",
                (app_id, old_status, effective, details.get("event_note", ""), stamp),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
        return _decode_row(row)


EDITABLE_FIELDS = {
    "status", "sector", "role_type", "location", "work_mode", "fit_rating", "deadline",
    "contact_person", "next_action", "next_action_date", "notes", "tags",
}


def update_application(app_id: str, changes: dict[str, Any], db_path: Path | None = None) -> dict[str, Any] | None:
    clean = {k: v for k, v in changes.items() if k in EDITABLE_FIELDS}
    if not clean:
        return get_application(app_id, db_path)
    with connect(db_path) as conn:
        old = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
        if old is None:
            return None
        old_status = old["status"]
        if "status" in clean:
            clean["status"] = normalize_status(str(clean["status"]))
        if "tags" in clean:
            clean["tags_json"] = _json(clean.pop("tags") if isinstance(clean["tags"], list) else [])
        clean["updated_at"] = now()
        assignments = ",".join(f"{key} = ?" for key in clean)
        conn.execute(f"UPDATE applications SET {assignments} WHERE id = ?", (*clean.values(), app_id))
        if clean.get("status") and clean["status"] != old_status:
            if clean["status"] == "applied" and not old["applied_at"]:
                conn.execute("UPDATE applications SET applied_at = ? WHERE id = ?", (clean["updated_at"], app_id))
            conn.execute(
                "INSERT INTO status_events(application_id, from_status, to_status, note, created_at) VALUES(?,?,?,?,?)",
                (app_id, old_status, clean["status"], "网页更新", clean["updated_at"]),
            )
        conn.commit()
    return get_application(app_id, db_path)


def get_application(app_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
        if row is None:
            return None
        out = _decode_row(row)
        events = conn.execute(
            "SELECT from_status, to_status, note, created_at FROM status_events WHERE application_id = ? ORDER BY id",
            (app_id,),
        ).fetchall()
        out["events"] = [dict(e) for e in events]
        return out


def list_applications(db_path: Path | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM applications ORDER BY CASE status "
            "WHEN 'offer' THEN 0 WHEN 'interview' THEN 1 WHEN 'applied' THEN 2 "
            "WHEN 'filled' THEN 3 WHEN 'blocked' THEN 4 ELSE 5 END, updated_at DESC"
        ).fetchall()
        return [_decode_row(row) for row in rows]


def list_requirements(db_path: Path | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM form_requirements ORDER BY "
            "CASE resolution_status WHEN 'missing' THEN 0 WHEN 'unmapped' THEN 1 WHEN 'manual_sensitive' THEN 2 ELSE 3 END, "
            "required DESC, occurrences DESC, last_seen DESC"
        ).fetchall()
        return [_decode_row(row) for row in rows]


def dashboard_payload(db_path: Path | None = None) -> dict[str, Any]:
    applications = list_applications(db_path)
    requirements = list_requirements(db_path)
    counts: dict[str, int] = {}
    portals: dict[str, int] = {}
    for app in applications:
        counts[app["status"]] = counts.get(app["status"], 0) + 1
        portals[app["portal"] or "other"] = portals.get(app["portal"] or "other", 0) + 1
    activity: dict[str, int] = {}
    with connect(db_path) as conn:
        for row in conn.execute(
            "SELECT substr(created_at,1,10) AS day, count(*) AS total FROM status_events "
            "GROUP BY substr(created_at,1,10) ORDER BY day DESC LIMIT 14"
        ):
            activity[row["day"]] = row["total"]
    return {
        "applications": applications,
        "requirements": requirements,
        "summary": {
            "total": len(applications),
            "active": sum(counts.get(s, 0) for s in ("filled", "blocked", "applied", "interview", "offer")),
            "applied": counts.get("applied", 0),
            "interview": counts.get("interview", 0),
            "offer": counts.get("offer", 0),
            "missing_fields": sum(1 for r in requirements if r["resolution_status"] in {"missing", "unmapped"}),
            "status_counts": counts,
            "portal_counts": portals,
            "activity": [{"date": day, "count": activity[day]} for day in sorted(activity)],
        },
    }


def import_existing_sources(db_path: Path | None = None) -> dict[str, int]:
    imported_log = 0
    imported_tracker = 0
    imported_seen = 0
    if config.SEEN_JOBS_JSON.exists():
        try:
            payload = json.loads(config.SEEN_JOBS_JSON.read_text(encoding="utf-8"))
            for key, entry in payload.get("seen", {}).items():
                if not isinstance(entry, dict) or not entry.get("url"):
                    continue
                portal = str(entry.get("portal") or str(key).split(":", 1)[0])
                portal = portal.removesuffix("-search")
                first_seen = str(entry.get("first_seen") or now())
                if len(first_seen) == 10:
                    first_seen += " 00:00:00"
                record_application(
                    portal,
                    str(entry.get("company") or ""),
                    str(entry.get("title") or ""),
                    str(entry.get("url") or ""),
                    "discovered",
                    created_at=first_seen,
                    location=str(entry.get("location") or ""),
                    fit_rating=str(entry.get("fit") or ""),
                    deadline=str(entry.get("deadline") or ""),
                    db_path=db_path,
                )
                imported_seen += 1
        except Exception:
            pass
    if config.APPLY_LOG.exists():
        try:
            payload = json.loads(config.APPLY_LOG.read_text(encoding="utf-8"))
            for entry in payload.get("applications", {}).values():
                record_application(
                    str(entry.get("portal") or ""), str(entry.get("company") or ""),
                    str(entry.get("title") or ""), str(entry.get("url") or ""),
                    str(entry.get("status") or "discovered"), resume=entry.get("resume"),
                    receipt=entry.get("receipt"), error=entry.get("error"),
                    steps=entry.get("steps") or [], created_at=entry.get("ts"), db_path=db_path,
                )
                imported_log += 1
        except Exception:
            pass
    if config.TRACKER_CSV.exists():
        try:
            with open(config.TRACKER_CSV, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    if not row.get("company") or not row.get("role"):
                        continue
                    record_application(
                        row.get("channel", ""), row["company"], row["role"], row.get("source", ""),
                        row.get("status", "discovered"), resume=row.get("cv_file"),
                        created_at=(row.get("date") or now()) + (" 00:00:00" if len(row.get("date", "")) == 10 else ""),
                        sector=row.get("sector", ""), role_type=row.get("role_type", ""),
                        fit_rating=row.get("fit_rating", ""), deadline=row.get("deadline", ""),
                        contact_person=row.get("contact_person", ""), notes=row.get("notes", ""),
                        cover_letter=row.get("cover_letter_file", ""), db_path=db_path,
                    )
                    imported_tracker += 1
        except Exception:
            pass
    return {"seen_jobs": imported_seen, "apply_log": imported_log, "tracker": imported_tracker}
