"""Save a prepared email application into QQ Mail's web Drafts folder.

This module deliberately has no send path. It reuses the project's dedicated
Chrome profile, waits for manual login, fills one prepared ``email_apply``
draft, saves it, verifies the subject in Drafts, and leaves Chrome open for
human review.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any, Iterable

from . import browser, config
from .email_apply import EmailApplicationError, load_draft


QQ_MAIL_URL = "https://mail.qq.com/"
CONTROL_PROBE = config.STATE_DIR / "probe_qq_mail_controls.json"


class QQMailDraftError(RuntimeError):
    pass


def _pages(context) -> list[Any]:
    return [item for item in context.pages if not item.is_closed()]


def _frames(context) -> Iterable[Any]:
    for page in _pages(context):
        for frame in page.frames:
            yield frame


def _safe_text(frame, limit: int = 1200) -> str:
    try:
        return frame.locator("body").inner_text(timeout=1200)[:limit]
    except Exception:
        return ""


def _mail_page(context):
    candidates = _pages(context)
    for page in reversed(candidates):
        if "mail.qq.com" not in page.url:
            continue
        text = "\n".join(_safe_text(frame) for frame in page.frames)
        if any(word in text for word in ("写信", "收件箱", "草稿箱")) and "QQ邮箱登录" not in text:
            return page
    return candidates[-1] if candidates else None


def _is_logged_in(context) -> bool:
    page = _mail_page(context)
    if page is None:
        return False
    text = "\n".join(_safe_text(frame) for frame in page.frames)
    return any(word in text for word in ("写信", "收件箱", "草稿箱")) and "QQ邮箱登录" not in text


def _visible(locator) -> bool:
    try:
        return locator.is_visible(timeout=500)
    except Exception:
        return False


def _click_text(context, labels: tuple[str, ...]) -> str | None:
    pattern = re.compile("^(?:" + "|".join(re.escape(label) for label in labels) + ")$")
    for frame in _frames(context):
        for selector in ("button", "a", "[role=button]", "[role=link]", "div", "span"):
            locator = frame.locator(selector).filter(has_text=pattern)
            for index in range(min(locator.count(), 8)):
                item = locator.nth(index)
                if _visible(item):
                    item.click(timeout=5000)
                    return labels[0]
    return None


def _first_visible(context, selectors: tuple[str, ...]):
    for frame in _frames(context):
        for selector in selectors:
            locator = frame.locator(selector)
            for index in range(min(locator.count(), 12)):
                item = locator.nth(index)
                if _visible(item):
                    return item
    return None


def _fill(locator, value: str, label: str) -> None:
    if locator is None:
        raise QQMailDraftError(f"未找到{label}控件")
    try:
        locator.fill(value, timeout=5000)
    except Exception:
        locator.click(timeout=3000)
        locator.press("Control+A")
        locator.press_sequentially(value, delay=8)


def _probe_controls(context, path: Path = CONTROL_PROBE) -> Path:
    payload: list[dict[str, Any]] = []
    for page_index, page in enumerate(_pages(context)):
        for frame_index, frame in enumerate(page.frames):
            item: dict[str, Any] = {
                "page_index": page_index,
                "frame_index": frame_index,
                "page_url": page.url,
                "frame_url": frame.url,
                "inputs": [],
                "contenteditables": [],
                "buttons": [],
            }
            for selector, key in (
                ("input, textarea", "inputs"),
                ("[contenteditable=true]", "contenteditables"),
                ("button, [role=button], a", "buttons"),
            ):
                locators = frame.locator(selector)
                for index in range(min(locators.count(), 100)):
                    locator = locators.nth(index)
                    try:
                        data = locator.evaluate("""el => ({
                          tag: el.tagName,
                          type: el.getAttribute('type'),
                          name: el.getAttribute('name'),
                          id: el.id,
                          placeholder: el.getAttribute('placeholder'),
                          aria: el.getAttribute('aria-label'),
                          role: el.getAttribute('role'),
                          text: (el.innerText || '').trim().slice(0, 80),
                          visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                        })""")
                    except Exception:
                        continue
                    if data.get("visible") or key != "buttons":
                        item[key].append(data)
            payload.append(item)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _wait_for_login(context, page, timeout_s: int) -> Any:
    if _is_logged_in(context):
        return _mail_page(context)
    print("[QQ邮箱] 请在打开的 Chrome 中手动完成 QQ/微信扫码或账号登录。")
    print(f"[QQ邮箱] 最长等待 {timeout_s} 秒；不会读取或保存你的密码/验证码。")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _is_logged_in(context):
            mail_page = _mail_page(context)
            print("[QQ邮箱] 已检测到登录成功。")
            return mail_page
        time.sleep(2)
    raise QQMailDraftError("等待 QQ 邮箱人工登录超时")


def _compose(context, manifest: dict[str, Any]) -> None:
    if not _click_text(context, ("写信", "写邮件")):
        raise QQMailDraftError("未找到“写信”入口")
    time.sleep(2)

    recipient = _first_visible(context, (
        'input[placeholder*="收件人"]', 'textarea[placeholder*="收件人"]',
        'input[aria-label*="收件人"]', 'textarea[aria-label*="收件人"]',
        'input[name*="to" i]', 'textarea[name*="to" i]',
    ))
    subject = _first_visible(context, (
        'input[placeholder*="主题"]', 'textarea[placeholder*="主题"]',
        'input[aria-label*="主题"]', 'input[name*="subject" i]',
    ))
    _fill(recipient, manifest["recipient"], "收件人")
    try:
        recipient.press("Enter")
    except Exception:
        pass
    _fill(subject, manifest["subject"], "主题")

    body = _first_visible(context, (
        '[contenteditable=true][aria-label*="正文"]',
        '[contenteditable=true][data-placeholder*="正文"]',
        '[contenteditable=true][role=textbox]',
        'body[contenteditable=true]',
    ))
    _fill(body, manifest["body"], "正文")

    file_input = _first_visible(context, ('input[type=file]',))
    if file_input is None:
        # Hidden file inputs are normal and can still accept a file.
        for frame in _frames(context):
            candidate = frame.locator('input[type=file]')
            if candidate.count():
                file_input = candidate.first
                break
    if file_input is None:
        raise QQMailDraftError("未找到附件上传控件")
    attachments = [str(Path(item["path"]).resolve()) for item in manifest["attachments"]]
    file_input.set_input_files(attachments, timeout=15000)
    time.sleep(3)


def _save_and_verify(context, manifest: dict[str, Any]) -> None:
    saved = _click_text(context, ("存草稿", "保存草稿"))
    if saved:
        time.sleep(3)
    else:
        # QQ Mail currently autosaves composed mail. Waiting before opening Drafts
        # gives the client time to persist the message.
        time.sleep(8)
    if not _click_text(context, ("草稿箱",)):
        raise QQMailDraftError("未找到“草稿箱”，无法验证在线草稿")
    time.sleep(4)
    subject = manifest["subject"]
    for frame in _frames(context):
        try:
            if frame.get_by_text(subject, exact=False).count():
                print(f"[QQ邮箱] 已在草稿箱核验主题：{subject}")
                return
        except Exception:
            continue
    raise QQMailDraftError("已尝试保存，但未能在草稿箱核验到目标主题")


def save_web_draft(reference: str, *, profile_dir: Path, timeout_s: int, keep_open: bool) -> None:
    manifest, manifest_path = load_draft(reference)
    if manifest.get("status") != "drafted":
        raise EmailApplicationError("仅允许把状态为 drafted 的本地草稿写入在线草稿箱")
    p, context, page = browser.launch(profile_dir=profile_dir, headless=False)
    try:
        page.goto(QQ_MAIL_URL, wait_until="domcontentloaded", timeout=30000)
        _wait_for_login(context, page, timeout_s)
        try:
            _compose(context, manifest)
            _save_and_verify(context, manifest)
        except Exception:
            probe = _probe_controls(context)
            print(f"[QQ邮箱] 已保存控件快照用于适配：{probe}")
            raise
        manifest["remote_draft"] = {
            "provider": "qq_mail_web",
            "status": "verified_in_drafts",
            "verified_subject": manifest["subject"],
            "verified_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sent": False,
        }
        manifest["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[QQ邮箱] 在线草稿已保存并核验；没有发送邮件。")
        if keep_open:
            print("[QQ邮箱] 浏览器保持打开供你审核；在本终端按 Enter 后才会关闭。")
            input()
    finally:
        context.close()
        p.stop()


def probe(*, profile_dir: Path, timeout_s: int, keep_open: bool) -> None:
    p, context, page = browser.launch(profile_dir=profile_dir, headless=False)
    try:
        page.goto(QQ_MAIL_URL, wait_until="domcontentloaded", timeout=30000)
        _wait_for_login(context, page, timeout_s)
        path = _probe_controls(context)
        print(f"[QQ邮箱] 控件快照：{path}")
        if keep_open:
            print("[QQ邮箱] 浏览器保持打开；在本终端按 Enter 后关闭。")
            input()
    finally:
        context.close()
        p.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="将本地求职邮件安全保存到 QQ 邮箱草稿箱（无发送功能）")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("probe", "save"):
        command = sub.add_parser(name)
        if name == "save":
            command.add_argument("draft", help="email_apply 草稿 ID 或 manifest.json")
        command.add_argument("--profile-dir", type=Path, default=config.CHROME_PROFILE_DIR)
        command.add_argument("--login-timeout", type=int, default=600)
        command.add_argument("--close", action="store_true", help="完成后关闭浏览器；默认保持打开供审核")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "probe":
            probe(profile_dir=args.profile_dir, timeout_s=args.login_timeout, keep_open=not args.close)
        else:
            save_web_draft(args.draft, profile_dir=args.profile_dir, timeout_s=args.login_timeout, keep_open=not args.close)
        return 0
    except (EmailApplicationError, QQMailDraftError) as exc:
        print(f"[阻塞] {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
