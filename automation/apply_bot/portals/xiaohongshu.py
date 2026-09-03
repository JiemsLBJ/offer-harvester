"""小红书官方招聘适配器（job.xiaohongshu.com）。

2026-08-24 真机锚点：
- 日常实习列表：/campus/position?campusRecruitTypes=term_intern
- 详情：/campus/position/<id>，标题 .text-title.text-h2
- 申请入口：button「投递简历」
- 未登录跳转：/login?redirectUrl=.../campus/position/<id>/apply

首次登录后的申请表必须先 probe，再按可见中文标签固化；不猜测字段、不绕过
手机号验证码，提交仍由 apply_one 的逐岗位人工确认关卡控制。
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .base import PortalAdapter, JobInfo, Blocked, click_by_text, wait_for_text
from .. import config


class XiaohongshuAdapter(PortalAdapter):
    name = "xiaohongshu"
    url_patterns = ["job.xiaohongshu.com", "campus.xiaohongshu.com"]
    home_url = "https://job.xiaohongshu.com/"
    login_url = "https://job.xiaohongshu.com/login"

    def is_logged_in(self, page: Any) -> bool:
        try:
            if "/login" in page.url:
                return False
            body = page.locator("body").inner_text(timeout=3000)
        except Exception:
            return False
        if "/apply" in page.url:
            return True
        return "登录" not in body or any(k in body for k in ("退出登录", "我的申请", "个人中心"))

    def login_hint(self) -> str:
        return "在浏览器窗口完成小红书招聘登录（手机号+验证码；验证码由你手动输入）"

    def open_job(self, page: Any, url: str) -> JobInfo:
        page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(2500)
        m = re.search(r"/campus/position/(\d+)", page.url)
        job_id = m.group(1) if m else None
        title = ""
        for selector in [".text-title.text-h2", "h1", "h2", "[class*=position-title]"]:
            loc = page.locator(selector).first
            if loc.count() == 0:
                continue
            try:
                text = (loc.inner_text(timeout=2000) or "").strip()
            except Exception:
                continue
            if text and text not in ("工作职责", "任职资格"):
                title = text
                break
        if not title:
            raise Blocked("未能解析小红书岗位标题", "请确认链接为 /campus/position/<id>", portal=self.name)
        location = None
        try:
            body = page.locator("body").inner_text(timeout=3000)
            hit = re.search(r"工作地点[：:]\s*([^\n]+)", body)
            location = hit.group(1).strip() if hit else None
        except Exception:
            pass
        return JobInfo(title=title, company="小红书", url=page.url, id=job_id, raw={"location": location})

    def open_apply_form(self, page: Any, job: JobInfo) -> None:
        if "/apply" in page.url:
            return
        button = page.get_by_role("button", name="投递简历", exact=True)
        if button.count() == 0:
            raise Blocked("详情页未找到「投递简历」按钮", "岗位可能已关闭或页面结构变化", portal=self.name)
        button.first.click(timeout=5000)
        page.wait_for_timeout(1500)

    def fill_form(self, page: Any, job: JobInfo, profile: dict[str, Any], resume: Path | None) -> list[str]:
        if "/apply" not in page.url:
            raise Blocked("未到达小红书申请表", "请检查登录状态和岗位是否仍可投递", portal=self.name)
        if resume is None:
            raise Blocked("未找到可上传的简历", "请用 --cv 指定 PDF/DOC/DOCX 简历", portal=self.name)

        fields: list[str] = []
        self._manual_issues: list[str] = []

        # 页面有两个 file input：第一个是主简历，第二个是可选补充附件。
        uploads = page.locator("input[type=file]")
        if uploads.count() == 0:
            raise Blocked("未找到小红书简历上传控件", "申请表结构可能已改版，请重新 probe", portal=self.name)
        uploads.first.set_input_files(str(resume))
        deadline = time.time() + min(config.UPLOAD_WAIT_S, 45)
        parsed = False
        while time.time() < deadline:
            try:
                body = page.locator("body").inner_text(timeout=2500)
                parsed = resume.name in body or "重新上传" in body or "上传成功" in body
                if parsed:
                    break
            except Exception:
                pass
            page.wait_for_timeout(1000)
        if not parsed:
            raise Blocked("小红书简历上传/解析未出现成功信号", "请人工检查文件格式、大小及页面提示", portal=self.name)
        fields.append(f"简历附件={resume.name}")

        identity = profile.get("identity", {})
        identity_fields = [
            ("form_item_name", identity.get("name"), "姓名"),
            ("form_item_email", identity.get("email"), "邮箱"),
        ]
        for field_id, value, label in identity_fields:
            if value and _fill_input(page, field_id, str(value)):
                fields.append(label)

        phone = identity.get("phone")
        phone_input = page.locator("input#form_item_mobile[type=text]").last
        if phone and phone_input.count():
            phone_input.fill(str(phone))
            fields.append("手机号")

        # 官网会从 PDF 自动推断出生年月；结构化档案没有该事实时必须清空，
        # 不能把解析器猜测当作候选人事实，也不能把值写入日志。
        birthday = identity.get("birthday")
        if birthday:
            if _set_month(page, "form_item_birthday", str(birthday)):
                fields.append("出生年月")
        else:
            birthday_input = page.locator("#form_item_birthday").first
            if birthday_input.count():
                try:
                    if birthday_input.input_value():
                        _clear_picker(page, "form_item_birthday")
                except Exception:
                    pass
            self._manual_issues.append("出生年月未在结构化档案中确认，请人工填写")

        availability = profile.get("availability", {})
        if _select_option(page, "form_item_resumeVo_internEntryDate", "1周内"):
            fields.append("到岗时间=1周内")
        if _select_option(page, "form_item_resumeVo_internshipTime", "3-6个月"):
            fields.append("实习时长=3-6个月")

        days = str(availability.get("days_per_week") or "")
        day_option = "5天" if "5" in days else "4天" if "4" in days else ""
        if day_option and _select_option(page, "form_item_resumeVo_internDayPerWeek", day_option):
            fields.append(f"每周出勤={day_option}")

        education = profile.get("education") or []
        highest = education[0] if education else {}
        level = str(highest.get("level") or "")
        level_option = "硕士" if "硕士" in level else "本科" if "本科" in level else ""
        if level_option and _select_option(page, "form_item_highestEducation", level_option):
            status = str(highest.get("status") or "")
            suffix = f"（{status}）" if status else ""
            fields.append(f"最高学历={level_option}{suffix}")
        school = highest.get("school")
        if school and _fill_input(page, "form_item_highestEducationCollege", str(school)):
            fields.append("最高学历学校")
        graduation = _year_month(str(highest.get("end") or ""))
        if graduation and _set_month(page, "form_item_graduationDate", graduation):
            fields.append(f"毕业时间={graduation}")

        return fields

    def verify(self, page: Any, job: JobInfo) -> list[str]:
        issues = list(getattr(self, "_manual_issues", []))
        required = {
            "form_item_name": "姓名",
            "form_item_birthday": "出生年月",
            "form_item_mobile": "手机号",
            "form_item_email": "邮箱",
            "form_item_highestEducationCollege": "最高学历学校",
            "form_item_graduationDate": "毕业时间",
        }
        for field_id, label in required.items():
            loc = page.locator(f"#{field_id}").last
            if loc.count() == 0:
                issues.append(f"未找到字段：{label}")
                continue
            try:
                if not loc.input_value().strip() and not (label == "出生年月" and any("出生年月" in x for x in issues)):
                    issues.append(f"必填项为空：{label}")
            except Exception:
                pass

        selects = {
            "form_item_resumeVo_internEntryDate": "到岗时间",
            "form_item_resumeVo_internshipTime": "实习时长",
            "form_item_resumeVo_internDayPerWeek": "每周出勤",
            "form_item_highestEducation": "最高学历",
        }
        for field_id, label in selects.items():
            if not _selected_text(page, field_id):
                issues.append(f"必填项为空：{label}")

        errors = page.locator(".ant-form-item-explain-error:visible")
        for i in range(min(errors.count(), 10)):
            try:
                text = errors.nth(i).inner_text().strip()
            except Exception:
                continue
            if text and "出生年月" in text and any("出生年月" in x for x in issues):
                continue
            if text and text not in issues:
                issues.append(text)
        return issues

    def submit(self, page: Any, job: JobInfo) -> None:
        for label in ["提交申请", "提交简历", "确认投递", "提交"]:
            if click_by_text(page, label, contains=True):
                return
        raise Blocked("未找到小红书最终提交按钮", "请按申请表 probe 更新提交锚点", portal=self.name)

    def wait_receipt(self, page: Any, job: JobInfo, timeout_s: int = 60) -> str | None:
        if wait_for_text(page, r"申请成功|投递成功|已投递|提交成功", timeout_s=timeout_s):
            return "投递成功"
        return None


def _fill_input(page: Any, field_id: str, value: str) -> bool:
    loc = page.locator(f"#{field_id}").last
    if loc.count() == 0:
        return False
    loc.scroll_into_view_if_needed()
    loc.fill(value)
    return True


def _select_option(page: Any, field_id: str, option: str) -> bool:
    """按已真机确认的 Ant Design 下拉项文本选择，不依赖易变 class 层级。"""
    loc = page.locator(f"#{field_id}").first
    if loc.count() == 0:
        return False
    root = loc.locator("xpath=ancestor::*[contains(concat(' ',normalize-space(@class),' '),' ant-select ')][1]")
    for _ in range(2):
        try:
            root.scroll_into_view_if_needed()
            root.locator(".ant-select-selector").click(force=True)
            dropdown = page.locator(".ant-select-dropdown:visible").last
            dropdown.wait_for(state="visible", timeout=3000)
            target = dropdown.get_by_text(option, exact=True).last
            if target.count() == 0:
                page.keyboard.press("Escape")
                continue
            target.click(timeout=3000)
            page.wait_for_timeout(200)
            if _selected_text(page, field_id) == option:
                return True
        except Exception:
            page.keyboard.press("Escape")
        page.wait_for_timeout(250)
    return False


def _selected_text(page: Any, field_id: str) -> str:
    loc = page.locator(f"#{field_id}").first
    if loc.count() == 0:
        return ""
    root = loc.locator("xpath=ancestor::*[contains(concat(' ',normalize-space(@class),' '),' ant-select ')][1]")
    selected = root.locator(".ant-select-selection-item")
    try:
        return selected.first.inner_text().strip() if selected.count() else ""
    except Exception:
        return ""


def _year_month(raw: str) -> str | None:
    hit = re.search(r"(20\d{2})[-/.年](\d{1,2})", raw)
    return f"{hit.group(1)}-{int(hit.group(2)):02d}" if hit else None


def _set_month(page: Any, field_id: str, value: str) -> bool:
    """通过 Ant Design MonthPicker 的可见年/月面板填写 YYYY-MM。"""
    hit = re.fullmatch(r"(20\d{2})-(\d{2})", value)
    if not hit:
        return False
    year, month = hit.group(1), int(hit.group(2))
    loc = page.locator(f"#{field_id}").first
    if loc.count() == 0:
        return False
    loc.scroll_into_view_if_needed()
    loc.click(force=True)
    dropdown = page.locator(".ant-picker-dropdown:visible").last
    try:
        dropdown.wait_for(state="visible", timeout=3000)
        dropdown.locator(".ant-picker-year-btn").click(timeout=3000)
        year_cell = dropdown.locator(".ant-picker-cell-inner", has_text=re.compile(rf"^{year}$"))
        if year_cell.count() == 0:
            page.keyboard.press("Escape")
            return False
        year_cell.first.click(timeout=3000)
        month_text = f"{month}月"
        month_cell = dropdown.locator(".ant-picker-cell-inner", has_text=re.compile(rf"^{month_text}$"))
        if month_cell.count() == 0:
            page.keyboard.press("Escape")
            return False
        month_cell.first.click(timeout=3000)
        return True
    except Exception:
        page.keyboard.press("Escape")
        return False


def _clear_picker(page: Any, field_id: str) -> bool:
    loc = page.locator(f"#{field_id}").first
    if loc.count() == 0:
        return False
    picker = loc.locator("xpath=ancestor::*[contains(concat(' ',normalize-space(@class),' '),' ant-picker ')][1]")
    try:
        picker.hover()
        clear = picker.locator(".ant-picker-clear")
        if clear.count():
            clear.click(force=True)
            return True
    except Exception:
        pass
    return False


def discover_jobs(
    page: Any,
    keyword: str = "",
    limit: int = 20,
    location: str = "",
    list_url: str | None = None,
) -> list[dict[str, Any]]:
    """通过公开日常实习列表发现岗位；低频个人使用，不翻页爬取。"""
    url = list_url or "https://job.xiaohongshu.com/campus/position?campusRecruitTypes=term_intern"
    if keyword and not list_url:
        url += f"&positionName={quote(keyword)}"
    page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
    deadline = time.time() + 12
    while time.time() < deadline:
        if page.locator("a[href*='/campus/position/']").count() > 0:
            break
        page.wait_for_timeout(800)

    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    links = page.locator("a[href*='/campus/position/']")
    for i in range(links.count()):
        link = links.nth(i)
        href = link.get_attribute("href") or ""
        m = re.search(r"/campus/position/(\d+)", href)
        if not m or href in seen:
            continue
        seen.add(href)
        try:
            text = (link.inner_text(timeout=1500) or "").strip()
        except Exception:
            continue
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            continue
        title = lines[0]
        city_line = next((line for line in lines[1:4] if re.search(r"市|新加坡|其他", line)), "")
        if location and location.rstrip("市") not in city_line:
            continue
        full = href if href.startswith("http") else f"https://job.xiaohongshu.com{href}"
        jobs.append({"title": title, "company": "小红书", "url": full, "id": m.group(1), "location": city_line or None})
        if len(jobs) >= limit:
            break
    return jobs
