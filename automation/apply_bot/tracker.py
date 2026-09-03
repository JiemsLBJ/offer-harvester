"""求职追踪表同步：与 /apply 的 job_search_tracker.csv 共用同一表头与语义。"""
from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any

from . import config

HEADER = [
    "date", "company", "sector", "role", "role_type", "channel", "status",
    "contact_person", "fit_rating", "notes", "cv_file", "cover_letter_file",
    "source", "deadline",
]


def _rows(path: Path) -> tuple[list[str], list[list[str]]]:
    if not path.exists():
        return HEADER[:], []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        data = list(reader)
    if not data:
        return HEADER[:], []
    header = data[0]
    if header and header[0].startswith("date"):
        if not header[-1].endswith("deadline"):
            header = header + ["deadline"]
        return header, data[1:]
    return HEADER[:], data


def upsert(
    company: str,
    role: str,
    *,
    portal: str,
    url: str,
    cv_file: str = "",
    cover_letter_file: str = "",
    fit_rating: str = "",
    status: str = "applied",
    deadline: str = "",
    sector: str = "",
    role_type: str = "",
) -> None:
    """按 公司+岗位 大小写不敏感匹配；存在未关闭行则更新，否则追加。

    状态语义沿用 /outcome 的 tracker 词汇表：`applied` 为已投递。
    """
    path = config.TRACKER_CSV
    header, rows = _rows(path)
    today = time.strftime("%Y-%m-%d")

    idx = {name: i for i, name in enumerate(header)}
    marker = (
        "auto-submit" if status == "applied"
        else "auto-draft" if status == "drafted"
        else f"dashboard:{status}"
    )
    key_company = idx["company"]
    key_role = idx["role"]
    match = None
    for row in rows:
        if len(row) <= max(key_company, key_role):
            continue
        if row[key_company].strip().lower() == company.strip().lower() and row[key_role].strip().lower() == role.strip().lower():
            match = row
            break

    def cell(row: list[str], name: str, value: str) -> None:
        i = idx[name]
        while len(row) <= i:
            row.append("")
        row[i] = value

    if match is not None:
        # 更新开放行：不动 date；刷新 source/status；notes 追加未日期标记
        cell(match, "source", url)
        cell(match, "status", status)
        cell(match, "channel", portal)
        if cv_file:
            cell(match, "cv_file", cv_file)
        if cover_letter_file:
            cell(match, "cover_letter_file", cover_letter_file)
        if fit_rating:
            cell(match, "fit_rating", fit_rating)
        if deadline:
            cell(match, "deadline", deadline)
        note = match[idx["notes"]] if len(match) > idx["notes"] else ""
        if marker not in note:
            cell(match, "notes", (note + " " + marker).strip())
        rows = [r for r in rows if r is not match] + [match]
    else:
        new: list[str] = []
        row: dict[str, str] = {
            "date": today, "company": company, "sector": sector, "role": role,
            "role_type": role_type, "channel": portal, "status": status,
            "contact_person": "", "fit_rating": fit_rating,
            "notes": marker,
            "cv_file": cv_file, "cover_letter_file": cover_letter_file, "source": url, "deadline": deadline,
        }
        for name in header:
            new.append(row.get(name, ""))
        rows.append(new)

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
