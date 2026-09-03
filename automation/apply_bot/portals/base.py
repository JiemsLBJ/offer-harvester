"""门户适配层基类与通用表单工具。

原则
- 确定性优先：选择器锚定站点结构；首次遇到未知结构→probe 模式：把可见表单
  快照（输入框提示语/标签/按钮文字）输出到文件并停下，等待人工探路后补全适配器。
- 不绕过验证码/扫码/短信；遇到验证码→Blocked(人机验证)，由人工完成。
- 提交前必经 confirm.confirm()（apply_one 统一执行），适配器不自行提交。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .. import config


class Blocked(RuntimeError):
    """需要人工介入（验证码/未知结构/站点限制）。携带原因与提示。"""

    def __init__(self, reason: str, hint: str = "", probe: dict | None = None, portal: str = "unknown"):
        self.reason = reason
        self.hint = hint
        self.probe = probe
        self.portal = portal
        super().__init__(f"[{portal}] {reason}")


@dataclass
class JobInfo:
    title: str
    company: str
    url: str
    id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class PortalAdapter:
    name = "base"
    url_patterns: list[str] = []
    home_url: str | None = None   # 站点首页：登录检测前先导航到此页，避免空白页误判
    login_url: str | None = None
    resume_prefers_docx = False   # True 时 find_resume 以 Word 优先（字节实测解析最好）

    # ---- 登录 ----
    def is_logged_in(self, page: Any) -> bool:
        raise NotImplementedError

    def login_hint(self) -> str:
        return f"请打开 {self.login_url or self.name} 登录页完成登录"

    # ---- 打开岗位 ----
    def open_job(self, page: Any, url: str) -> JobInfo:
        raise NotImplementedError

    # ---- 进入申请表 ----
    def open_apply_form(self, page: Any, job: JobInfo) -> None:
        raise NotImplementedError

    # ---- 填写（自动+人工补充）----
    def fill_form(self, page: Any, job: JobInfo, profile: dict[str, Any], resume: Path | None) -> list[str]:
        """返回「实际填写的字段名」清单（确认关卡展示用）。缺字段留待人工时在 notes 说明。"""
        raise NotImplementedError

    # ---- 校验 ----
    def verify(self, page: Any, job: JobInfo) -> list[str]:
        """返回问题清单；空列表=通过。"""
        return []

    # ---- 提交（点击按钮，不确认）----
    def submit(self, page: Any, job: JobInfo) -> None:
        raise NotImplementedError

    # ---- 回执 ----
    def wait_receipt(self, page: Any, job: JobInfo, timeout_s: int = 60) -> str | None:
        return None

    # ---- 探路 ----
    def probe(self, page: Any, url: str) -> dict[str, Any]:
        page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        # 招聘站点多为 SPA；domcontentloaded 时表单通常尚未挂载完成。
        page.wait_for_timeout(2500)
        snap = dump_form_snapshot(page)
        _save_probe(self.name, url, snap)
        return snap


def _save_probe(portal: str, url: str, snap: dict[str, Any]) -> Path:
    config.ensure_dirs()
    out = config.STATE_DIR / f"probe_{portal}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"portal": portal, "url": url, "snapshot": snap}, f, ensure_ascii=False, indent=2)
    return out


# ---------------------------------------------------------------------------
# 通用 DOM 工具
# ---------------------------------------------------------------------------

def proxy_url() -> str | None:
    """环境变量优先，其次 Windows 注册表 ProxyServer（Clash 等）。"""
    import os

    for env in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        v = os.environ.get(env)
        if v:
            return v
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
            enable, _ = winreg.QueryValueEx(k, "ProxyEnable")
            if not enable:
                return None
            server, _ = winreg.QueryValueEx(k, "ProxyServer")
            return server if "://" in server else f"http://{server}"
    except Exception:
        return None


def fetch_html(url: str, headers: dict | None = None, timeout: int = 25) -> str:
    """抓取页面 HTML：先直连，失败时回退系统代理。仅用于公开页面解析。"""
    import gzip
    import json
    import urllib.request

    base_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "gzip",
    }
    base_headers.update(headers or {})
    last_err: Exception | None = None
    for handler in (urllib.request.ProxyHandler({}), urllib.request.ProxyHandler({"http": proxy_url(), "https": proxy_url()})):
        opener = urllib.request.build_opener(handler)
        try:
            req = urllib.request.Request(url, headers=base_headers)
            with opener.open(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", "replace")
        except Exception as e:  # direct 失败 → 尝试代理
            last_err = e
    raise last_err or RuntimeError(f"fetch failed: {url}")


def dump_form_snapshot(page: Any) -> dict[str, Any]:
    inputs = page.evaluate(
        """() => {
          const pick = (el) => {
            const r = {tag: el.tagName.toLowerCase()};
            // 不读取 value：probe 可能在用户人工填写证件号后运行，任何字段值都
            // 不得落盘。仅保存定位申请表结构所需的静态元数据。
            for (const a of ["name","id","placeholder","type","accept","class","role","aria-label","aria-required","required","autocomplete"]) {
              const v = el.getAttribute(a);
              if (v) r[a] = v;
            }
            if (el.parentElement?.className && typeof el.parentElement.className === "string") {
              r.parent_class = el.parentElement.className;
            }
            const lbl = el.closest("label") || el.closest(".form-item, .ant-form-item, .el-form-item, .form-group");
            if (lbl) r.label = (lbl.textContent || "").trim().slice(0, 60);
            r.visible = !!(el.offsetParent || el.getClientRects().length);
            return r;
          };
          const inputs = [...document.querySelectorAll("input, textarea, select")].map(pick);
          const buttons = [...document.querySelectorAll("button, .btn, [role=button], a")].map(el =>
            ({text: (el.textContent || "").trim().slice(0, 40), visible: !!(el.offsetParent || el.getClientRects().length)})
          ).filter(b => b.text);
          const uploads = [...document.querySelectorAll("input[type=file]")].map(pick);
          return {title: document.title, url: location.href, inputs, uploads, buttons};
        }"""
    )
    return inputs


def fill_by_placeholder(page: Any, label_regex: str, value: str, *, exact: bool = False) -> bool:
    """按 placeholder 或 label 文本（正则）定位输入框并填值。返回是否命中。"""
    for sel in ("input", "textarea"):
        loc = page.locator(sel)
        n = loc.count()
        for i in range(n):
            el = loc.nth(i)
            try:
                ph = el.get_attribute("placeholder") or ""
                label = (el.evaluate("e => (e.closest('label')||e.parentElement)?.textContent || ''") or "")
            except Exception:
                continue
            hay = f"{ph} {label}".strip()
            if exact:
                hit = hay == label_regex
            else:
                hit = bool(re.search(label_regex, hay))
            if hit:
                el.scroll_into_view_if_needed()
                el.fill(value)
                return True
    return False


def click_by_text(page: Any, pattern: str, *, contains: bool = True, timeout_ms: int = config.ELEMENT_TIMEOUT_MS) -> bool:
    """点击第一个文本匹配的按钮/链接。返回是否命中。"""
    for sel in ("button", "a", "div[role=button]", ".btn", "[class*=btn]"):
        loc = page.locator(sel)
        n = min(loc.count(), 60)
        for i in range(n):
            el = loc.nth(i)
            try:
                text = (el.inner_text() or "").strip()
            except Exception:
                continue
            hit = pattern in text if contains else text == pattern
            if hit and text:
                try:
                    el.scroll_into_view_if_needed()
                    el.click(timeout=3000)
                    return True
                except Exception:
                    continue
    return False


def upload_file(page: Any, file_path: Path) -> bool:
    """向页面任一 file input 设置文件。返回是否命中 input。"""
    loc = page.locator("input[type=file]")
    n = loc.count()
    if n == 0:
        return False
    loc.first.set_input_files(str(file_path))
    return True


def check_if_present(page: Any, selectors: list[str]) -> bool:
    for sel in selectors:
        loc = page.locator(sel)
        if loc.count() > 0:
            try:
                loc.first.check(timeout=2000)
                return True
            except Exception:
                try:
                    loc.first.click(timeout=2000)
                    return True
                except Exception:
                    continue
    return False


def checkbox_checked(page: Any) -> bool | None:
    """页面第一个 checkbox 的勾选状态；找不到返回 None。"""
    try:
        return bool(page.locator("input[type=checkbox]").first.is_checked(timeout=1500))
    except Exception:
        return None


def is_page_undergoing(page: Any, markers: list[str]) -> bool:
    """提交/上传后页面出现这些提示语（按钮禁用、toast 等）时等待。"""
    try:
        body = page.locator("body").inner_text(timeout=3000)
    except Exception:
        return False
    for m in markers:
        if m in body:
            return True
    return False


def wait_for_text(page: Any, pattern: str, timeout_s: int = 60) -> bool:
    import time as _t

    deadline = _t.time() + timeout_s
    while _t.time() < deadline:
        try:
            body = page.locator("body").inner_text(timeout=3000)
            if re.search(pattern, body):
                return True
        except Exception:
            pass
        _t.sleep(2)
    return False
