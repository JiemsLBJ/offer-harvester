"""Wecruit/Hotjob 单岗位适配器（先覆盖已验证的新一代 wecruit.hotjob.cn）。

公开岗位身份由 listPositionDetail API 校验；浏览器只负责官方登录、简历上传、
结构化字段回填与人工审核。详情页的 `.deliver` 只是进入登录/简历预览，最终提交
仍只能由 apply_one 的逐岗位确认关卡触发。

未知或改版后的登录态表单会保存静态 probe 并停止。不会读取输入值、猜测证件附件、
绕过验证码，亦不会把旧版 `www.hotjob.cn/wt/...` 未验证页面冒充为已支持。
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

from .base import Blocked, JobInfo, PortalAdapter, dump_form_snapshot, fill_by_placeholder, proxy_url, wait_for_text
from .. import config


DELOITTE_TENANT = "SU64365a780dcad43c5ae82bab"
TENANT_EMPLOYERS = {DELOITTE_TENANT: "德勤"}


def parse_hotjob_url(url: str) -> tuple[str, str, str] | None:
    """返回 (tenant, post_id, post_type)，只接受真实单岗位详情 URL。"""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if parsed.hostname != "wecruit.hotjob.cn" or "/pb/posDetail.html" not in parsed.path:
        return None
    tenant_match = re.search(r"/(SU[a-zA-Z0-9]+)/pb/posDetail\.html$", parsed.path)
    query = urllib.parse.parse_qs(parsed.query)
    post_id = (query.get("postId") or [""])[0]
    post_type = (query.get("postType") or ["intern"])[0]
    if not tenant_match or not re.fullmatch(r"[a-fA-F0-9]{24}", post_id):
        return None
    return tenant_match.group(1), post_id.lower(), post_type


def canonical_hotjob_url(tenant: str, post_id: str) -> str:
    return (
        f"https://wecruit.hotjob.cn/{tenant}/pb/posDetail.html?"
        f"postId={urllib.parse.quote(post_id)}&postType=intern"
    )


def _api_post(path: str, tenant: str, data: dict[str, str], timeout: int = 25) -> dict[str, Any]:
    payload = urllib.parse.urlencode(data).encode("utf-8")
    url = f"https://wecruit.hotjob.cn/wecruit{path}/{urllib.parse.quote(tenant)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; apply-bot/1.0; personal-use)",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": f"https://wecruit.hotjob.cn/{tenant}/pb/interns.html",
    }
    proxy = proxy_url()
    handlers = [urllib.request.ProxyHandler({})]
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    last_error: Exception | None = None
    for handler in handlers:
        try:
            opener = urllib.request.build_opener(handler)
            request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            with opener.open(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as error:
            last_error = error
    raise last_error or RuntimeError(f"Hotjob API request failed: {path}")


def fetch_hotjob_detail(tenant: str, post_id: str) -> dict[str, Any]:
    response = _api_post(
        "/positionInfo/listPositionDetail", tenant,
        {"postId": post_id, "recruitType": "12"},
    )
    data = response.get("data") if response.get("state") == "200" else None
    if not isinstance(data, dict) or not data.get("postName"):
        raise Blocked(
            f"Hotjob 详情接口未返回岗位（state={response.get('state') or 'none'}）",
            "岗位可能已关闭或站点接口已改版；请重新运行 /scrape health 后再处理",
            portal="hotjob",
        )
    return data


def _visible_text(page: Any) -> str:
    try:
        return page.locator("body").inner_text(timeout=3500)
    except Exception:
        return ""


def resume_readiness_issues(text: str) -> list[str]:
    """从 Hotjob 最终审核弹层识别在线简历完整度警告。"""
    issues: list[str] = []
    compact = re.sub(r"\s+", " ", text or "")
    match = re.search(r"简历完整度[:：]?\s*中文\s*(\d+)%\s*英文\s*(\d+)%", compact, re.I)
    if match:
        chinese, english = int(match.group(1)), int(match.group(2))
        if chinese < 100 or english < 100:
            issues.append(f"Hotjob在线简历完整度：中文{chinese}%，英文{english}%")
    if "待完善" in compact:
        issues.append("Hotjob在线简历状态为待完善")
    if "请完善英文简历" in compact:
        issues.append("Hotjob提示请完善英文简历")
    return list(dict.fromkeys(issues))


def _click_exact_in(page: Any, roots: list[str], labels: list[str]) -> str | None:
    """在弹层/表单内点击精确按钮；不触碰详情页 `.deliver`。"""
    for root in roots:
        containers = page.locator(root)
        for container_index in range(min(containers.count(), 8)):
            container = containers.nth(container_index)
            try:
                if not container.is_visible():
                    continue
            except Exception:
                continue
            for label in labels:
                candidates = container.locator("button, a, [role=button]")
                for index in range(min(candidates.count(), 80)):
                    item = candidates.nth(index)
                    try:
                        text = re.sub(r"\s+", "", item.inner_text()).strip()
                        if text == label and item.is_visible():
                            item.click(timeout=4000)
                            return label
                    except Exception:
                        continue
    return None


def _has_exact_in(page: Any, roots: list[str], labels: list[str]) -> str | None:
    """只检测弹层/表单内的精确按钮，不触发任何点击。"""
    for root in roots:
        containers = page.locator(root)
        for container_index in range(min(containers.count(), 8)):
            container = containers.nth(container_index)
            try:
                if not container.is_visible():
                    continue
            except Exception:
                continue
            candidates = container.locator("button, a, [role=button]")
            for index in range(min(candidates.count(), 80)):
                item = candidates.nth(index)
                try:
                    text = re.sub(r"\s+", "", item.inner_text()).strip()
                    if text in labels and item.is_visible():
                        return text
                except Exception:
                    continue
    return None


def _resume_upload(page: Any, resume: Path) -> bool:
    inputs = page.locator("input[type=file]")
    for index in range(inputs.count()):
        item = inputs.nth(index)
        try:
            meta = item.evaluate(
                """el => {
                  const box = el.closest('label, .form-item, .ant-form-item, .el-form-item, .upload, [class*=upload]') || el.parentElement;
                  return {label: (box?.textContent || '').trim().slice(0, 160), accept: el.accept || '', name: el.name || '', id: el.id || ''};
                }"""
            )
            haystack = " ".join(str(meta.get(key) or "") for key in ("label", "accept", "name", "id"))
            if not re.search(r"简历|resume|curriculum|cv|附件", haystack, re.I):
                continue
            item.set_input_files(str(resume))
            return True
        except Exception:
            continue
    return False


def _click_verified_delivery(button: Any) -> None:
    """点击已由调用方完成文案校验的 `.deliver` 按钮。

    Hotjob 的固定顶部导航在部分窗口尺寸会覆盖按钮的可点击坐标。普通点击只有在
    明确报告 ``intercepts pointer events`` 时，才退回到该精确 DOM 元素自身的
    ``click()``；不会按模糊文本查找或触碰任何最终提交按钮。
    """
    try:
        button.click(timeout=5000)
    except Exception as error:
        if "intercepts pointer events" not in str(error):
            raise
        button.evaluate("el => el.click()")


class HotjobAdapter(PortalAdapter):
    name = "hotjob"
    url_patterns = ["wecruit.hotjob.cn/"]

    def is_logged_in(self, page: Any) -> bool:
        try:
            state = page.evaluate(
                """() => ({
                  username: localStorage.getItem('username') || '',
                  loginType: localStorage.getItem('loginType') || ''
                })"""
            )
            if state.get("username"):
                return True
        except Exception:
            pass
        body = _visible_text(page)
        if re.search(r"登录/注册|验证码登录|扫码登录|手机号登录", body):
            return False
        if re.search(r"退出登录|我的投递|个人简历", body):
            return True
        # Hotjob 登录后的“选择/新增简历”弹层不总是显示用户名或“我的投递”，
        # 但它只会在投递入口完成鉴权后出现。登录弹层已由上面的明确文案排除，
        # 因此这里可把可见的简历申请弹层认作已登录，避免无限等待。
        try:
            application_dialogs = page.locator(
                ".ant-modal:visible, [role=dialog]:visible, .modal:visible"
            )
            for index in range(min(application_dialogs.count(), 6)):
                text = application_dialogs.nth(index).inner_text(timeout=1200)
                if re.search(r"选择简历|新增简历|新建简历|完善简历|编辑简历|上传简历", text):
                    return True
        except Exception:
            pass
        return False

    def login_hint(self) -> str:
        return "在当前 Hotjob/Wecruit 页面手动完成手机号验证码或扫码登录；完成后不要关闭浏览器"

    def open_job(self, page: Any, url: str) -> JobInfo:
        parsed = parse_hotjob_url(url)
        if not parsed:
            raise Blocked(
                "Hotjob 适配器只接受 pb/posDetail.html 的单岗位直达 URL",
                "请先用 hotjob-search CLI 或 /scrape 获取带 postId 的真实岗位链接",
                portal=self.name,
            )
        tenant, post_id, _ = parsed
        page.goto(canonical_hotjob_url(tenant, post_id), wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(2500)
        detail = fetch_hotjob_detail(tenant, post_id)
        deadline = str(detail.get("endDate") or "")[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", deadline) and deadline < date.today().isoformat():
            raise Blocked("Hotjob 岗位已过截止日期", f"官网截止日期：{deadline}", portal=self.name)
        if detail.get("canDelivery") is False:
            raise Blocked("Hotjob 详情接口显示当前岗位不可投递", "可能已投递、已关闭或达到项目投递上限，请人工核验", portal=self.name)
        employer = TENANT_EMPLOYERS.get(tenant) or re.sub(r"招聘$", "", page.title()).strip() or "Hotjob 企业"
        return JobInfo(
            title=str(detail["postName"]).strip(), company=employer,
            url=canonical_hotjob_url(tenant, post_id), id=post_id,
            raw={
                "tenant": tenant,
                "deadline": deadline or None,
                "location": detail.get("workPlaceStr"),
                "department": detail.get("department"),
                "post_code": detail.get("postCode"),
                "can_delivery": detail.get("canDelivery"),
            },
        )

    def open_apply_form(self, page: Any, job: JobInfo) -> None:
        body = _visible_text(page)
        if re.search(r"职位已关闭|停止招聘|已投递|已申请", body):
            raise Blocked("Hotjob 页面显示岗位已投递或已关闭", "请人工核验岗位状态，系统不会重复点击", portal=self.name)
        button = page.locator("button.deliver:visible").first
        if button.count() == 0:
            raise Blocked(
                "Hotjob 详情页未找到已验证的投递入口 `.deliver`",
                "站点结构可能改版；已停止，避免把其他按钮误当作投递入口",
                probe=dump_form_snapshot(page), portal=self.name,
            )
        try:
            label = re.sub(r"\s+", "", button.inner_text()).strip()
        except Exception:
            label = ""
        if label and not re.search(r"投递|申请|简历", label):
            raise Blocked(f"Hotjob 投递入口文案异常：{label}", probe=dump_form_snapshot(page), portal=self.name)
        _click_verified_delivery(button)
        page.wait_for_timeout(2200)

    def fill_form(self, page: Any, job: JobInfo, profile: dict[str, Any], resume: Path | None) -> list[str]:
        filled: list[str] = []

        # 登录完成后站点有时关闭登录弹层但不自动恢复投递预览；只重开已验证入口。
        usable = page.locator("input:visible, textarea:visible, select:visible").count()
        if usable == 0 and page.locator("button.deliver:visible").count() and self.is_logged_in(page):
            _click_verified_delivery(page.locator("button.deliver:visible").first)
            page.wait_for_timeout(1800)

        # 隐私提示只推进到简历预览，不是岗位提交。按钮必须位于含隐私文本的弹层。
        dialogs = page.locator(".ant-modal:visible, [role=dialog]:visible, .modal:visible")
        for index in range(min(dialogs.count(), 6)):
            dialog = dialogs.nth(index)
            try:
                text = dialog.inner_text(timeout=1500)
            except Exception:
                continue
            if re.search(r"隐私|个人信息|数据保护", text):
                clicked = _click_exact_in(page, [".ant-modal:visible", "[role=dialog]:visible", ".modal:visible"], ["同意并继续", "继续", "确定"])
                if clicked:
                    filled.append(f"隐私提示={clicked}")
                    page.wait_for_timeout(1500)
                break

        # 若当前预览只提供“新增/完善简历”，可安全进入编辑页；绝不点击“投递/提交”。
        navigation = _click_exact_in(
            page,
            [".ant-modal:visible", "[role=dialog]:visible", ".modal:visible", "main", "#root"],
            ["新增简历", "新建简历", "完善简历", "编辑简历", "上传简历"],
        )
        if navigation:
            filled.append(f"进入{navigation}")
            page.wait_for_timeout(2000)

        if resume is None:
            resume = config.find_resume(job.company)
        if resume is None:
            raise Blocked("未找到岗位定向简历，请用 --cv 指定", portal=self.name)

        uploaded = _resume_upload(page, resume)
        if uploaded:
            filled.append(f"简历附件={resume.name}")
            page.wait_for_timeout(3500)
            if not wait_for_text(page, rf"{re.escape(resume.name)}|上传成功|更换简历|删除", timeout_s=15):
                raise Blocked(
                    "Hotjob 设置了简历文件，但未检测到页面成功信号",
                    "请人工检查文件名或上传状态；超时不等于失败，因此未继续到提交",
                    probe=dump_form_snapshot(page), portal=self.name,
                )

        identity = profile.get("identity", {})
        for label, pattern, value in [
            ("姓名", r"姓名|Name", identity.get("name")),
            ("手机号", r"手机|手机号|联系电话|Phone|Mobile", identity.get("phone")),
            ("邮箱", r"邮箱|电子邮件|Email|E-mail", identity.get("email")),
            ("出生日期", r"出生日期|出生年月|Birthday", identity.get("birthday")),
        ]:
            if value and fill_by_placeholder(page, pattern, str(value)):
                filled.append(label)

        introduction = profile.get("self_intro", {}).get("zh_200") or profile.get("self_intro", {}).get("zh_60")
        if introduction and fill_by_placeholder(page, r"自我介绍|个人简介|个人优势|Self.?introduction", str(introduction)):
            filled.append("自我介绍")
        availability = profile.get("availability", {})
        if availability.get("days_per_week") and fill_by_placeholder(page, r"每周.*天|实习天数|Days per week", str(availability["days_per_week"])):
            filled.append("每周到岗天数")
        if availability.get("min_months") and fill_by_placeholder(page, r"实习.*月|实习时长|Duration", str(availability["min_months"])):
            filled.append("实习月数")

        # 只勾选明确带协议/隐私语义的 checkbox，避免误选岗位、地点或志愿。
        checkboxes = page.locator("input[type=checkbox]")
        for index in range(checkboxes.count()):
            item = checkboxes.nth(index)
            try:
                label = item.evaluate(
                    "el => (el.closest('label, .ant-checkbox-wrapper, .el-checkbox, .form-item')?.textContent || '').trim()"
                )
                if not re.search(r"隐私|同意.*协议|个人信息保护|privacy", label, re.I):
                    continue
                if not item.is_checked():
                    item.check(timeout=3000)
                if item.is_checked():
                    filled.append("隐私/个人信息处理同意")
            except Exception:
                continue

        body = _visible_text(page)
        if resume.name in body and not uploaded:
            filled.append(f"已选简历={resume.name}")
            uploaded = True

        if not uploaded:
            final_review = _has_exact_in(
                page,
                [".ant-modal:visible", "[role=dialog]:visible", ".modal:visible", "form:visible", "main"],
                ["确认提交", "提交申请", "投递简历"],
            )
            if final_review:
                # 德勤当前 Hotjob 实习入口真机结构：账号已有在线简历时，岗位页
                # 直接显示隐私确认和最终“确认提交”，没有岗位级 file input。
                # 这条路径可以作为人工审核就绪，但绝不能声称定向 PDF 已上传。
                filled.append(f"站点复用在线简历（未上传岗位定向PDF，已到{final_review}前）")
                return list(dict.fromkeys(filled))
            raise Blocked(
                "Hotjob 当前登录态页面未找到已验证的简历附件上传控件",
                "本次已停在简历/申请预览，未点击投递。请在可见浏览器确认页面结构；probe 已加入资料缺口学习队列",
                probe=dump_form_snapshot(page), portal=self.name,
            )
        return list(dict.fromkeys(filled))

    def verify(self, page: Any, job: JobInfo) -> list[str]:
        result = page.evaluate(
            """() => {
              const visible = el => {
                const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
              };
              const empty = [...document.querySelectorAll('input[required], textarea[required], select[required], [aria-required=true]')]
                .filter(el => visible(el) && el.type !== 'file' && !(el.value || '').trim())
                .map(el => {
                  const box = el.closest('label, .form-item, .ant-form-item, .el-form-item') || el.parentElement;
                  return (box?.textContent || el.placeholder || el.name || el.id || el.tagName).trim().slice(0, 100);
                });
              const errors = [...document.querySelectorAll('.error, .error-message, .ant-form-item-explain-error, .el-form-item__error, [role=alert]')]
                .filter(visible).map(el => (el.textContent || '').trim()).filter(t => t && t.length <= 160);
              const uncheckedPolicy = [...document.querySelectorAll('input[type=checkbox]')].filter(el => {
                if (!visible(el) || el.checked) return false;
                const text = (el.closest('label, .ant-checkbox-wrapper, .el-checkbox, .form-item')?.textContent || '');
                return /隐私|同意.*协议|个人信息保护|privacy/i.test(text);
              }).length;
              return {empty: [...new Set(empty)], errors: [...new Set(errors)], uncheckedPolicy};
            }"""
        )
        issues = [f"可见必填项为空：{label}" for label in result.get("empty", []) if label]
        issues.extend(f"页面校验：{message}" for message in result.get("errors", []))
        if result.get("uncheckedPolicy"):
            issues.append("隐私/个人信息处理协议未勾选")
        issues.extend(resume_readiness_issues(_visible_text(page)))
        return list(dict.fromkeys(issues))

    def submit(self, page: Any, job: JobInfo) -> None:
        clicked = _click_exact_in(
            page,
            [".ant-modal:visible", "[role=dialog]:visible", ".modal:visible", "form:visible", "main"],
            ["确认投递", "提交申请", "确认提交", "投递简历"],
        )
        if not clicked:
            raise Blocked(
                "Hotjob 人工确认后仍未找到已验证的最终提交按钮",
                "请人工核验当前页面；系统不会用详情页入口或模糊文本兜底提交",
                probe=dump_form_snapshot(page), portal=self.name,
            )

    def wait_receipt(self, page: Any, job: JobInfo, timeout_s: int = 90) -> str | None:
        if wait_for_text(page, r"投递成功|申请成功|已投递|提交成功|我的投递", timeout_s=timeout_s):
            return "Hotjob 页面显示投递成功/已投递"
        return None
