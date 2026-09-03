"""牛客网适配器（发现+半自动）。

2026-08 探测结论：牛客实习中心的搜索结果由客户端 JS 在登录后拉取
（SSR 状态内 jobList=null），且投递通常跳转企业官方网站/内推渠道。
因此本适配器不做独立抓取 CLI，也不自动完成牛客侧投递：
- 发现：在已有登录态的浏览器会话中打开求职中心人工/半自动浏览（可复用会话）。
- 投递：点击「投递」后若跳转企业官网，转用对应企业适配器；否则提示人工继续。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import PortalAdapter, JobInfo, Blocked
from .. import config


class NowcoderAdapter(PortalAdapter):
    name = "nowcoder"
    url_patterns = ["nowcoder.com"]
    login_url = "https://www.nowcoder.com/login"

    def is_logged_in(self, page: Any) -> bool:
        try:
            body = page.locator("body").inner_text(timeout=3000)
        except Exception:
            return False
        return ("退出登录" in body) or (page.url and "login" not in page.url.lower() and "个人中心" in body)

    def login_hint(self) -> str:
        return "在浏览器窗口完成牛客网登录（微信/手机号+验证码）"

    def open_job(self, page: Any, url: str) -> JobInfo:
        page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(2000)
        title = ""
        try:
            title = page.locator("h1").first.inner_text(timeout=3000).strip() or page.title()
        except Exception:
            title = page.title()
        return JobInfo(title=title or "(未知岗位)", company="(来自牛客)", url=page.url)

    def open_apply_form(self, page: Any, job: JobInfo) -> None:
        raise Blocked(
            "牛客「投递」通常跳转企业官网或内推渠道——请在浏览器中点击投递后，"
            "若为其他站点请用对应站点 URL 重新运行 apply_one.py",
            "本适配器用于发现与复用登录态；投递不自动执行",
            portal=self.name,
        )

    def fill_form(self, page: Any, job: JobInfo, profile: dict[str, Any], resume: Path | None) -> list[str]:
        raise Blocked("牛客侧无标准化申请表，不自动填写", portal=self.name)

    def submit(self, page: Any, job: JobInfo) -> None:
        raise Blocked("牛客侧投递不自动执行", portal=self.name)
