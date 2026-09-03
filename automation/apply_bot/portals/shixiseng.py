"""实习僧投递适配器。

已知约束（2026-08 探测）：
- 列表/详情公开可读（shixiseng-search CLI），投递需要登录（微信/手机号+验证码）。
- 「立即投递」通常在详情页右栏；首次投递会弹登录浮层（由人工完成，不绕过）。
- 投递弹窗常见形态：选择简历（在线简历 / 附件简历）→ 确认投递。部分职位或
  用户状态（非会员/企业 VIP 限制）会拦截，界面提示「需开通/简历未完善」——
  一律报告为 blocked，不做任何绕过。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import (
    PortalAdapter,
    JobInfo,
    Blocked,
    click_by_text,
    upload_file,
    wait_for_text,
    fetch_html,
    dump_form_snapshot,
)
from .. import config


def parse_detail_html(html: str, uuid: str | None = None) -> tuple[str, str]:
    """从实习僧详情页 HTML 提取 (title, company)。

    SSR 页面无 <h1>（线上审计 2026-08-23）；标题/公司以内嵌的
    状态赋值（`.iname="..."` / `.cname="..."`）为准，浏览器无关、可离线单测。
    """
    title = ""
    t = re.search(r'\.iname\s*=\s*"((?:[^"\\]|\\.)*)"', html)
    if t:
        title = t.group(1)
    company = ""
    c = re.search(r'\.cname\s*=\s*"((?:[^"\\]|\\.)*)"', html)
    if c:
        company = c.group(1)
    return title, company


def _select_el_option(page: Any, index: int, target: str) -> str | None:
    """按弹窗内可见顺序设置 Element UI 单选下拉，并返回实际选中值。"""
    inputs = page.locator("input[placeholder='请选择']:visible")
    if index >= inputs.count():
        return None
    input_el = inputs.nth(index)
    select = input_el.locator("xpath=ancestor::div[contains(@class,'el-select')][1]")

    def selected_value() -> str:
        selected = select.locator("li.el-select-dropdown__item.selected")
        if selected.count() == 0:
            return ""
        try:
            return (selected.first.inner_text(timeout=1000) or "").strip()
        except Exception:
            return ""

    current = selected_value()
    if current == target:
        return current
    try:
        input_el.locator("xpath=..").click(timeout=3000)
        page.wait_for_timeout(400)
        options = page.locator(".el-select-dropdown:visible li.el-select-dropdown__item")
        for i in range(options.count()):
            option = options.nth(i)
            if (option.inner_text(timeout=1000) or "").strip() == target:
                option.click(timeout=3000)
                page.wait_for_timeout(300)
                break
    except Exception:
        return None
    return selected_value() or target


class ShixisengAdapter(PortalAdapter):
    name = "shixiseng"
    url_patterns = ["shixiseng.com"]
    home_url = "https://www.shixiseng.com/"
    login_url = "https://www.shixiseng.com/"

    def is_logged_in(self, page: Any) -> bool:
        # 未登录特征：页面浮层出现「登录」/「扫码登录」；已登录通常出现用户名/退出。
        try:
            body = page.locator("body").inner_text(timeout=3000)
        except Exception:
            return False
        if len(body.strip()) < 50:  # 空白/未加载页面一律视为未登录，绝不误判已登录
            return False
        if "扫码登录" in body or "手机登录" in body:
            return False
        # 打开任意个人中心页面无法直达；以无登录浮层 + 存在用户名元素为粗略判断
        return "登录" not in body or "退出" in body

    def login_hint(self) -> str:
        return "在浏览器窗口完成实习僧登录（微信扫码或手机号+验证码）"

    def open_job(self, page: Any, url: str) -> JobInfo:
        page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(2500)
        m = re.search(r"/intern/(inn_[a-z0-9]+)", page.url)
        uuid = m.group(1) if m else None
        title, company = "", ""
        # 主路径：直接抓 SSR HTML 解析状态赋值（浏览器无关、确定性；已线上验证
        # .iname="..." / .cname="..." 存在于原始 HTML）
        try:
            title, company = parse_detail_html(fetch_html(url), uuid)
        except Exception:
            pass
        # 兜底：浏览器内已执行的 window.__NUXT__（同源数据）
        if not title:
            try:
                state = page.evaluate("JSON.stringify(window.__NUXT__)")
                t = re.search(r'"iname":"((?:[^"\\]|\\.)*)"', state or "")
                if not t:
                    t = re.search(r'"name":"((?:[^"\\]|\\.)*)"', state or "")
                if t:
                    title = t.group(1)
            except Exception:
                pass
        if not title:
            try:
                title = page.locator("h1, h2").first.inner_text(timeout=2000).strip()
            except Exception:
                pass
        if not title:
            title = (page.title() or "").split("_")[0].strip()
        # 公司名的次要来源：浏览器内元素（[class*=company] 匹配线上 .f-r.go-company）
        if not company:
            try:
                company = page.locator(".company-name, .company_name, [class*=company]").first.inner_text(timeout=3000).strip()
            except Exception:
                pass
        if not uuid and "inn_" not in page.url:
            raise Blocked("无法确认实习僧岗位详情页", "请使用 https://www.shixiseng.com/intern/inn_xxx 形式的链接", portal=self.name)
        return JobInfo(title=title or "(未知岗位)", company=company or "(未知公司)", url=page.url, id=uuid)

    def open_apply_form(self, page: Any, job: JobInfo) -> None:
        # 2026-08-24 真机：新版详情页入口为 div.resume_apply.com_res，文案
        # 「投个简历」（页面顶部/底部各一处），不再是旧版「立即投递」。
        clicked = False
        for selector in ["div.resume_apply.com_res", ".resume_apply"]:
            loc = page.locator(selector)
            for i in range(loc.count()):
                el = loc.nth(i)
                try:
                    if el.is_visible() and "投个简历" in (el.inner_text() or ""):
                        el.click(timeout=3000)
                        clicked = True
                        break
                except Exception:
                    continue
            if clicked:
                break
        if not clicked and not (
            click_by_text(page, "投个简历", contains=True)
            or click_by_text(page, "立即投递", contains=True)
        ):
            raise Blocked("未找到「投个简历/立即投递」按钮", "岗位可能已关闭或需要企业内推入口；请人工检查", portal=self.name)
        page.wait_for_timeout(1500)
        # 投递前置登录浮层（扫码/手机验证码由人工完成；完成后重跑本命令即可）
        try:
            body = page.locator("body").inner_text(timeout=3000)
        except Exception:
            body = ""
        if "扫码登录" in body or "手机登录" in body:
            raise Blocked(
                "实习僧投递需要登录（扫码/手机验证码）",
                "请在浏览器窗口完成登录后重新执行本命令（登录态会持久化保存）",
                portal=self.name,
            )

    def fill_form(self, page: Any, job: JobInfo, profile: dict[str, Any], resume: Path | None) -> list[str]:
        filled: list[str] = []
        body = page.locator("body").inner_text(timeout=3000)
        if "开通" in body and "VIP" in body:
            raise Blocked("实习僧提示需开通会员/被企业限制投递", "请人工确认账号状态；不进行任何付费或绕过操作", portal=self.name)
        # 2026-08-25 真机：在线简历未达到企业要求时，投递入口先展示
        # 「取消 / 去完善」弹窗，而不是简历选择表单。进入完善页仅用于探测缺失
        # 字段，不会保存或提交任何资料；快照交给通用表单学习层处理。
        if page.get_by_text("去完善", exact=True).count() > 0:
            candidates = page.get_by_text("去完善", exact=True)
            improve = candidates.first
            for i in range(candidates.count()):
                if candidates.nth(i).is_visible():
                    improve = candidates.nth(i)
                    break
            try:
                pages_before = len(page.context.pages)
                improve.click(timeout=3000)
                page.wait_for_timeout(1800)
                # 「去完善」当前会在新标签打开 resume.shixiseng.com。适配器
                # 的后续流程仍持有原 page 对象，因此把新标签 URL 安全地转到
                # 当前页，便于生成真正的完善页字段快照。
                if len(page.context.pages) > pages_before:
                    resume_page = page.context.pages[-1]
                    resume_page.wait_for_load_state("domcontentloaded", timeout=8000)
                    resume_url = resume_page.url
                    if resume_url.startswith("https://resume.shixiseng.com/"):
                        page.goto(resume_url, wait_until="domcontentloaded", timeout=15000)
                    resume_page.close()
                    page.wait_for_timeout(3000)
                config.ensure_dirs()
                page.screenshot(
                    path=str(config.STATE_DIR / "probe_shixiseng_resume.png"),
                    full_page=True,
                )
            except Exception:
                raise Blocked(
                    "账号在线简历未达到该岗位投递要求",
                    "请在实习僧完善在线简历后重跑；不会绕过完整度限制",
                    probe=dump_form_snapshot(page),
                    portal=self.name,
                )
            raise Blocked(
                "账号在线简历未达到该岗位投递要求",
                "已打开简历完善页并记录字段快照；补全缺失资料后可自动续跑",
                probe=dump_form_snapshot(page),
                portal=self.name,
            )
        # 旧版可能直接提供附件上传；新版（2026-08-24 真机）弹窗默认选中账号
        # 在线简历，并用三个下拉收集到岗/时长/出勤。这里不点击「确认投递」。
        if upload_file(page, resume) if resume else False:
            filled.append("附件简历上传")
        else:
            online = page.locator(".user-resume").first
            online_selected = False
            if online.count() > 0:
                try:
                    online_selected = online.locator("img[src*='radio-choosed']").count() > 0
                    if not online_selected:
                        online.click(timeout=3000)
                        page.wait_for_timeout(300)
                        online_selected = online.locator("img[src*='radio-choosed']").count() > 0
                except Exception:
                    online_selected = False
            if online_selected:
                filled.append("在线简历(中文96%)")
            elif click_by_text(page, "使用在线简历", contains=True):
                filled.append("在线简历选择")
            else:
                raise Blocked("投递弹窗结构未知", "请人工查看弹窗并选择简历；若为首次探路请运行 probe 模式", probe=dump_form_snapshot(page), portal=self.name)

        availability = profile.get("availability", {})
        arrival_target = "1周内" if availability.get("start_date") == "立即" else "2周内"
        min_months = int(availability.get("min_months") or 3)
        duration_target = "6个月以上" if min_months > 6 else "3-6个月"
        day_numbers = [int(x) for x in re.findall(r"\d+", str(availability.get("days_per_week") or ""))]
        days_target = f"{max(day_numbers)}天" if day_numbers else "5天"
        for label, index, target in [
            ("到岗时间", 0, arrival_target),
            ("实习时长", 1, duration_target),
            ("每周出勤", 2, days_target),
        ]:
            actual = _select_el_option(page, index, target)
            if actual:
                filled.append(f"{label}={actual}")
            else:
                raise Blocked(
                    f"投递弹窗无法设置{label}",
                    "请按 probe 快照核对 Element UI 下拉结构；不点击确认投递",
                    probe=dump_form_snapshot(page),
                    portal=self.name,
                )
        return filled

    def verify(self, page: Any, job: JobInfo) -> list[str]:
        issues: list[str] = []
        try:
            body = page.locator("body").inner_text(timeout=3000)
        except Exception:
            return ["无法读取页面文本"]
        if "未完善" in body or "请先完善" in body:
            issues.append("账号在线简历未完善，可能无法投递（请在浏览器中人工完善）")
        selects = page.locator("input[placeholder='请选择']:visible")
        if selects.count() < 3:
            issues.append("投递弹窗缺少到岗时间/实习时长/每周出勤下拉")
        if page.locator(".user-resume img[src*='radio-choosed']").count() == 0:
            issues.append("未检测到已选中的在线简历")
        return issues

    def submit(self, page: Any, job: JobInfo) -> None:
        for label in ["确认投递", "投递", "发送"]:
            if click_by_text(page, label, contains=True):
                return
        raise Blocked("未找到投递确认按钮", "请人工检查投递弹窗", portal=self.name)

    def wait_receipt(self, page: Any, job: JobInfo, timeout_s: int = 60) -> str | None:
        if wait_for_text(page, r"投递成功|已投递|投递完成", timeout_s=timeout_s):
            return "投递成功"
        return None
