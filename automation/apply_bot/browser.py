"""浏览器管理：持久化 Chrome 会话（channel="chrome" + 专用 user-data-dir）。

设计要点
- 复用用户日常安装的 Google Chrome（channel="chrome"），不下载 Chromium。
- 专用 user-data-dir 保存登录态：用户扫码/短信登录一次，之后复用。
- 不添加任何反检测/规避参数；不做验证码、扫码、短信验证码绕过——这类交互
  一律停住等人工完成。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from . import config


class BrowserError(RuntimeError):
    pass


def launch(profile_dir: Path | None = None, headless: bool = False):
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

    p = sync_playwright().start()
    try:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir or config.CHROME_PROFILE_DIR),
            channel="chrome",
            headless=headless,
            viewport=None,
            args=["--start-maximized"],
            ignore_default_args=["--enable-automation"],
        )
    except Exception as e:
        p.stop()
        raise BrowserError(f"启动 Chrome 失败（{e}）—— 请确认已安装 Google Chrome，且没有其他进程占用 {profile_dir or config.CHROME_PROFILE_DIR}") from e
    return p, context, context.new_page()


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
