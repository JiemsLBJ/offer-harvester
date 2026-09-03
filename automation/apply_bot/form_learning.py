"""跨站表单学习、资料缺口归档与已确认字段的通用回填。

只保存字段结构与用户明确确认的补充资料；探路快照不读取 input.value，身份证号
永不写入补充档案、数据库或日志。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from . import application_store, config, model


FIELD_RULES: list[tuple[str, str, str]] = [
    (r"身份证|证件号码|证件号|id\s*(?:card|number)|identity", "identity.id_card.value", "sensitive"),
    (r"姓名|真实姓名|^name$|full[\s_-]*name", "identity.name", "text"),
    (r"手机|电话|mobile|phone", "identity.phone", "tel"),
    (r"邮箱|email|e-mail", "identity.email", "email"),
    (r"性别|gender", "identity.gender", "choice"),
    (r"出生|生日|birth", "identity.birthday", "date"),
    (r"微信|wechat", "identity.wechat", "text"),
    (r"籍贯|生源地|家乡|hometown", "identity.hometown", "text"),
    (r"现居|当前所在地|居住地|current\s*location", "identity.location", "text"),
    (r"政治面貌|political", "form_answers.political_status", "choice"),
    (r"民族|ethnicity", "form_answers.ethnicity", "choice"),
    (r"婚姻|marital", "form_answers.marital_status", "choice"),
    (r"户口|户籍|household", "form_answers.household_registration", "text"),
    (r"学校|院校|university|college", "education.0.school", "text"),
    (r"专业证书|职业资格|证书(?:名称|等级|状态)|professional\s*certificate|certification",
     "form_answers.professional_certificates", "text"),
    (r"专业|major", "education.0.major", "text"),
    (r"最高学历|学历|education\s*level", "education.0.level", "choice"),
    (r"学位|degree", "education.0.degree", "choice"),
    (r"毕业时间|毕业日期|graduation", "education.0.end", "date"),
    (r"入学时间|入学日期|education\s*start", "education.0.start", "date"),
    (r"gpa|绩点", "education.0.gpa", "text"),
    (r"排名|rank", "education.0.ranking", "text"),
    (r"到岗|入职时间|available|start\s*date", "availability.start_date", "choice"),
    (r"实习时长|实习周期|可实习.*月|duration", "availability.min_months", "number"),
    (r"每周.*天|出勤|days.*week", "availability.days_per_week", "number"),
    (r"期望城市|工作地点|城市|location", "availability.cities.0", "choice"),
    (r"期望薪资|日薪|薪资要求|salary", "salary_expectation.min_daily_cny", "number"),
    (r"自我评价|自我介绍|个人介绍|summary|introduction", "self_intro.zh_200", "textarea"),
    (r"照片|证件照|头像|photo", "identity.photo_path", "file"),
]
SKIP_PATTERNS = re.compile(r"搜索|验证码|密码|登录|keyword|search|captcha|verification|password", re.I)
FORBIDDEN_PATHS = ("identity.id_card",)


def _stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _clean_label(item: dict[str, Any]) -> str:
    candidates = [item.get("aria-label"), item.get("placeholder"), item.get("label"), item.get("name"), item.get("id")]
    for candidate in candidates:
        value = re.sub(r"\s+", " ", str(candidate or "")).strip(" *：:")
        if value:
            return value[:80]
    return "未命名字段"


def _field_key(label: str) -> str:
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "_", label.lower()).strip("_")
    return normalized[:72] or hashlib.sha256(label.encode("utf-8")).hexdigest()[:16]


def infer_profile_path(label: str) -> tuple[str, str, bool]:
    for pattern, path, data_type in FIELD_RULES:
        if re.search(pattern, label, re.I):
            return path, data_type, data_type == "sensitive"
    return "", "text", False


def profile_value(profile: dict[str, Any], path: str) -> Any:
    if not path:
        return None
    node: Any = profile
    try:
        for part in path.split("."):
            node = node[int(part)] if isinstance(node, list) else node[part]
        return node
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _has_value(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _requirement_id(portal: str, field_key: str) -> str:
    return hashlib.sha256(f"{portal}|{field_key}".encode("utf-8")).hexdigest()[:20]


def learn_snapshot(
    snapshot: dict[str, Any], *, portal: str, url: str, company: str = "", title: str = "",
    profile: dict[str, Any] | None = None, issues: list[str] | None = None,
    db_path: Path | None = None,
) -> dict[str, int]:
    profile = profile or model.load_profile()
    app_id = application_store.stable_application_id(portal, company, title, url)
    observed: list[tuple[dict[str, Any], str]] = []
    for item in snapshot.get("inputs", []):
        if not item.get("visible") or item.get("type") in {"hidden", "button", "submit", "password"}:
            continue
        label = _clean_label(item)
        if SKIP_PATTERNS.search(label):
            continue
        observed.append((item, ""))
    for issue in issues or []:
        observed.append(({"label": issue[:80], "visible": True, "issue": issue[:240]}, issue[:240]))

    learned = missing = unmapped = 0
    with application_store.connect(db_path) as conn:
        app_exists = bool(conn.execute("SELECT 1 FROM applications WHERE id = ?", (app_id,)).fetchone())
        for item, issue in observed:
            label = _clean_label(item)
            key = _field_key(label)
            req_id = _requirement_id(portal, key)
            path, inferred_type, sensitive = infer_profile_path(label)
            required = bool(item.get("required") is not None or item.get("aria-required") == "true" or "*" in str(item.get("label") or "") or issue)
            data_type = item.get("type") or inferred_type
            if sensitive:
                resolution = "manual_sensitive"
                path = ""
            elif path and _has_value(profile_value(profile, path)):
                resolution = "covered"
            elif path:
                resolution = "missing"
                missing += 1
            elif required:
                resolution = "unmapped"
                unmapped += 1
            else:
                resolution = "observed"
            existing = conn.execute("SELECT * FROM form_requirements WHERE id = ?", (req_id,)).fetchone()
            if existing and existing["resolution_status"] in {"manual", "ignored", "covered"}:
                resolution = existing["resolution_status"]
                path = existing["profile_path"] or path
            contexts = json.loads(existing["sample_context_json"]) if existing else []
            context = {"company": company, "title": title, "url": url}
            if context not in contexts:
                contexts = (contexts + [context])[-8:]
            meta = {k: v for k, v in item.items() if k not in {"label", "issue"} and v not in (None, "")}
            conn.execute(
                """INSERT INTO form_requirements(
                     id, portal, field_key, label, data_type, required, sensitive, profile_path,
                     resolution_status, occurrences, first_seen, last_seen, selector_meta_json,
                     sample_context_json, last_issue
                   ) VALUES(?,?,?,?,?,?,?,?,?,0,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     label=excluded.label, data_type=excluded.data_type,
                     required=max(form_requirements.required, excluded.required),
                     sensitive=max(form_requirements.sensitive, excluded.sensitive),
                     profile_path=CASE WHEN form_requirements.profile_path='' THEN excluded.profile_path ELSE form_requirements.profile_path END,
                     resolution_status=excluded.resolution_status, last_seen=excluded.last_seen,
                     selector_meta_json=excluded.selector_meta_json,
                     sample_context_json=excluded.sample_context_json,
                     last_issue=CASE WHEN excluded.last_issue='' THEN form_requirements.last_issue ELSE excluded.last_issue END""",
                (req_id, portal, key, label, str(data_type), int(required), int(sensitive), path, resolution,
                 _stamp(), _stamp(), json.dumps(meta, ensure_ascii=False), json.dumps(contexts, ensure_ascii=False), issue),
            )
            if app_exists:
                conn.execute(
                    "INSERT INTO requirement_observations(application_id, requirement_id, outcome, observed_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(application_id, requirement_id) DO UPDATE SET outcome=excluded.outcome, observed_at=excluded.observed_at",
                    (app_id, req_id, resolution, _stamp()),
                )
                count = conn.execute(
                    "SELECT count(*) FROM requirement_observations WHERE requirement_id = ?", (req_id,)
                ).fetchone()[0]
                conn.execute("UPDATE form_requirements SET occurrences = ? WHERE id = ?", (count, req_id))
            learned += 1
        conn.commit()
    return {"learned": learned, "missing": missing, "unmapped": unmapped}


def save_profile_answer(requirement_id: str, profile_path: str, value: Any, db_path: Path | None = None) -> None:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*(?:\.(?:[a-z_][a-z0-9_]*|\d+))*", profile_path):
        raise ValueError("档案路径格式无效")
    if any(profile_path.startswith(prefix) for prefix in FORBIDDEN_PATHS):
        raise ValueError("身份证号禁止保存；该字段只能在单次投递确认时人工输入")
    if value in (None, "", []):
        raise ValueError("补充内容不能为空")
    with application_store.connect(db_path) as conn:
        req = conn.execute("SELECT sensitive, label FROM form_requirements WHERE id = ?", (requirement_id,)).fetchone()
        if req is None:
            raise ValueError("字段要求不存在")
        if req["sensitive"]:
            raise ValueError("该敏感字段禁止持久化")

    path = config.SUPPLEMENTAL_PROFILE_JSON
    payload: dict[str, Any] = {"schema_version": "1.0.0", "source": "用户通过本机求职控制台明确补充", "values": {}}
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("values", {})[profile_path] = value
    payload["updated"] = time.strftime("%Y-%m-%d")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)

    # 审计日志只记录路径和时间，不复制个人字段值。
    audit = {"updates": []}
    if config.PROFILE_UPDATE_LOG.exists():
        try:
            audit = json.loads(config.PROFILE_UPDATE_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    audit.setdefault("updates", []).append({"requirement_id": requirement_id, "profile_path": profile_path, "ts": _stamp()})
    config.PROFILE_UPDATE_LOG.parent.mkdir(parents=True, exist_ok=True)
    config.PROFILE_UPDATE_LOG.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with application_store.connect(db_path) as conn:
        conn.execute(
            "UPDATE form_requirements SET profile_path=?, resolution_status='covered', last_seen=? WHERE id=?",
            (profile_path, _stamp(), requirement_id),
        )
        conn.commit()


def resolve_requirement(requirement_id: str, action: str, *, profile_path: str = "", value: Any = None,
                        db_path: Path | None = None) -> dict[str, Any]:
    if action == "save":
        save_profile_answer(requirement_id, profile_path, value, db_path)
    elif action in {"manual", "ignored", "missing"}:
        with application_store.connect(db_path) as conn:
            conn.execute("UPDATE form_requirements SET resolution_status=?, last_seen=? WHERE id=?", (action, _stamp(), requirement_id))
            conn.commit()
    else:
        raise ValueError("未知处理动作")
    with application_store.connect(db_path) as conn:
        row = conn.execute("SELECT * FROM form_requirements WHERE id = ?", (requirement_id,)).fetchone()
        if row is None:
            raise ValueError("字段要求不存在")
        return application_store._decode_row(row)


def fill_learned_fields(page: Any, portal: str, profile: dict[str, Any], db_path: Path | None = None) -> list[str]:
    """只填档案中已有且当前为空的普通输入框，绝不覆盖站点已有值。

    先复用同站已学习的稳定选择器，再对当前页面做一次纯结构推断。后者让用户刚在
    控制台补齐的字段也能用于一个此前从未见过的新公司表单。
    """
    filled: list[str] = []
    with application_store.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT label, profile_path, data_type, selector_meta_json FROM form_requirements "
            "WHERE portal=? AND resolution_status='covered' AND sensitive=0 AND profile_path!=''",
            (portal,),
        ).fetchall()
    for row in rows:
        value = profile_value(profile, row["profile_path"])
        if not _has_value(value) or isinstance(value, (dict, list)):
            continue
        meta = json.loads(row["selector_meta_json"] or "{}")
        if _fill_from_meta(page, meta, value):
            filled.append(str(row["label"]))

    # 新站点首次出现的字段也按当前可见静态标签推断；敏感字段和列表/对象不参与。
    try:
        from .portals.base import dump_form_snapshot

        snapshot = dump_form_snapshot(page)
        for item in snapshot.get("inputs", []):
            if not item.get("visible"):
                continue
            label = _clean_label(item)
            path, _, sensitive = infer_profile_path(label)
            value = profile_value(profile, path)
            if sensitive or not path or not _has_value(value) or isinstance(value, (dict, list)):
                continue
            if _fill_from_meta(page, item, value):
                filled.append(label)
    except Exception:
        pass
    return list(dict.fromkeys(filled))


def _fill_from_meta(page: Any, meta: dict[str, Any], value: Any) -> bool:
    locator = None
    for attr in ("id", "name", "placeholder", "aria-label"):
        raw = meta.get(attr)
        if not raw:
            continue
        escaped = str(raw).replace("\\", "\\\\").replace('"', '\\"')
        candidate = page.locator(
            f'input[{attr}="{escaped}"],textarea[{attr}="{escaped}"],select[{attr}="{escaped}"]'
        ).first
        if candidate.count():
            locator = candidate
            break
    if locator is None:
        return False
    try:
        if not locator.is_visible() or locator.is_disabled():
            return False
        tag = locator.evaluate("el => el.tagName.toLowerCase()")
        kind = (locator.get_attribute("type") or "").lower()
        if kind in {"file", "radio", "checkbox", "password", "hidden"}:
            return False
        if tag == "select":
            locator.select_option(label=str(value))
        else:
            if locator.input_value().strip():
                return False
            locator.fill(str(value))
        return True
    except Exception:
        return False


def import_historical_snapshots(db_path: Path | None = None) -> dict[str, int]:
    """把既有校验问题和 probe 文件补入学习库，便于控制台首次启动即显示缺口。"""
    learned_runs = 0
    learned_fields = 0
    profile = model.load_profile()
    if config.APPLY_LOG.exists():
        try:
            payload = json.loads(config.APPLY_LOG.read_text(encoding="utf-8"))
            for entry in payload.get("applications", {}).values():
                issues: list[str] = []
                for step in entry.get("steps") or []:
                    if str(step).startswith("校验:"):
                        issues.extend(x.strip() for x in str(step)[3:].split(";") if x.strip())
                if not issues:
                    continue
                result = learn_snapshot(
                    {"inputs": []}, portal=str(entry.get("portal") or "unknown"),
                    url=str(entry.get("url") or ""), company=str(entry.get("company") or ""),
                    title=str(entry.get("title") or ""), profile=profile, issues=issues, db_path=db_path,
                )
                learned_runs += 1
                learned_fields += result["learned"]
        except Exception:
            pass
    for probe_path in config.STATE_DIR.glob("probe_*.json"):
        try:
            payload = json.loads(probe_path.read_text(encoding="utf-8"))
            snapshot = payload.get("snapshot") or {}
            portal = str(payload.get("portal") or probe_path.stem.removeprefix("probe_"))
            result = learn_snapshot(
                snapshot, portal=portal, url=str(payload.get("url") or snapshot.get("url") or ""),
                profile=profile, issues=[str(payload.get("reason"))] if payload.get("reason") else [],
                db_path=db_path,
            )
            learned_runs += 1
            learned_fields += result["learned"]
        except Exception:
            continue
    return {"runs": learned_runs, "fields": learned_fields}
