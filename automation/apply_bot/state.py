"""投递状态日志：apply_log.json（每岗位一条，含回执/失败原因）。"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from . import config


def load() -> dict[str, Any]:
    if not config.APPLY_LOG.exists():
        return {"applications": {}}
    try:
        with open(config.APPLY_LOG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"applications": {}}


def save(log: dict[str, Any]) -> None:
    config.ensure_dirs()
    tmp = config.APPLY_LOG.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    os.replace(tmp, config.APPLY_LOG)


def record(
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
) -> dict[str, Any]:
    """status: drafted / filled / submitted / blocked / probe（中途状态见 steps）。

    返回本条记录（供打印）。重复投递同一 公司+岗位 时保留旧的回执，不做覆盖。
    """
    log = load()
    key = f"{company}:{title}"
    entry = {
        "portal": portal,
        "company": company,
        "title": title,
        "url": url,
        "resume": resume,
        "status": status,
        "receipt": receipt,
        "error": error,
        "steps": steps or [],
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    existing = log["applications"].get(key)
    if existing and existing.get("status") == "submitted":
        return existing  # 已提交成功：不再改动
    log["applications"][key] = entry
    save(log)
    try:
        # 同步到网页控制台的 SQLite；JSON 日志仍保留为兼容与灾备来源。
        from . import application_store

        application_store.record_application(
            portal, company, title, url, status, resume=resume, receipt=receipt,
            error=error, steps=steps, created_at=entry["ts"],
        )
    except Exception as e:
        # 投递已经发生时，控制台同步失败不能把外部操作误报成“未投递”。
        entry["dashboard_sync_error"] = str(e)
        log["applications"][key] = entry
        save(log)
    return entry


def is_submitted(portal: str, company: str, title: str) -> bool:
    log = load()
    for key, e in log["applications"].items():
        if e.get("company") == company and e.get("title") == title and e.get("portal") == portal:
            return e.get("status") == "submitted"
    return False
