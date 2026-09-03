"""智联招聘单岗位适配器（www.zhaopin.com）。

安全要点：智联详情页的「立即投递」不是进入表单，而是调用已保存简历直接提交。
官方前端工作流在只有一份简历时会从 preparation 直接进入 reqApply。因此：
- open_apply_form 只做只读检查，绝不点击；
- fill_form 只在独立简历中心准备/核验简历；
- 只有 apply_one 的终端逐岗位确认收到 y 后，submit 才点击「立即投递」。

搜索页可能出现 EdgeOne 人机验证；不绕过，适配器只处理用户提供的单岗位 URL。
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .base import PortalAdapter, JobInfo, Blocked, dump_form_snapshot, wait_for_text
from .. import config


class ZhaopinAdapter(PortalAdapter):
    name = "zhaopin"
    url_patterns = ["zhaopin.com/jobdetail/", "m.zhaopin.com/jobs/", "xiaoyuan.zhaopin.com/job/"]
    home_url = "https://www.zhaopin.com/"
    login_url = "https://passport.zhaopin.com/login"

    def is_logged_in(self, page: Any) -> bool:
        try:
            names = {c.get("name") for c in page.context.cookies()}
            if "at" in names and "rt" in names:
                return True
            if "passport.zhaopin.com" in page.url:
                return False
            body = page.locator("body").inner_text(timeout=2500)
            return "登录/注册" not in body and "验证码登录/注册" not in body
        except Exception:
            return False

    def login_hint(self) -> str:
        return "在智联招聘登录页手动完成微信扫码或短信验证码登录；不绕过安全验证"

    def open_job(self, page: Any, url: str) -> JobInfo:
        page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(3500)
        body = page.locator("body").inner_text(timeout=5000)
        if "Security Verification" in page.title() or "正在验证连接安全性" in body:
            raise Blocked("智联招聘要求人机安全验证", "请在可见浏览器中人工完成复选框验证后重跑；不做绕过", portal=self.name)
        job_id_match = re.search(r"(CCL?\d+J\d+)", page.url, re.I)
        job_id = job_id_match.group(1) if job_id_match else None
        title = ""
        for selector in ["h1", ".summary-plane__title", "[class*=job-name]", "[class*=position-name]"]:
            loc = page.locator(selector).first
            if not loc.count():
                continue
            try:
                value = loc.inner_text(timeout=1800).strip()
            except Exception:
                continue
            if value:
                title = value
                break
        if not title:
            title = page.title().split("招聘_")[0].strip()
        company = ""
        for selector in [".company-info__name", "[class*=company-name]", "a[href*=companydetail]"]:
            loc = page.locator(selector).first
            if not loc.count():
                continue
            try:
                value = loc.inner_text(timeout=1800).strip()
            except Exception:
                continue
            if value:
                company = value
                break
        if not company:
            hit = re.search(r"招聘_(.+?)招聘\s*-\s*智联招聘", page.title())
            company = hit.group(1).strip() if hit else "(智联招聘企业)"
        return JobInfo(title=title or "(未知岗位)", company=company, url=page.url, id=job_id)

    def open_apply_form(self, page: Any, job: JobInfo) -> None:
        # 绝不在这里点击「立即投递」：该按钮可能直接产生外部投递。
        try:
            body = page.locator("body").inner_text(timeout=3000)
        except Exception:
            body = ""
        if any(x in body for x in ("职位已下线", "职位已关闭", "停止招聘", "已投递")):
            raise Blocked("智联岗位已投递或已关闭", "为避免重复/错投，需人工确认后再处理", portal=self.name)

    def fill_form(self, page: Any, job: JobInfo, profile: dict[str, Any], resume: Path | None) -> list[str]:
        if resume is None:
            raise Blocked("未找到可用于智联投递的简历", "请用 --cv 指定 PDF/DOC/DOCX", portal=self.name)
        self._resume_name = resume.name
        self._manual_issues: list[str] = []

        # 在独立简历中心准备材料，不触碰岗位的一键投递按钮。
        page.goto("https://i.zhaopin.com/resume", wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(3500)
        if not self.is_logged_in(page):
            raise Blocked("智联招聘简历中心未登录", "请人工完成微信扫码/短信验证码后重跑", portal=self.name)
        body = page.locator("body").inner_text(timeout=4000)
        if "正在验证连接安全性" in body:
            raise Blocked("智联招聘要求人机安全验证", "请人工完成验证；不绕过", portal=self.name)

        uploads = page.locator("input[type=file]")
        if uploads.count():
            uploads.first.set_input_files(str(resume))
            deadline = time.time() + min(config.UPLOAD_WAIT_S, 60)
            while time.time() < deadline:
                try:
                    body = page.locator("body").inner_text(timeout=2500)
                    if resume.name in body or any(x in body for x in ("上传成功", "解析成功", "审核中")):
                        break
                except Exception:
                    pass
                page.wait_for_timeout(1000)
            return [f"智联附件简历={resume.name}", "岗位按钮未点击"]

        # 没有上传控件时，只在现有在线简历与结构化档案的关键事实一致时继续。
        identity = profile.get("identity", {})
        education = profile.get("education") or []
        facts = [str(identity.get("name") or ""), str(identity.get("phone") or ""), str(identity.get("email") or "")]
        if education:
            facts.append(str(education[0].get("school") or ""))
        present = [fact for fact in facts if fact and fact in body]
        if len(present) >= 3:
            return ["使用现有智联在线简历（关键事实已核对）", "岗位按钮未点击"]
        raise Blocked(
            "智联简历中心未找到可上传附件，且现有在线简历无法自动核对",
            "请人工完善在线简历或上传附件后重跑；不会先点「立即投递」",
            probe=dump_form_snapshot(page),
            portal=self.name,
        )

    def verify(self, page: Any, job: JobInfo) -> list[str]:
        return list(getattr(self, "_manual_issues", []))

    def submit(self, page: Any, job: JobInfo) -> None:
        # 到这里时 apply_one 已在终端展示岗位/公司/简历/字段，并收到用户输入 y。
        page.goto(job.url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(3500)
        button = _text_control(page, "立即投递")
        if button is None:
            try:
                body = page.locator("body").inner_text(timeout=2500)
            except Exception:
                body = ""
            if "已投递" in body:
                raise Blocked("该智联岗位已投递", "中止重复投递", portal=self.name)
            raise Blocked("未找到智联「立即投递」按钮", "请检查登录态、岗位状态或页面安全验证", portal=self.name)
        button.click(timeout=5000)
        page.wait_for_timeout(1200)

        # 命中多简历/附件实验时，官网会先要求选简历；此时仍在已获授权的 submit 内。
        resume_name = getattr(self, "_resume_name", "")
        if resume_name:
            choice = page.get_by_text(resume_name, exact=False)
            if choice.count():
                choice.last.click(timeout=3000)
        select_apply = _text_control(page, "投递")
        if select_apply is not None:
            select_apply.click(timeout=5000)

    def wait_receipt(self, page: Any, job: JobInfo, timeout_s: int = 45) -> str | None:
        return "投递成功" if wait_for_text(page, r"投递成功|申请成功|已投递", timeout_s=timeout_s) else None


def _text_control(page: Any, text: str):
    """在主文档及同源 job-apply frame 中找精确文本按钮；只返回，不提前点击。"""
    for frame in page.frames:
        for selector in ("button", "a", "[role=button]"):
            loc = frame.locator(selector).filter(has_text=re.compile(rf"^\s*{re.escape(text)}\s*$"))
            for i in range(loc.count()):
                el = loc.nth(i)
                try:
                    if el.is_visible():
                        return el
                except Exception:
                    continue
    return None
