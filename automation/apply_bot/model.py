"""候选人档案加载与字段取值。纯数据层，不关心站点差异。"""
from __future__ import annotations

import json
import copy
from pathlib import Path
from typing import Any

from . import config


class ProfileError(RuntimeError):
    pass


def load_profile(path: Path | None = None) -> dict[str, Any]:
    p = path or config.PROFILE_JSON
    if not p.exists():
        raise ProfileError(f"profile.json 不存在: {p}（先根据 automation/profile/README.md 生成）")
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    # 用户在本机求职控制台中明确补充的表单事实单独保存，避免自动改写用于
    # 生成简历的叙述性源文件。加载时深度合并，使后续站点适配器立即可用。
    if path is None and config.SUPPLEMENTAL_PROFILE_JSON.exists():
        try:
            with open(config.SUPPLEMENTAL_PROFILE_JSON, encoding="utf-8") as f:
                supplemental_payload = json.load(f)
            data = _deep_merge(data, supplemental_payload.get("fields", {}))
            for field_path, value in supplemental_payload.get("values", {}).items():
                _set_path(data, field_path, value)
        except Exception as e:
            raise ProfileError(f"supplemental_profile.json 无法读取: {e}") from e
    # 红线：无论补充文件内容如何，证件号都不能从磁盘进入自动填表数据。
    data.setdefault("identity", {}).setdefault("id_card", {})["value"] = None
    if "identity" not in data or not data["identity"].get("name"):
        raise ProfileError("profile.json 缺少 identity.name")
    return data


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _set_path(root: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node: Any = root
    for index, part in enumerate(parts[:-1]):
        nxt = parts[index + 1]
        if isinstance(node, list):
            pos = int(part)
            while len(node) <= pos:
                node.append({})
            node = node[pos]
        else:
            if part not in node:
                node[part] = [] if nxt.isdigit() else {}
            node = node[part]
    leaf = parts[-1]
    if isinstance(node, list):
        pos = int(leaf)
        while len(node) <= pos:
            node.append(None)
        node[pos] = value
    else:
        node[leaf] = value


def pick(profile: dict[str, Any], *keys: str, default: Any = None) -> Any:
    node: Any = profile
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return default
        node = node[k]
    return node


def education_lines(profile: dict[str, Any]) -> list[dict[str, str]]:
    """表单「教育经历」通常需要一行一条；这里聚合常见字段。"""
    out: list[dict[str, str]] = []
    for e in profile.get("education", []):
        out.append(
            {
                "school": str(e.get("school", "")),
                "major": str(e.get("major", "")),
                "degree": str(e.get("degree", "")),
                "start": str(e.get("start", "")),
                "end": str(e.get("end", "")),
                "gpa": str(e.get("gpa", "")) if e.get("gpa") else "",
                "ranking": str(e.get("ranking", "")) if e.get("ranking") else "",
            }
        )
    return out


def sensitive_fields(profile: dict[str, Any]) -> list[str]:
    """将被填写/授权写入第三方站点的敏感字段清单（确认关卡展示用）。"""
    seg: list[str] = []
    id_card = profile.get("identity", {}).get("id_card", {})
    if id_card.get("authorized"):
        seg.append("身份证号（本次人工输入，不保存）")
    for k, label in [("phone", "手机号"), ("email", "邮箱"), ("name", "姓名")]:
        if profile.get("identity", {}).get(k):
            seg.append(label)
    return seg
