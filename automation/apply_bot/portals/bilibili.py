"""哔哩哔哩官方招聘适配器（jobs.bilibili.com）。

2026-08-24 官方站锚点：校园实习列表 /campus/positions?type=2；岗位详情
/<channel>/positions/<id>；登录后简历页 /<channel>/resume?position=<id>；
最终站内二次确认是「投递」→「确认提交」。邮箱验证码必须由用户人工完成。

当前校园实习公开接口 total=0，因此字段映射保留 probe-first；只有出现真实匹配
实习岗位后才上传并固化，绝不拿不匹配的社会全职岗位制造申请草稿。
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .base import PortalAdapter, JobInfo, Blocked, click_by_text, dump_form_snapshot, wait_for_text
from .. import config


class BilibiliAdapter(PortalAdapter):
    name = "bilibili"
    url_patterns = ["jobs.bilibili.com"]
    home_url = "https://jobs.bilibili.com/campus/"
    login_url = "https://passport.bilibili.com/login?gourl=https%3A%2F%2Fjobs.bilibili.com%2Fcampus%2F"

    def is_logged_in(self, page: Any) -> bool:
        if "passport.bilibili.com/login" in page.url:
            return False
        try:
            body = page.locator("body").inner_text(timeout=3000)
        except Exception:
            return False
        if "/resume" in page.url or "/records" in page.url or "/me" in page.url:
            return True
        return "登录" not in body

    def login_hint(self) -> str:
        return "在哔哩哔哩登录页手动扫码/输入密码或短信验证码；完成后会回到招聘详情页"

    def open_job(self, page: Any, url: str) -> JobInfo:
        page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(2500)
        hit = re.search(r"/(campus|social)/positions/(\d+)", page.url)
        if not hit:
            raise Blocked("不是哔哩哔哩岗位详情 URL", "需要 /campus/positions/<id> 或 /social/positions/<id>", portal=self.name)
        channel, job_id = hit.groups()
        title = ""
        for selector in ["h1", "h2", ".position-title", "[class*=position-name]"]:
            loc = page.locator(selector).first
            if not loc.count():
                continue
            try:
                text = loc.inner_text(timeout=1500).strip()
            except Exception:
                continue
            if text and text not in ("职位描述", "部门介绍"):
                title = text
                break
        if not title:
            body = page.locator("body").inner_text(timeout=3000)
            lines = [x.strip() for x in body.splitlines() if x.strip()]
            marker = next((i for i, x in enumerate(lines) if x == "登录"), -1)
            title = lines[marker + 1] if marker >= 0 and marker + 1 < len(lines) else ""
        if not title:
            raise Blocked("未能解析哔哩哔哩岗位标题", "岗位可能已下架或站点结构已变化", portal=self.name)
        return JobInfo(title=title, company="哔哩哔哩", url=page.url, id=job_id, raw={"channel": channel})

    def open_apply_form(self, page: Any, job: JobInfo) -> None:
        if "/resume" in page.url:
            return
        button = page.get_by_role("button", name="投递简历", exact=True)
        if not button.count():
            raise Blocked("未找到「投递简历」按钮", "岗位可能已下架或已达到投递上限", portal=self.name)
        button.first.click(timeout=5000)
        page.wait_for_timeout(1200)
        if page.get_by_text("继续投递", exact=True).count():
            page.get_by_text("继续投递", exact=True).last.click(timeout=3000)
            page.wait_for_timeout(1000)

    def fill_form(self, page: Any, job: JobInfo, profile: dict[str, Any], resume: Path | None) -> list[str]:
        # B站登录成功会回详情页，而不是自动回简历页，因此登录后再进入一次。
        if "/resume" not in page.url and "/positions/" in page.url:
            self.open_apply_form(page, job)
        if "/resume" not in page.url:
            raise Blocked("未到达哔哩哔哩简历编辑页", "请检查登录状态；验证码由你手动完成", portal=self.name)
        if resume is None:
            raise Blocked("未找到可上传的简历", "请用 --cv 指定 PDF/DOC/DOCX", portal=self.name)

        page.wait_for_timeout(2500)
        upload = page.locator("input[type=file]").first
        if not upload.count():
            raise Blocked(
                "哔哩哔哩简历表尚未完成首次真机字段探路",
                "出现真实匹配实习岗位并登录后，依据 probe 固化表单；当前不拿全职岗位试投",
                probe=dump_form_snapshot(page),
                portal=self.name,
            )
        upload.set_input_files(str(resume))
        page.wait_for_timeout(1200)
        if page.get_by_text("是，确认覆盖", exact=False).count():
            page.get_by_text("是，确认覆盖", exact=False).last.click(timeout=5000)
        deadline = time.time() + min(config.UPLOAD_WAIT_S, 60)
        while time.time() < deadline:
            try:
                body = page.locator("body").inner_text(timeout=2500)
                if "解析完成" in body or resume.name in body:
                    break
            except Exception:
                pass
            page.wait_for_timeout(1000)

        self._manual_issues = _clear_unknown_sensitive_fields(page, profile)
        return [f"简历附件={resume.name}", "解析并覆盖在线简历"]

    def verify(self, page: Any, job: JobInfo) -> list[str]:
        issues = list(getattr(self, "_manual_issues", []))
        for selector in [".ant-form-explain:visible", ".ant-form-item-explain-error:visible", "[class*=error]:visible"]:
            errors = page.locator(selector)
            for i in range(min(errors.count(), 15)):
                try:
                    text = errors.nth(i).inner_text().strip()
                except Exception:
                    continue
                if text and len(text) < 120 and text not in issues:
                    issues.append(text)
        return issues

    def submit(self, page: Any, job: JobInfo) -> None:
        if not click_by_text(page, "投递", contains=False):
            raise Blocked("未找到哔哩哔哩「投递」按钮", "请人工检查简历表完整性", portal=self.name)
        page.wait_for_timeout(800)
        try:
            body = page.locator("body").inner_text(timeout=2000)
        except Exception:
            body = ""
        if "验证邮箱" in body or "请输入验证码" in body:
            raise Blocked("哔哩哔哩要求邮箱验证码", "请人工获取并输入验证码；不绕过验证", portal=self.name)
        if not click_by_text(page, "确认提交", contains=False):
            raise Blocked("未找到哔哩哔哩站内「确认提交」按钮", "请检查弹窗或页面校验提示", portal=self.name)

    def wait_receipt(self, page: Any, job: JobInfo, timeout_s: int = 60) -> str | None:
        return "投递成功" if wait_for_text(page, r"投递成功|提交成功|已投递", timeout_s=timeout_s) else None


def _clear_unknown_sensitive_fields(page: Any, profile: dict[str, Any]) -> list[str]:
    """解析后清除档案中未确认的出生年月及任何证件号码，不读取或记录其值。"""
    issues: list[str] = []
    identity = profile.get("identity", {})
    targets: list[tuple[str, str]] = []
    if not identity.get("birthday"):
        targets.append(("出生日期|出生年月|生日", "出生年月未在结构化档案中确认，请人工填写"))
    targets.append(("身份证|证件号码|证件号", "证件号码禁止自动填写，请在提交前按需人工处理"))
    items = page.locator(".ant-form-item")
    for pattern, issue in targets:
        for i in range(items.count()):
            item = items.nth(i)
            try:
                label = item.locator("label").first.inner_text().strip() if item.locator("label").count() else ""
            except Exception:
                continue
            if not re.search(pattern, label):
                continue
            inputs = item.locator("input")
            for j in range(inputs.count()):
                try:
                    inputs.nth(j).fill("")
                except Exception:
                    clear = item.locator(".ant-picker-clear")
                    if clear.count():
                        try:
                            item.hover()
                            clear.first.click(force=True)
                        except Exception:
                            pass
            if issue not in issues:
                issues.append(issue)
    return issues


def discover_jobs(page: Any, keyword: str = "", limit: int = 20, location: str = "", list_url: str | None = None) -> list[dict[str, Any]]:
    """调用官网页面自身使用的公开接口；默认只查校园实习，不混入社会全职。"""
    url = list_url or "https://jobs.bilibili.com/campus/positions?type=2"
    _validate_discovery_url(url)
    channel = "campus"
    page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
    page.wait_for_timeout(1800)
    result = page.evaluate(
        """async ({channel, keyword, location, limit}) => {
          const token = (await (await fetch('/api/auth/v1/csrf/token')).json()).data;
          const campus = channel === 'campus';
          const body = {
            pageSize: Math.min(limit, 50), pageNum: 1, positionName: keyword,
            postCode: [], postCodeList: [], workLocationList: location ? [location.replace(/市$/, '')] : [],
            workTypeList: [campus ? '2' : '3'], positionTypeList: [campus ? '2' : '3'],
            deptCodeList: [], recruitType: campus ? null : 0, practiceTypes: [], onlyHotRecruit: 0
          };
          const response = await fetch(`/api/${campus ? 'campus' : 'srs'}/position/positionList`, {
            method: 'POST', headers: {'content-type':'application/json','x-appkey':'ops.ehr-api.auth',
              'x-usertype':'2','x-csrf':token,'x-channel':channel}, body: JSON.stringify(body)
          });
          return await response.json();
        }""",
        {"channel": channel, "keyword": keyword, "location": location, "limit": limit},
    )
    if not isinstance(result, dict) or result.get("code") not in (None, 0):
        message = str(result.get("message") or "响应结构无效") if isinstance(result, dict) else "响应结构无效"
        raise Blocked("哔哩哔哩校园实习接口返回异常", message, portal="bilibili")
    data = result.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("list"), list):
        raise Blocked("哔哩哔哩校园实习接口结构变化", "未找到 data.list，已停止入库以避免误抓", portal="bilibili")
    rows = data["list"]
    jobs: list[dict[str, Any]] = []
    for row in rows[:limit]:
        job_id = str(row.get("id") or "")
        if not job_id:
            continue
        jobs.append({
            "title": row.get("positionName") or "(未知岗位)", "company": "哔哩哔哩",
            "url": f"https://jobs.bilibili.com/{channel}/positions/{job_id}", "id": job_id,
            "location": row.get("workLocation"), "description": row.get("positionDescription"),
        })
    return jobs


def _validate_discovery_url(url: str) -> None:
    """实习工作流禁止把社会招聘入口当成校园实习来源。"""
    if "jobs.bilibili.com" not in url or "/campus/" not in url or "/social/" in url:
        raise Blocked(
            "B站岗位来源不是校园实习入口",
            "请使用 https://jobs.bilibili.com/campus/positions?type=2；社会招聘不会写入实习岗位库",
            portal="bilibili",
        )
