"""Clone an audited application email into Gmail Drafts without sending it."""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from . import browser, config
from .email_apply import EmailApplicationError, load_draft, prepare_draft


GMAIL_URL = "https://mail.google.com/mail/u/0/#inbox"
EMAIL_RE = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PROBE_PATH = config.STATE_DIR / "probe_gmail_controls.json"


class GmailDraftError(RuntimeError):
    pass


def _pages(context) -> list[Any]:
    return [page for page in context.pages if not page.is_closed()]


def _mail_page(context):
    for page in reversed(_pages(context)):
        if "mail.google.com" in page.url:
            return page
    return _pages(context)[-1] if _pages(context) else None


def _body_text(page, limit: int = 2500) -> str:
    try:
        return page.locator("body").inner_text(timeout=1500)[:limit]
    except Exception:
        return ""


def _is_logged_in(context) -> bool:
    page = _mail_page(context)
    if page is None or "accounts.google.com" in page.url:
        return False
    text = _body_text(page)
    return any(word in text for word in ("撰写", "收件箱", "Compose", "Inbox", "草稿", "Drafts"))


def _wait_for_login(context, timeout_s: int):
    if _is_logged_in(context):
        return _mail_page(context)
    print("[Gmail] 请在打开的 Chrome 中手动完成 Google 账号登录。")
    print(f"[Gmail] 最长等待 {timeout_s} 秒；不会读取或保存密码、验证码。")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _is_logged_in(context):
            print("[Gmail] 已检测到登录成功。")
            return _mail_page(context)
        time.sleep(2)
    raise GmailDraftError("等待 Gmail 人工登录超时")


def _account_email(page) -> str | None:
    selectors = (
        'a[aria-label*="@"]', 'img[aria-label*="@"]',
        '[data-email*="@"]', '[title*="@"]', '[aria-label*="@"]',
    )
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(min(locator.count(), 40)):
            item = locator.nth(index)
            for attribute in ("data-email", "aria-label", "title"):
                try:
                    value = item.get_attribute(attribute) or ""
                except Exception:
                    continue
                match = EMAIL_RE.search(value)
                if match and not value.lower().startswith(("to:", "收件人")):
                    return match.group(0).lower()
    return None


def _visible(locator) -> bool:
    try:
        return locator.is_visible(timeout=500)
    except Exception:
        return False


def _first_visible(page, selectors: tuple[str, ...]):
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(min(locator.count(), 25)):
            item = locator.nth(index)
            if _visible(item):
                return item
    return None


def _click_named(page, names: tuple[str, ...]) -> bool:
    pattern = re.compile("^(?:" + "|".join(re.escape(name) for name in names) + ")$")
    for role in ("button", "link"):
        locator = page.get_by_role(role, name=pattern)
        for index in range(min(locator.count(), 10)):
            item = locator.nth(index)
            if _visible(item):
                item.click(timeout=5000)
                return True
    for selector in ("div", "span", "a"):
        locator = page.locator(selector).filter(has_text=pattern)
        for index in range(min(locator.count(), 10)):
            item = locator.nth(index)
            if _visible(item):
                item.click(timeout=5000)
                return True
    return False


def _fill(locator, value: str, label: str) -> None:
    if locator is None:
        raise GmailDraftError(f"未找到{label}控件")
    try:
        locator.fill(value, timeout=5000)
    except Exception:
        locator.click(timeout=3000)
        locator.press("Control+A")
        locator.press_sequentially(value, delay=6)


def _probe(page, path: Path = PROBE_PATH) -> Path:
    payload: dict[str, Any] = {"url": page.url, "title": page.title(), "controls": []}
    locators = page.locator("input, textarea, [contenteditable=true], button, [role=button], a")
    for index in range(min(locators.count(), 250)):
        locator = locators.nth(index)
        try:
            data = locator.evaluate("""el => ({
              tag: el.tagName, type: el.getAttribute('type'), name: el.getAttribute('name'),
              id: el.id, placeholder: el.getAttribute('placeholder'),
              aria: el.getAttribute('aria-label'), role: el.getAttribute('role'),
              text: (el.innerText || '').trim().slice(0, 80),
              visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
            })""")
        except Exception:
            continue
        if data.get("visible") or data.get("type") == "file":
            payload["controls"].append(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _clone_local_draft(source_reference: str, sender: str) -> tuple[dict[str, Any], Path]:
    source, source_path = load_draft(source_reference)
    if source.get("channel_intent") == "gmail_web_draft_only":
        if source.get("sender") != sender:
            raise GmailDraftError("当前 Gmail 登录账号与已有 Gmail 草稿发件人不一致")
        return source, source_path
    images = [Path(item["archived_path"]) for item in source.get("source_images", [])]
    attachments = [Path(item["path"]) for item in source["attachments"]]
    # Keep the posting-specific review notes from the audited source draft.
    # Generic image/public-domain flags are regenerated by prepare_draft().
    # Do not assume the source was already sent through QQ: many drafts are
    # prepared specifically for Gmail and that false warning hides real risks.
    source_review_notes = [
        str(item.get("detail", "")).strip()
        for item in source.get("risk_flags", [])
        if item.get("code") == "posting_specific_review" and str(item.get("detail", "")).strip()
    ]
    source_review_notes.append("本次仅保存Gmail草稿，必须由用户人工决定是否发送")
    manifest = prepare_draft(
        recipient=source["recipient"],
        subject=source["subject"],
        body=source["body"],
        attachments=attachments,
        company=source["company"],
        role=source["role"],
        source_images=images,
        source_url=source.get("source_url", ""),
        custom_risk_notes=source_review_notes,
        sender_override=sender,
        sync_tracking=False,
    )
    manifest_path = Path(manifest["files"]["manifest"])
    manifest["origin_draft_id"] = source["draft_id"]
    manifest["channel_intent"] = "gmail_web_draft_only"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest, manifest_path


def _compose(page, manifest: dict[str, Any]) -> None:
    # Fresh Gmail accounts may show an onboarding card over the inbox. Dismiss
    # only non-destructive prompts; never interact with Send.
    for label in ("No thanks", "Not now", "Dismiss", "不用了", "以后再说"):
        try:
            candidate = page.get_by_role("button", name=label, exact=True)
            if candidate.count() and _visible(candidate.first):
                candidate.first.click(timeout=3000)
                time.sleep(1)
        except Exception:
            pass
    if not _click_named(page, ("撰写", "Compose")):
        raise GmailDraftError("未找到 Gmail“撰写”入口")
    time.sleep(4)

    recipient = _first_visible(page, (
        'input[role=combobox][aria-label*="收件人"]',
        'input[role=combobox][aria-label*="Recipients"]',
        'input[role=combobox][aria-label^="To"]',
        'input[placeholder*="Recipients"]',
        'input[peoplekit-autocomplete-input]', 'textarea[name=to]', 'input[name=to]',
        'input[role=combobox][type=text]:not([name=q])',
    ))
    _fill(recipient, manifest["recipient"], "收件人")
    try:
        recipient.press("Enter")
    except Exception:
        pass
    subject = _first_visible(page, ('input[name=subjectbox]', 'input[placeholder*="主题"]'))
    _fill(subject, manifest["subject"], "主题")
    body = _first_visible(page, (
        'div[aria-label="邮件正文"]', 'div[aria-label="Message Body"]',
        'div[contenteditable=true][role=textbox]',
    ))
    _fill(body, manifest["body"], "正文")

    file_input = page.locator('input[type=file][name=Filedata]')
    if not file_input.count():
        file_input = page.locator('input[type=file]')
    if not file_input.count():
        raise GmailDraftError("未找到 Gmail 附件上传控件")
    paths = [str(Path(item["path"]).resolve()) for item in manifest["attachments"]]
    file_input.first.set_input_files(paths, timeout=15000)
    time.sleep(5)


def _save_close_and_verify(page, manifest: dict[str, Any]) -> None:
    close = _first_visible(page, (
        '[aria-label="保存并关闭"]', '[aria-label="Save & close"]',
        'img[aria-label="保存并关闭"]', 'img[aria-label="Save & close"]',
    ))
    if close is None:
        raise GmailDraftError("未找到 Gmail“保存并关闭”控件")
    close.click(timeout=5000)
    time.sleep(4)
    page.goto("https://mail.google.com/mail/u/0/#drafts", wait_until="domcontentloaded", timeout=30000)
    time.sleep(6)
    subject = manifest["subject"]
    subject_locator = page.get_by_text(subject, exact=False)
    if not subject_locator.count():
        raise GmailDraftError("未能在 Gmail 草稿箱核验到目标主题")
    print(f"[Gmail] 已在草稿箱核验主题：{subject}")
    # Long subjects can also appear in Gmail's attachment live-region. Clicking
    # that text fails because it is outside the viewport. Reopen only through a
    # visible message-list row, and keep verification successful if Gmail's row
    # markup changes: the draft has already been saved and found above.
    draft_rows = page.locator("tr").filter(has_text=subject)
    for index in range(min(draft_rows.count(), 8)):
        row = draft_rows.nth(index)
        if not _visible(row):
            continue
        try:
            row.click(timeout=5000)
            time.sleep(2)
            return
        except Exception:
            continue
    print("[Gmail] 草稿已保存并核验，但未能自动重新打开；当前保留在草稿列表。")


def save_gmail_draft(source_reference: str, *, profile_dir: Path, timeout_s: int, keep_open: bool) -> None:
    p, context, page = browser.launch(profile_dir=profile_dir, headless=False)
    try:
        page.goto(GMAIL_URL, wait_until="domcontentloaded", timeout=30000)
        page = _wait_for_login(context, timeout_s)
        sender = _account_email(page)
        if not sender:
            path = _probe(page)
            raise GmailDraftError(f"无法从当前 Gmail 页面确认发件账号；控件快照：{path}")
        print(f"[Gmail] 当前发件账号：{sender}")
        manifest, manifest_path = _clone_local_draft(source_reference, sender)
        try:
            _compose(page, manifest)
            _save_close_and_verify(page, manifest)
        except Exception:
            print(f"[Gmail] 已保存控件快照用于适配：{_probe(page)}")
            raise
        manifest["remote_draft"] = {
            "provider": "gmail_web",
            "status": "verified_in_drafts",
            "verified_subject": manifest["subject"],
            "verified_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sent": False,
        }
        manifest["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[Gmail] 在线草稿已保存并核验；没有发送。草稿 ID：{manifest['draft_id']}")
        if keep_open:
            print("[Gmail] 草稿已重新打开供你审核；在本终端按 Enter 后才会关闭浏览器。")
            input()
    finally:
        context.close()
        p.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="把已审计求职邮件复制到 Gmail 草稿箱（无发送功能）")
    parser.add_argument("source_draft", help="来源 email_apply 草稿 ID 或 manifest.json")
    parser.add_argument("--profile-dir", type=Path, default=config.AUTOMATION_DIR / "apply_bot" / ".chrome-profile-gmail")
    parser.add_argument("--login-timeout", type=int, default=600)
    parser.add_argument("--close", action="store_true", help="完成后关闭浏览器；默认保持打开供审核")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        save_gmail_draft(
            args.source_draft,
            profile_dir=args.profile_dir,
            timeout_s=args.login_timeout,
            keep_open=not args.close,
        )
        return 0
    except (EmailApplicationError, GmailDraftError) as exc:
        print(f"[阻塞] {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
