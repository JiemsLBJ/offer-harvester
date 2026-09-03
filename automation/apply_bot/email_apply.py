"""图片/帖子来源岗位的安全邮件投递草稿与单封确认发送。

默认行为只生成本地 ``.eml``、结构化清单和浏览器预览。QQ SMTP 发送需要：
1. 草稿仍处于 drafted；2. 环境变量中存在授权码；3. 用户输入本草稿的精确确认口令。
授权码不会进入命令行参数、草稿、日志或追踪表。
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import mimetypes
import os
import re
import shutil
import smtplib
import sys
import time
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Callable, Mapping

from . import config, materials, model, state, tracker


QQ_SMTP_HOST = "smtp.qq.com"
QQ_SMTP_PORT = 465
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
PUBLIC_EMAIL_DOMAINS = {
    "gmail.com", "qq.com", "foxmail.com", "163.com", "126.com",
    "outlook.com", "hotmail.com", "yahoo.com",
}


class EmailApplicationError(RuntimeError):
    pass


class SendCancelled(EmailApplicationError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_header(value: str, label: str) -> str:
    clean = value.strip()
    if not clean:
        raise EmailApplicationError(f"{label}不能为空")
    if "\r" in clean or "\n" in clean:
        raise EmailApplicationError(f"{label}包含非法换行")
    return clean


def validate_single_recipient(value: str) -> str:
    recipient = _clean_header(value, "收件人")
    if any(separator in recipient for separator in (",", ";")):
        raise EmailApplicationError("首版仅允许一个收件人，不支持群发、抄送或密送")
    display, address = parseaddr(recipient)
    if display or address != recipient:
        raise EmailApplicationError("收件人必须是单个纯邮箱地址")
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", address):
        raise EmailApplicationError(f"邮箱格式无效: {recipient}")
    return address.lower()


def _file_meta(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise EmailApplicationError(f"文件不存在: {resolved}")
    return {
        "name": resolved.name,
        "path": str(resolved),
        "size": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def _risk_flags(
    company: str,
    recipient: str,
    source_images: list[dict[str, Any]],
    source_url: str,
    custom_risk_notes: list[str] | None = None,
) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    domain = recipient.rsplit("@", 1)[-1]
    if domain in PUBLIC_EMAIL_DOMAINS:
        flags.append({
            "code": "public_recipient_domain",
            "detail": f"收件地址使用公共邮箱域名 {domain}，不是可识别的公司域名",
        })
    if "某" in company or "未知" in company or company.strip().lower() in {"unknown", "n/a"}:
        flags.append({
            "code": "anonymized_employer",
            "detail": "招聘方名称被匿名化，无法仅凭材料确认真实公司主体",
        })
    if source_images and not source_url:
        flags.append({
            "code": "image_only_source",
            "detail": "岗位仅来自图片，未提供可独立核验的原帖或官网链接",
        })
    if source_images:
        flags.append({
            "code": "recipient_from_image",
            "detail": "收件地址来自图片识别，发送前必须人工逐字符核对",
        })
    for note in custom_risk_notes or []:
        clean = note.strip()
        if clean:
            flags.append({"code": "posting_specific_review", "detail": clean})
    return flags


def _source_reference(source_url: str, source_images: list[dict[str, Any]]) -> str:
    if source_url:
        return source_url
    if source_images:
        return f"image-sha256:{source_images[0]['sha256']}"
    return "email-draft"


def _build_message(sender: str, recipient: str, subject: str, body: str, attachments: list[dict[str, Any]]) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body.strip() + "\n", subtype="plain", charset="utf-8")
    for item in attachments:
        path = Path(item["path"])
        mime, _ = mimetypes.guess_type(item["name"])
        maintype, subtype = (mime or "application/octet-stream").split("/", 1)
        message.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=item["name"])
    return message


def _write_review(path: Path, manifest: dict[str, Any]) -> None:
    risks = "".join(
        f"<li><strong>{html.escape(item['code'])}</strong>：{html.escape(item['detail'])}</li>"
        for item in manifest["risk_flags"]
    ) or "<li>未发现额外风险标记；仍需人工核对收件人、主题和附件。</li>"
    attachments = "".join(
        f"<li>{html.escape(item['name'])} · {item['size'] / 1024:.1f} KB · SHA-256 {html.escape(item['sha256'][:12])}…</li>"
        for item in manifest["attachments"]
    )
    is_sent = manifest.get("status") == "sent"
    status_label = "已发送" if is_sent else "未发送"
    gate = (
        f"<p>发送回执：<code>{html.escape(str(manifest.get('receipt') or '邮件服务器已接受'))}</code></p>"
        if is_sent else
        f"<p>发送口令：<code>{html.escape(manifest['confirmation_token'])}</code></p>"
    )
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>邮件投递审核</title>
<style>
:root{{color-scheme:dark}}body{{margin:0;background:#0b0f14;color:#e9eef5;font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}}
main{{max-width:900px;margin:36px auto;padding:0 22px}}.card{{background:#121923;border:1px solid #263242;border-radius:18px;padding:24px;margin:16px 0;box-shadow:0 18px 45px #0005}}
.eyebrow{{color:#7ee0c3;font-size:12px;letter-spacing:.12em;text-transform:uppercase}}h1{{font-size:28px;margin:.25em 0}}h2{{font-size:16px;color:#9fb0c3}}dt{{color:#8fa3b8}}dd{{margin:0 0 12px}}pre{{white-space:pre-wrap;background:#0a1017;border-radius:12px;padding:18px;color:#e9eef5}}.warn{{border-color:#725a22;background:#1b1810}}code{{color:#8fe7cd}}</style></head>
<body><main><div class="eyebrow">AI Job Search · {status_label}</div><h1>邮件投递审核</h1>
<section class="card"><dl><dt>草稿 ID</dt><dd>{html.escape(manifest['draft_id'])}</dd><dt>公司 / 岗位</dt><dd>{html.escape(manifest['company'])} · {html.escape(manifest['role'])}</dd><dt>发件人</dt><dd>{html.escape(manifest['sender'])}</dd><dt>收件人</dt><dd>{html.escape(manifest['recipient'])}</dd><dt>主题</dt><dd>{html.escape(manifest['subject'])}</dd></dl></section>
<section class="card"><h2>正文</h2><pre>{html.escape(manifest['body'])}</pre><h2>附件</h2><ul>{attachments}</ul></section>
<section class="card warn"><h2>人工核验项</h2><ul>{risks}</ul>{gate}</section>
</main></body></html>"""
    path.write_text(document, encoding="utf-8")


def prepare_draft(
    *,
    recipient: str,
    subject: str,
    body: str,
    attachments: list[Path],
    attachment_names: list[str] | None = None,
    company: str,
    role: str,
    source_images: list[Path] | None = None,
    source_url: str = "",
    custom_risk_notes: list[str] | None = None,
    sender_override: str | None = None,
    draft_root: Path | None = None,
    sync_tracking: bool = True,
) -> dict[str, Any]:
    """Create an auditable local draft. This function never sends email."""
    profile = model.load_profile()
    sender = validate_single_recipient(sender_override or str(profile["identity"]["email"]))
    clean_recipient = validate_single_recipient(recipient)
    clean_subject = _clean_header(subject, "邮件主题")
    clean_company = _clean_header(company, "公司")
    clean_role = _clean_header(role, "岗位")
    clean_body = body.strip()
    if not clean_body:
        raise EmailApplicationError("邮件正文不能为空")
    if not attachments:
        raise EmailApplicationError("求职邮件至少需要一个简历附件")

    if attachment_names is not None and len(attachment_names) != len(attachments):
        raise EmailApplicationError("--attachment-name 数量必须与 --attachment 完全一致")
    try:
        prepared_attachments = [
            materials.prepare_upload_file(Path(item), attachment_names[index] if attachment_names else None)
            for index, item in enumerate(attachments)
        ]
    except materials.MaterialError as exc:
        raise EmailApplicationError(str(exc)) from exc
    attachment_meta = [_file_meta(item) for item in prepared_attachments]
    total_size = sum(item["size"] for item in attachment_meta)
    if total_size > MAX_ATTACHMENT_BYTES:
        raise EmailApplicationError(f"附件合计超过 {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB 安全上限")

    source_paths = [Path(item) for item in (source_images or [])]
    source_meta_original = [_file_meta(item) for item in source_paths]
    source_url = source_url.strip()
    seed = f"{clean_recipient}|{clean_subject}|{clean_company}|{clean_role}|{time.time_ns()}"
    draft_id = time.strftime("%Y%m%d_%H%M%S") + "_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
    root = (draft_root or config.EMAIL_DRAFT_DIR).resolve()
    draft_dir = root / draft_id
    draft_dir.mkdir(parents=True, exist_ok=False)

    archived_sources: list[dict[str, Any]] = []
    if source_meta_original:
        source_dir = draft_dir / "sources"
        source_dir.mkdir()
        for index, (source_path, item) in enumerate(zip(source_paths, source_meta_original), start=1):
            archived = source_dir / f"{index:02d}_{source_path.name}"
            shutil.copy2(source_path.resolve(), archived)
            archived_sources.append({
                "name": source_path.name,
                "archived_path": str(archived.resolve()),
                "size": item["size"],
                "sha256": item["sha256"],
            })

    message = _build_message(sender, clean_recipient, clean_subject, clean_body, attachment_meta)
    eml_path = draft_dir / "message.eml"
    eml_path.write_bytes(message.as_bytes(policy=policy.SMTP))
    source_ref = _source_reference(source_url, archived_sources)
    manifest: dict[str, Any] = {
        "schema_version": "1.0.0",
        "draft_id": draft_id,
        "status": "drafted",
        "company": clean_company,
        "role": clean_role,
        "sender": sender,
        "recipient": clean_recipient,
        "subject": clean_subject,
        "body": clean_body,
        "attachments": attachment_meta,
        "source_images": archived_sources,
        "source_url": source_url,
        "source_reference": source_ref,
        "risk_flags": _risk_flags(
            clean_company, clean_recipient, archived_sources, source_url, custom_risk_notes,
        ),
        "confirmation_token": f"SEND {draft_id}",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": {
            "eml": str(eml_path.resolve()),
            "review": str((draft_dir / "review.html").resolve()),
        },
        "eml_sha256": _sha256(eml_path),
        "transport": None,
        "receipt": None,
    }
    manifest_path = draft_dir / "manifest.json"
    manifest["files"]["manifest"] = str(manifest_path.resolve())
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_review(draft_dir / "review.html", manifest)

    if sync_tracking:
        try:
            state.record(
                "email", clean_company, clean_role, source_ref, "drafted",
                resume=attachment_meta[0]["path"],
                steps=["图片/帖子岗位已结构化", "邮件草稿已生成（未发送）"],
            )
            tracker.upsert(
                clean_company, clean_role, portal="email", url=source_ref,
                cv_file=attachment_meta[0]["path"], status="drafted",
            )
        except Exception as exc:  # 草稿本身仍然有效；显式记录本地同步警告。
            manifest["tracking_warning"] = str(exc)
            manifest["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _resolve_manifest(reference: str | Path, draft_root: Path | None = None) -> Path:
    direct = Path(reference)
    if direct.is_file():
        return direct.resolve()
    root = (draft_root or config.EMAIL_DRAFT_DIR).resolve()
    candidate = root / str(reference) / "manifest.json"
    if not candidate.is_file():
        raise EmailApplicationError(f"找不到邮件草稿: {reference}")
    return candidate


def load_draft(reference: str | Path, draft_root: Path | None = None) -> tuple[dict[str, Any], Path]:
    manifest_path = _resolve_manifest(reference, draft_root)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise EmailApplicationError(f"草稿清单无法读取: {exc}") from exc
    return payload, manifest_path


def render_review(manifest: dict[str, Any], *, include_body: bool = True) -> str:
    lines = [
        "", "=" * 72, "【邮件发送前审核】（当前未发送）",
        f"  草稿 ID:  {manifest['draft_id']}",
        f"  公司/岗位: {manifest['company']} / {manifest['role']}",
        f"  发件人:    {manifest['sender']}",
        f"  收件人:    {manifest['recipient']}",
        f"  主题:      {manifest['subject']}",
        "  附件:      " + " | ".join(item["name"] for item in manifest["attachments"]),
    ]
    if manifest.get("risk_flags"):
        lines.append("  风险核验:")
        lines.extend(f"    - {item['detail']}" for item in manifest["risk_flags"])
    if include_body:
        lines.extend(["-" * 72, manifest["body"]])
    lines.extend([
        "=" * 72,
        f"只有在单独确认本封邮件后，才可输入精确口令: {manifest['confirmation_token']}",
    ])
    return "\n".join(lines)


def send_draft(
    reference: str | Path,
    *,
    draft_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    input_func: Callable[[str], str] = input,
    smtp_factory: Callable[..., Any] = smtplib.SMTP_SSL,
    sync_tracking: bool = True,
) -> dict[str, Any]:
    """Send exactly one prepared draft through QQ SMTP after an exact token."""
    manifest, manifest_path = load_draft(reference, draft_root)
    if manifest.get("status") != "drafted":
        raise EmailApplicationError(f"草稿状态为 {manifest.get('status')}，不能重复发送")
    eml_path = Path(manifest["files"]["eml"])
    if not eml_path.is_file() or _sha256(eml_path) != manifest.get("eml_sha256"):
        raise EmailApplicationError("message.eml 缺失或已被修改；请重新生成草稿")

    env = environ if environ is not None else os.environ
    smtp_user = validate_single_recipient(env.get("AI_JOB_QQ_SMTP_USER", ""))
    auth_code = env.get("AI_JOB_QQ_SMTP_AUTH_CODE", "").strip()
    if not auth_code:
        raise EmailApplicationError("缺少 AI_JOB_QQ_SMTP_AUTH_CODE；请只在当前终端环境变量中设置 QQ 邮箱授权码")
    if smtp_user != manifest["sender"]:
        raise EmailApplicationError("QQ SMTP 账号与草稿发件人不一致")

    print(render_review(manifest, include_body=True))
    answer = input_func("> ").strip()
    if answer != manifest["confirmation_token"]:
        raise SendCancelled("确认口令不匹配，邮件未发送")

    message = BytesParser(policy=policy.default).parsebytes(eml_path.read_bytes())
    try:
        with smtp_factory(QQ_SMTP_HOST, QQ_SMTP_PORT, timeout=30) as client:
            client.login(smtp_user, auth_code)
            refused = client.send_message(message)
    except Exception as exc:
        raise EmailApplicationError(f"QQ SMTP 发送失败（授权码未记录）: {type(exc).__name__}: {exc}") from exc
    if refused:
        raise EmailApplicationError(f"邮件服务器拒绝了收件人: {', '.join(str(key) for key in refused)}")

    manifest["status"] = "sent"
    manifest["transport"] = "qq-smtp"
    manifest["sent_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    manifest["updated_at"] = manifest["sent_at"]
    manifest["receipt"] = "QQ SMTP accepted message for delivery"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_review(Path(manifest["files"]["review"]), manifest)

    if sync_tracking:
        try:
            state.record(
                "email", manifest["company"], manifest["role"], manifest["source_reference"], "submitted",
                resume=manifest["attachments"][0]["path"], receipt=manifest["receipt"],
                steps=["邮件草稿已人工核对", "QQ SMTP 已接受单封邮件"],
            )
            tracker.upsert(
                manifest["company"], manifest["role"], portal="email",
                url=manifest["source_reference"], cv_file=manifest["attachments"][0]["path"], status="applied",
            )
        except Exception as exc:
            manifest["tracking_warning"] = str(exc)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="图片岗位邮件投递：默认仅生成草稿，单封确认后才能发送")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="生成本地 .eml、审核页和结构化清单；不发送")
    prepare.add_argument("--recipient", required=True)
    prepare.add_argument("--subject", required=True)
    prepare.add_argument("--body-file", type=Path, required=True)
    prepare.add_argument("--attachment", type=Path, action="append", required=True)
    prepare.add_argument(
        "--attachment-name", action="append",
        help="招聘方要求的实际附件文件名；可重复，数量和顺序必须与 --attachment 一致",
    )
    prepare.add_argument("--company", required=True)
    prepare.add_argument("--role", required=True)
    prepare.add_argument("--source-image", type=Path, action="append", default=[])
    prepare.add_argument("--source-url", default="")
    prepare.add_argument("--risk-note", action="append", default=[], help="写入审核页的岗位特有风险，可重复")

    show = sub.add_parser("show", help="显示待审核草稿")
    show.add_argument("draft")

    send = sub.add_parser("send", help="QQ SMTP 单封发送；必须输入本草稿精确口令")
    send.add_argument("draft")
    send.add_argument("--transport", choices=["qq-smtp"], default="qq-smtp")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            if not args.body_file.is_file():
                raise EmailApplicationError(f"正文文件不存在: {args.body_file}")
            manifest = prepare_draft(
                recipient=args.recipient,
                subject=args.subject,
                body=args.body_file.read_text(encoding="utf-8"),
                attachments=args.attachment,
                attachment_names=args.attachment_name,
                company=args.company,
                role=args.role,
                source_images=args.source_image,
                source_url=args.source_url,
                custom_risk_notes=args.risk_note,
            )
            print(render_review(manifest))
            print(f"\n审核网页: {manifest['files']['review']}")
            print(f"邮件草稿: {manifest['files']['eml']}")
            return 0
        if args.command == "show":
            manifest, _ = load_draft(args.draft)
            print(render_review(manifest))
            return 0
        if args.command == "send":
            sent = send_draft(args.draft)
            print(f"已发送并记录: {sent['draft_id']} · {sent['recipient']}")
            return 0
    except SendCancelled as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except EmailApplicationError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
