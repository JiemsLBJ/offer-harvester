"""浏览器管理：持久化 Chrome 会话（channel="chrome" + 专用 user-data-dir）。

设计要点
- 复用用户日常安装的 Google Chrome（channel="chrome"），不下载 Chromium。
- 专用 user-data-dir 保存登录态：用户扫码/短信登录一次，之后复用。
- 不添加任何反检测/规避参数；不做验证码、扫码、短信验证码绕过——这类交互
  一律停住等人工完成。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit, urlunsplit
from urllib.request import ProxyHandler, build_opener

from . import config


class BrowserError(RuntimeError):
    pass


class BrowserRuntime:
    """Playwright runtime with an optional independently owned Chrome process."""

    def __init__(self, playwright, *, retained: bool = False, browser=None, process=None):
        self.playwright = playwright
        self.retained = retained
        self.browser = browser
        self.process = process

    def stop(self) -> None:
        if self.retained:
            record_browser_event("automation_disconnected", retained=True)
        # For connect_over_cdp this disconnects Playwright but does not close the
        # independently launched Chrome. For launch_persistent_context it keeps
        # the historical behavior and closes the Playwright-owned browser.
        self.playwright.stop()


def _event_url(value: str) -> str:
    """Keep useful page identity without persisting query strings or fragments."""
    try:
        parts = urlsplit(value)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except Exception:
        return ""


def record_browser_event(event: str, **details) -> None:
    """Append local crash/disconnect diagnostics without form values."""
    try:
        config.ensure_dirs()
        allowed = {"stage", "portal", "url", "error_type", "retained", "port", "pid", "profile"}
        payload = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event": event,
        }
        for key, value in details.items():
            if key not in allowed or value is None:
                continue
            payload[key] = _event_url(str(value)) if key == "url" else str(value)[:500]
        path = config.STATE_DIR / "browser_events.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # Diagnostics must never break an application workflow.
        pass


def _chrome_executable() -> Path:
    command = shutil.which("chrome") or shutil.which("google-chrome")
    if command:
        return Path(command)
    candidates = [
        Path(root) / "Google/Chrome/Application/chrome.exe"
        for root in (
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        )
        if root
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise BrowserError("未找到系统 Google Chrome；请先安装 Chrome")


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _cdp_ready(port: int, timeout: float = 0.8) -> bool:
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return bool(payload.get("webSocketDebuggerUrl"))
    except Exception:
        return False


def _session_path(profile_dir: Path) -> Path:
    return profile_dir / ".apply-bot-browser-session.json"


def _existing_cdp_port(profile_dir: Path) -> int | None:
    path = _session_path(profile_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        port = int(payload.get("port", 0))
        return port if port and _cdp_ready(port) else None
    except Exception:
        return None


def _start_retained_chrome(profile_dir: Path) -> tuple[int, subprocess.Popen | None]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    existing = _existing_cdp_port(profile_dir)
    if existing:
        record_browser_event("retained_browser_reused", port=existing, profile=profile_dir.name)
        return existing, None

    port = _free_loopback_port()
    args = [
        str(_chrome_executable()),
        f"--user-data-dir={profile_dir.resolve()}",
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        "--start-maximized",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    popen_kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    process = None
    if os.name == "nt":
        base_flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0,
        )
        breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        try:
            process = subprocess.Popen(args, creationflags=base_flags | breakaway, **popen_kwargs)
        except OSError:
            process = subprocess.Popen(args, creationflags=base_flags, **popen_kwargs)
    else:
        process = subprocess.Popen(args, start_new_session=True, **popen_kwargs)

    deadline = time.time() + 20
    while time.time() < deadline:
        if _cdp_ready(port):
            _session_path(profile_dir).write_text(
                json.dumps({"port": port, "pid": process.pid}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            record_browser_event(
                "retained_browser_started", port=port, pid=process.pid, profile=profile_dir.name,
            )
            return port, process
        if process.poll() is not None:
            break
        time.sleep(0.25)
    raise BrowserError("独立 Chrome 启动后未开放本机调试端口；请确认该登录档案没有被其他 Chrome 占用")


def _bind_diagnostics(context, *, retained: bool) -> None:
    def page_url(page) -> str:
        try:
            return page.url
        except Exception:
            return ""

    def bind_page(page) -> None:
        page.on("crash", lambda: record_browser_event("page_crash", url=page_url(page), retained=retained))
        page.on("close", lambda: record_browser_event("page_closed", url=page_url(page), retained=retained))

    for page in context.pages:
        bind_page(page)
    context.on("page", bind_page)
    context.on("close", lambda: record_browser_event("context_closed", retained=retained))


def launch(
    profile_dir: Path | None = None,
    headless: bool = False,
    retain_on_exit: bool = False,
):
    """启动持久化上下文。返回 (playwright, context, page)。

    headless=True 仅用于探路/巡检；投递流程必须 headless=False（用户需要
    看见页面、登录、并在确认关卡操作）。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise BrowserError(
            "未安装 playwright：pip install -r automation/apply_bot/requirements.txt"
        ) from e

    if headless and retain_on_exit:
        raise BrowserError("无头浏览器不能使用独立审核保留模式")

    selected_profile = (profile_dir or config.CHROME_PROFILE_DIR).resolve()
    if retain_on_exit:
        port, process = _start_retained_chrome(selected_profile)
        p = sync_playwright().start()
        try:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=15_000)
            if not browser.contexts:
                raise RuntimeError("Chrome 未返回可用浏览器上下文")
            context = browser.contexts[0]
            page = context.new_page()
            _bind_diagnostics(context, retained=True)
            return BrowserRuntime(
                p, retained=True, browser=browser, process=process,
            ), context, page
        except Exception as error:
            p.stop()
            raise BrowserError(f"连接独立 Chrome 失败（{error}）") from error

    p = sync_playwright().start()
    try:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(selected_profile),
            channel="chrome",
            headless=headless,
            viewport=None,
            args=["--start-maximized"],
            ignore_default_args=["--enable-automation"],
        )
    except Exception as e:
        p.stop()
        raise BrowserError(f"启动 Chrome 失败（{e}）—— 请确认已安装 Google Chrome，且没有其他进程占用 {selected_profile}") from e
    page = context.new_page()
    _bind_diagnostics(context, retained=False)
    return BrowserRuntime(p), context, page


def wait_for_login(
    context,
    page,
    is_logged_in: Callable[[object], bool],
    login_hint: str,
    timeout_s: int | None = None,
) -> None:
    """等待用户在打开的 Chrome 窗口完成登录。

    is_logged_in(page) 返回 True 即结束；每 POLL_INTERVAL 秒检查一次；提示人工
    完成扫码/短信验证码（不做任何绕过）。轮询前会刷新页面以便反映登录态，
    但若页面正处于扫码/验证码交互（body 含「扫码」等字眼）则跳过刷新不打断。
    超时则抛出 BrowserError。
    """
    timeout_s = timeout_s or config.LOGIN_WAIT_S
    deadline = time.time() + timeout_s
    print(f"\n[登录] {login_hint}")
    print(f"[登录] 请在浏览器窗口手动完成登录（扫码/短信验证码/密码均可），完成后自动继续，最长等待 {timeout_s} 秒 ...")
    manual_check = 0
    while time.time() < deadline:
        try:
            if is_logged_in(page):
                print("[登录] 检测到已登录，继续。\n")
                return
        except Exception:
            pass
        time.sleep(config.POLL_INTERVAL_S)
        manual_check += 1
        # 每 ~30 秒刷新一次页面让登录态生效；正在扫码/填验证码时跳过刷新
        if manual_check >= 6:
            manual_check = 0
            try:
                body = page.locator("body").inner_text(timeout=1500)
                login_interaction = body.lower()
                if not any(k in login_interaction for k in (
                    "扫码", "二维码", "验证码", "recaptcha", "verification code",
                    "email login", "phone number login", "wechat",
                )):
                    page.reload(wait_until="domcontentloaded")
            except Exception:
                pass
    raise BrowserError("等待人工登录超时——请重新运行，并在浏览器中先完成登录。")


def open_page(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
