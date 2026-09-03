"""Application-material safeguards: current template checks and exact upload names."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from . import config


class MaterialError(RuntimeError):
    """Raised before a stale or incorrectly named resume can be uploaded."""


CURRENT_TEMPLATE = "onepagecv-v1"
_INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SUPPORTED_SUFFIXES = {".pdf", ".doc", ".docx"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_upload_filename(requested_name: str, source_suffix: str) -> str:
    """Return a safe filename whose basename is exactly what the portal will see."""
    name = requested_name.strip()
    if not name:
        raise MaterialError("岗位指定的简历文件名不能为空")
    if _INVALID_WINDOWS_CHARS.search(name) or name in {".", ".."}:
        raise MaterialError(f"简历文件名包含路径或 Windows 非法字符: {requested_name}")
    if name.endswith((" ", ".")):
        raise MaterialError("简历文件名不能以空格或句点结尾")
    if len(name) > 200:
        raise MaterialError("简历文件名超过 200 个字符，请先按招聘方要求缩短")

    suffix = source_suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise MaterialError(f"不支持的简历格式: {source_suffix}")
    requested_suffix = Path(name).suffix.lower()
    if not requested_suffix:
        name += suffix
    elif requested_suffix != suffix:
        raise MaterialError(
            f"指定文件名扩展名 {requested_suffix} 与源简历 {suffix} 不一致；不会伪装文件格式"
        )
    return name


def template_provenance(path: Path) -> dict[str, str | None]:
    """Inspect the sibling TeX source when this is a project-generated resume."""
    resolved = path.resolve()
    tex = resolved if resolved.suffix.lower() == ".tex" else resolved.with_suffix(".tex")
    if not tex.is_file():
        return {"template": None, "source_tex": None}
    source = tex.read_text(encoding="utf-8", errors="replace")
    if "\\usepackage{onepagecv}" in source:
        template = CURRENT_TEMPLATE
    elif "\\documentclass" in source and "moderncv" in source:
        template = "legacy-moderncv"
    else:
        template = "unknown-project-template"
    return {"template": template, "source_tex": str(tex)}


def require_current_project_template(path: Path) -> dict[str, str | None]:
    """Reject a known legacy project CV; user-supplied PDFs without TeX remain allowed."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise MaterialError(f"简历文件不存在: {resolved}")
    if resolved.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise MaterialError(f"简历文件格式不支持: {resolved.suffix}")
    provenance = template_provenance(resolved)
    if provenance["template"] == "legacy-moderncv":
        raise MaterialError(
            f"检测到旧版 moderncv 简历，禁止继续复用: {resolved.name}。请用 onepagecv 单页模板重新生成。"
        )
    if provenance["template"] == "unknown-project-template":
        raise MaterialError(
            f"项目简历没有使用当前 onepagecv 模板: {resolved.name}。请先按现行模板重新生成。"
        )
    return provenance


def prepare_upload_file(source: Path, requested_name: str | None = None) -> Path:
    """Validate a resume and, when required, make an auditable exact-name copy."""
    resolved = source.resolve()
    provenance = require_current_project_template(resolved)
    if not requested_name:
        return resolved

    filename = validate_upload_filename(requested_name, resolved.suffix)
    if filename == resolved.name:
        return resolved

    digest = _sha256(resolved)
    target_dir = config.STATE_DIR / "named_uploads" / digest[:12]
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename
    if not target.is_file() or _sha256(target) != digest:
        shutil.copy2(resolved, target)
    if target.name != filename or _sha256(target) != digest:
        raise MaterialError("简历重命名副本校验失败，已停止上传")

    audit = {
        "schema_version": "1.0.0",
        "source": str(resolved),
        "source_sha256": digest,
        "upload_path": str(target.resolve()),
        "upload_filename": filename,
        "template": provenance["template"],
        "source_tex": provenance["source_tex"],
    }
    target.with_suffix(target.suffix + ".upload.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target.resolve()
