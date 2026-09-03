"""BOSS直聘适配器（仅浏览/搜索，不自动沟通）。

BOSS 直聘是沟通型平台：「打招呼 / 发送简历」属于对外沟通行为，且平台对自动化
沟通有严格限制（风控、滑块验证码、限流）。本工作流遵守「对外沟通每次人工发送」
的原则，本适配器只做：
- 在复用登录态的会话中浏览职位列表/职位详情（探路或人工辅助）。
- 明确拒绝任何形式的自动打招呼/自动发送。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import PortalAdapter, JobInfo, Blocked
from .. import config


class BossAdapter(PortalAdapter):
    name = "boss"
    url_patterns = ["zhipin.com"]
    home_url = "https://www.zhipin.com/"
    login_url = "https://www.zhipin.com/web/user/?ka=header-login"

    def is_logged_in(self, page: Any) -> bool:
        try:
            body = page.locator("body").inner_text(timeout=3000)
            names = {c.get("name") for c in page.context.cookies("https://www.zhipin.com")}
        except Exception:
            return False
        return "登录/注册" not in body and ("退出" in body or bool(names & {"wt2", "t", "zp_token"}))

    def login_hint(self) -> str:
        return "在浏览器窗口完成 BOSS 直聘登录（APP 扫码）"

    def open_job(self, page: Any, url: str) -> JobInfo:
        page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(2500)
        if "/job_detail/" in url and "/job_detail/" not in page.url:
            raise Blocked(
                "BOSS 岗位详情被重定向，无法可靠核对目标岗位",
                "请人工完成登录/安全验证后重跑；不做风控绕过",
                portal=self.name,
            )
        title = ""
        for selector in [".job-name", "h1", "[class*=job-title]"]:
            loc = page.locator(selector).first
            if not loc.count():
                continue
            try:
                title = loc.inner_text(timeout=1800).strip()
            except Exception:
                continue
            if title:
                break
        company = ""
        for selector in [".company-info .name", ".company-name", "a[href*=gongsi]"]:
            loc = page.locator(selector).first
            if not loc.count():
                continue
            try:
                company = loc.inner_text(timeout=1800).strip()
            except Exception:
                continue
            if company:
                break
        body = page.locator("body").inner_text(timeout=3500)
        job_id = (re.search(r"/job_detail/([^/?]+)", page.url) or [None, None])[1]
        return JobInfo(
            title=title or page.title() or "(未知岗位)",
            company=company or "(来自BOSS直聘)",
            url=page.url,
            id=job_id,
            raw={"description": body[:12_000]},
        )

    def open_apply_form(self, page: Any, job: JobInfo) -> None:
        raise Blocked(
            "BOSS直聘为沟通型平台：发送消息/简历属于对外沟通，本工作流不自动执行，"
            "请在浏览器中人工点击「沟通/打招呼」发送（内容可先在本仓库准备）",
            portal=self.name,
        )

    def fill_form(self, page: Any, job: JobInfo, profile: dict[str, Any], resume: Path | None) -> list[str]:
        raise Blocked("BOSS直聘无标准化申请表", portal=self.name)

    def submit(self, page: Any, job: JobInfo) -> None:
        raise Blocked("BOSS直聘发送动作不自动执行", portal=self.name)


def discover_jobs(page: Any, keyword: str = "", limit: int = 20, location: str = "", list_url: str | None = None) -> list[dict[str, Any]]:
    """只读当前可见首屏，不翻页、不绕过登录/滑块/重定向。"""
    if not list_url:
        raise Blocked(
            "BOSS 搜索需要用户在浏览器中先生成筛选后的列表 URL",
            "复制当前结果页 URL 后用 --list-url 传入；本工具不构造或绕过风控参数",
            portal="boss",
        )
    page.goto(list_url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
    page.wait_for_timeout(3000)
    body = page.locator("body").inner_text(timeout=4000)
    links = page.locator("a[href*='/job_detail/']")
    if links.count() == 0:
        if any(x in body for x in ("安全验证", "滑动验证", "登录/注册")) or "/zhaopin/" not in page.url:
            raise Blocked("BOSS 列表未展示或被安全验证/重定向拦截", "请人工登录并完成验证；不做绕过", portal="boss")
        return []

    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i in range(min(links.count(), 80)):
        link = links.nth(i)
        href = link.get_attribute("href") or ""
        hit = re.search(r"/job_detail/([^/?]+)", href)
        if not hit or hit.group(1) in seen:
            continue
        seen.add(hit.group(1))
        card = link.locator("xpath=ancestor::*[contains(@class,'job-card') or contains(@class,'job-list')][1]")
        try:
            text = (card.inner_text(timeout=1200) if card.count() else link.inner_text(timeout=1200)).strip()
        except Exception:
            continue
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        if not lines:
            continue
        title = lines[0]
        if keyword and keyword not in text:
            continue
        if location and location.rstrip("市") not in text:
            continue
        company = lines[-1] if len(lines) > 1 else "(来自BOSS直聘)"
        full = href if href.startswith("http") else f"https://www.zhipin.com{href}"
        jobs.append({"title": title, "company": company, "url": full, "id": hit.group(1), "description": text})
        if len(jobs) >= limit:
            break
    return jobs
