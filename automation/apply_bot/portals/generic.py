"""未知招聘官网的保守通用填表适配器。

它只接受用户已经打开或明确提供的“申请表直达 URL”，不寻找/点击申请按钮，
不猜测文件上传控件用途，也永远不提交。真正的普通字段回填由 apply_one 统一调用
form_learning.fill_learned_fields 完成；未识别字段会进入本机资料缺口队列。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .base import Blocked, JobInfo, PortalAdapter, dump_form_snapshot
from .. import config


class GenericFormAdapter(PortalAdapter):
    name = "generic"
    # 故意为空：未知 URL 绝不自动落入通用适配，必须显式 --portal generic。
    url_patterns: list[str] = []

    def is_logged_in(self, page: Any) -> bool:
        if page.url == "about:blank":
            return True
        try:
            passwords = page.locator("input[type=password]")
            for index in range(passwords.count()):
                if passwords.nth(index).is_visible():
                    return False
            body = page.locator("body").inner_text(timeout=2500)
            # Some ATS products render the whole application form behind a login
            # modal. Counting every visible form field therefore misclassifies the
            # page as logged in. Explicit login controls take precedence.
            login_controls = page.locator(
                'input[placeholder*="verification code" i]:visible, '
                'input[placeholder*="enter email" i]:visible, '
                'input[placeholder*="验证码"]:visible'
            )
            if login_controls.count() and re.search(
                r"sign\s*in|log\s*in|email\s*login|phone\s*number\s*login|登录|验证码登录",
                body, re.I,
            ):
                return False
            visible_inputs = page.locator("input:visible, textarea:visible, select:visible").count()
            login_only = re.search(r"登录|扫码登录|验证码登录|sign\s*in|log\s*in", body, re.I)
            return not bool(login_only and visible_inputs <= 4)
        except Exception:
            return True

    def login_hint(self) -> str:
        return "请在当前官网手动完成登录/扫码/验证码，并停留在申请表页面；通用适配不会绕过验证"

    def open_job(self, page: Any, url: str) -> JobInfo:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise Blocked("通用适配只接受 http/https 的申请表直达 URL", portal=self.name)
        page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(2500)
        title = _first_text(page, ["h1", "[class*=job-title]", "[class*=position-title]"])
        if not title:
            title = (page.title() or "未知岗位").strip()
        company = _meta_content(page, "meta[property='og:site_name']") or parsed.hostname or "未知公司"
        return JobInfo(title=title[:160], company=company[:120], url=page.url)

    def open_apply_form(self, page: Any, job: JobInfo) -> None:
        snapshot = dump_form_snapshot(page)
        usable = [
            item for item in snapshot.get("inputs", [])
            if item.get("visible") and item.get("type") not in {"hidden", "button", "submit", "search"}
        ]
        if not usable:
            raise Blocked(
                "当前页面没有可见申请表字段",
                "请先人工进入真正的申请表页面，再复制该页面 URL 并重跑；通用适配不会猜测或点击申请按钮",
                probe=snapshot,
                portal=self.name,
            )

    def fill_form(
        self, page: Any, job: JobInfo, profile: dict[str, Any], resume: Path | None,
    ) -> list[str]:
        fields = ["启用通用字段结构识别"]
        uploaded = False

        # QQ Docs questionnaires use custom widgets that expose only one textarea
        # and a hidden file input in a static snapshot. Fill this narrow, verified
        # form only when host, identity prompt, and resume label all match.
        if _is_qqdocs_resume_form(page):
            textareas = page.locator("textarea:visible")
            if textareas.count() == 1:
                target = textareas.first
                identity_line = _qqdocs_identity_line(profile)
                if identity_line and not (target.input_value() or "").strip():
                    target.fill(identity_line)
                    fields.append("腾讯文档:姓名/学校/专业/毕业时间")

            if resume is not None:
                # Assigning QQ Docs' hidden file input directly does not update
                # its form state. Use only the visible, explicit file control and
                # require UI evidence before recording the upload as successful.
                add_file = page.get_by_text(re.compile(r"^\s*添加文件\s*$"), exact=False)
                visible_triggers = []
                for index in range(min(add_file.count(), 4)):
                    try:
                        trigger = add_file.nth(index)
                        if trigger.is_visible():
                            visible_triggers.append(trigger)
                    except Exception:
                        continue
                # Multiple upload questions are ambiguous: do not guess which
                # visible picker belongs to the resume field.
                if len(visible_triggers) == 1:
                    try:
                        trigger = visible_triggers[0]
                        with page.expect_file_chooser(timeout=5000) as chooser:
                            trigger.click()
                        chooser.value.set_files(str(resume))
                        for _ in range(15):
                            if _resume_upload_visible(page, resume.name):
                                uploaded = True
                                fields.append(f"上传简历:{resume.name}")
                                break
                            page.wait_for_timeout(1000)
                    except Exception:
                        pass

        # Never use "the first file input" on an unknown site. A chooser is safe
        # only when the visible trigger explicitly says resume/CV.
        if resume is not None and not uploaded:
            for pattern in (r"上传简历", r"upload\s+(?:resume|cv)", r"resume\s+upload"):
                trigger = page.get_by_text(re.compile(pattern, re.I), exact=False)
                for index in range(min(trigger.count(), 8)):
                    item = trigger.nth(index)
                    try:
                        if not item.is_visible():
                            continue
                        with page.expect_file_chooser(timeout=3000) as chooser:
                            item.click()
                        chooser.value.set_files(str(resume))
                        uploaded = True
                        fields.append(f"上传简历:{resume.name}")
                        break
                    except Exception:
                        continue
                if uploaded:
                    break
        if not uploaded:
            fields.append("未自动上传附件（未发现明确标注为简历/CV的上传控件）")
        fields.append("未点击任何申请/提交按钮")
        return fields

    def verify(self, page: Any, job: JobInfo) -> list[str]:
        issues: list[str] = []
        for selector in ("[role=alert]", ".error-message", ".field-error", ".ant-form-item-explain-error"):
            loc = page.locator(selector)
            for index in range(min(loc.count(), 20)):
                try:
                    item = loc.nth(index)
                    if item.is_visible():
                        text = re.sub(r"\s+", " ", item.inner_text()).strip()
                        if text:
                            issues.append(text[:160])
                except Exception:
                    continue
        return list(dict.fromkeys(issues))

    def submit(self, page: Any, job: JobInfo) -> None:
        raise Blocked(
            "通用适配器禁止自动提交",
            "请在可见浏览器中逐字段检查后人工提交；需要自动提交时必须先开发并验证该站点的专用适配器",
            portal=self.name,
        )


def _first_text(page: Any, selectors: list[str]) -> str:
    for selector in selectors:
        loc = page.locator(selector).first
        try:
            if loc.count() and loc.is_visible():
                value = re.sub(r"\s+", " ", loc.inner_text()).strip()
                if value:
                    return value
        except Exception:
            continue
    return ""


def _meta_content(page: Any, selector: str) -> str:
    try:
        loc = page.locator(selector).first
        return (loc.get_attribute("content") or "").strip() if loc.count() else ""
    except Exception:
        return ""


def _resume_upload_visible(page: Any, filename: str) -> bool:
    try:
        matches = page.get_by_text(filename, exact=False)
        for index in range(min(matches.count(), 6)):
            if matches.nth(index).is_visible():
                return True
        body = page.locator("body").inner_text(timeout=2500)
        return bool(re.search(r"上传成功|重新上传|删除文件", body))
    except Exception:
        return False


def _is_qqdocs_resume_form(page: Any) -> bool:
    try:
        host = (urlsplit(page.url).hostname or "").lower()
        if host != "docs.qq.com":
            return False
        body = page.locator("body").inner_text(timeout=2500)
        identity_prompt = re.search(
            r"姓名\s*\+\s*学校\s*\+\s*专业方向[\s\S]{0,80}毕业时间",
            body,
        )
        return bool(identity_prompt and "简历" in body)
    except Exception:
        return False


def _qqdocs_identity_line(profile: dict[str, Any]) -> str:
    identity = profile.get("identity", {})
    education = profile.get("education", [])
    bachelor = next((item for item in education if item.get("level") == "本科"), {})
    master = next((item for item in education if "硕士" in str(item.get("level", ""))), {})
    graduation = re.sub(r"（预计）|\(预计\)", "", str(master.get("end", ""))).strip()
    if re.fullmatch(r"\d{4}-\d{2}", graduation):
        year, month = graduation.split("-", 1)
        graduation = f"{year}年{int(month)}月"
    required = (
        identity.get("name"),
        bachelor.get("school"),
        bachelor.get("major"),
        master.get("school"),
        master.get("major"),
        graduation,
    )
    if not all(str(value or "").strip() for value in required):
        return ""
    return (
        f"{identity.get('name', '')} + "
        f"本科：{bachelor.get('school', '')}{bachelor.get('major', '')}，"
        f"研究生：{master.get('school', '')}{master.get('major', '')} + "
        f"预计{graduation}毕业"
    )
