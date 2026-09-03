"""腾讯招聘投递适配器（careers.tencent.com）。

已知情况（2026-08 探测 + 线上审计）：
- 岗位列表/详情公开（tencent-search CLI）；jobdesc.html 页面是 ~2KB 的 JS 空壳
  （标题/DOM 由客户端渲染，无 <h1>），因此 open_job 直接调 ByPostId 公开 API
  获取真实岗位名/地点/BG（失败时再用页面 title 兜底）。
- 投递入口「投递/立即投递」按钮由页面 JS 渲染——点击与申请表单需真实浏览器会话。
- 投递需要腾讯通行证（微信/QQ扫码或手机号+验证码）——由人工完成，不绕过。
- 首次遇到申请表未知结构：执行 probe（写入 state/probe_tencent.json）后停下，
  等待人工探路补全字段映射。
"""
from __future__ import annotations

import json
import re
import urllib.request
import winreg  # noqa: F401  (Windows; 其他平台在 _load_json 中降级)
from pathlib import Path
from typing import Any

from .base import (
    PortalAdapter,
    JobInfo,
    Blocked,
    click_by_text,
    fill_by_placeholder,
    wait_for_text,
    dump_form_snapshot,
    _save_probe,
)
from .. import config


def _proxy_url() -> str | None:
    """环境变量优先，其次 Windows 注册表 ProxyServer。"""
    for env in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        v = __import__("os").environ.get(env)
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


def _api_get(url: str) -> dict[str, Any] | None:
    """GET ByPostId API（与 tencent-search CLI 同通道），失败返回 None。"""
    proxy = _proxy_url()
    handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy}) if proxy else urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(handler)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; apply-bot/1.0; personal-use)",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://careers.tencent.com/",
        },
    )
    try:
        with opener.open(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _click_visible_text(page: Any, text: str, *, contains: bool = False) -> bool:
    """点击当前展开层中可见的短选项文本，避免命中页面正文。"""
    # 优先限制在常见 option/list-item 节点，防止点击到表单中已选值的展示文本。
    selectors = [
        "[role='option']",
        ".el-select-dropdown__item",
        "li",
        "[class*='option']",
        "[class*='item']",
    ]
    for selector in selectors:
        loc = page.locator(selector).filter(has_text=text)
        for i in range(min(loc.count(), 400) - 1, -1, -1):
            el = loc.nth(i)
            try:
                actual = (el.inner_text(timeout=1000) or "").strip()
                matched = text in actual if contains else actual == text
                if not matched or not el.is_visible() or len(actual) > len(text) + 8:
                    continue
                el.click(timeout=3000)
                return True
            except Exception:
                continue
    return False


def _select_dropdown(page: Any, selector: str, options: list[str]) -> str | None:
    """打开腾讯自定义下拉并选择第一个真实存在的候选文案。"""
    loc = page.locator(selector).first
    if loc.count() == 0:
        return None
    try:
        loc.scroll_into_view_if_needed()
        click_target = loc.locator("xpath=..") if "el-input__inner" in (loc.get_attribute("class") or "") else loc
        click_target.click(timeout=3000)
        page.wait_for_timeout(1200)
    except Exception:
        return None
    for option in options:
        if _click_visible_text(page, option) or _click_visible_text(page, option, contains=True):
            page.wait_for_timeout(700)
            try:
                selected = (loc.input_value() or "").strip()
                parent_text = (loc.locator("xpath=..").inner_text(timeout=1000) or "").strip()
                if option in selected or option in parent_text:
                    return option
            except Exception:
                pass
    # 可搜索下拉的保守兜底；不使用 force，也不绕过页面校验。
    try:
        if not loc.get_attribute("readonly"):
            loc.fill(options[0])
            page.wait_for_timeout(1000)
            if _click_visible_text(page, options[0]) or _click_visible_text(page, options[0], contains=True):
                page.wait_for_timeout(500)
            else:
                loc.press("ArrowDown")
                loc.press("Enter")
            selected = (loc.input_value() or "").strip()
            parent_text = (loc.locator("xpath=..").inner_text(timeout=1000) or "").strip()
            if options[0] in selected or options[0] in parent_text:
                return options[0]
    except Exception:
        pass
    page.keyboard.press("Escape")
    return None


class TencentAdapter(PortalAdapter):
    name = "tencent"
    url_patterns = ["careers.tencent.com", "talent.tencent.com", "join.qq.com"]
    home_url = "https://careers.tencent.com/"
    login_url = "https://careers.tencent.com/"

    def is_logged_in(self, page: Any) -> bool:
        try:
            url = page.url
        except Exception:
            return False
        if re.search(r"login|passport|qr", url, re.I):
            return False
        try:
            body = page.locator("body").inner_text(timeout=3000)
        except Exception:
            return False
        if "微信扫码" in body or "QQ登录" in body:
            return False
        return "投递" in body or "简历" in body

    def login_hint(self) -> str:
        return "在浏览器窗口完成腾讯通行证登录（微信/QQ 扫码或手机号+验证码）"

    def probe(self, page: Any, url: str) -> dict[str, Any]:
        """腾讯 SPA 表单探路，并只读采集自定义下拉框实际出现的选项文案。"""
        page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(2500)
        snap = dump_form_snapshot(page)
        dropdown_options: dict[str, list[str]] = {}
        for name, selector in [
            # 城市依赖已选国家，优先探测，避免前一个国家下拉层残留干扰。
            ("expected_city", "input.el-select__input"),
            ("current_country", "input[placeholder='选择国家/地区']"),
            ("expected_country", "input[placeholder='请选择国家/地区']"),
        ]:
            loc = page.locator(selector).first
            if loc.count() == 0:
                continue
            try:
                before = set(page.evaluate("""() => [...document.querySelectorAll('body *')]
                  .filter(el => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    const visible = r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
                    const hasVisibleChild = [...el.children].some(c => {
                      const cr = c.getBoundingClientRect();
                      const cs = getComputedStyle(c);
                      return cr.width > 0 && cr.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
                    });
                    const t = (el.textContent || '').trim();
                    return visible && !hasVisibleChild && t && t.length <= 50;
                  }).map(el => el.textContent.trim())"""))
                loc.scroll_into_view_if_needed()
                click_target = loc.locator("xpath=..") if "el-input__inner" in (loc.get_attribute("class") or "") else loc
                click_target.click()
                page.wait_for_timeout(700)
                after = page.evaluate("""() => [...document.querySelectorAll('body *')]
                  .filter(el => {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    const visible = r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
                    const hasVisibleChild = [...el.children].some(c => {
                      const cr = c.getBoundingClientRect();
                      const cs = getComputedStyle(c);
                      return cr.width > 0 && cr.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
                    });
                    const t = (el.textContent || '').trim();
                    return visible && !hasVisibleChild && t && t.length <= 50;
                  }).map(el => el.textContent.trim())""")
                dropdown_options[name] = list(dict.fromkeys(t for t in after if t not in before))[:100]
                page.keyboard.press("Escape")
            except Exception as e:
                detail = " ".join(str(e).split())[:500]
                dropdown_options[name] = [f"<probe failed: {type(e).__name__}: {detail}>"]
        snap["dropdown_options"] = dropdown_options
        _save_probe(self.name, url, snap)
        return snap

    def open_job(self, page: Any, url: str) -> JobInfo:
        page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(2500)
        m = re.search(r"postId=(\d+)", page.url)
        post_id = m.group(1) if m else None
        # jobdesc.html 是 JS 空壳：标题/公司优先走公开 ByPostId API（可靠、无歧义）
        title, company, location = "", "腾讯", None
        if post_id:
            body = _api_get(f"https://careers.tencent.com/tencentcareer/api/post/ByPostId?postId={post_id}")
            data = (body or {}).get("Data")
            if data and data.get("RecruitPostName"):
                title = data["RecruitPostName"]
                company = data.get("ComName") or "腾讯"
                location = " · ".join(x for x in [data.get("CountryName"), data.get("LocationName")] if x) or None
        if not title:
            try:
                title = page.locator("h1").first.inner_text(timeout=3000).strip()
            except Exception:
                pass
        if not title:
            title = (page.title() or "").split("|")[0].strip() or "(未知岗位)"
        return JobInfo(title=title, company=company, url=page.url, id=post_id, raw={"location": location})

    def open_apply_form(self, page: Any, job: JobInfo) -> None:
        # 操作指引确认（2026-08-23 检索）：详情页右侧按钮为「申请」；
        # 需先登录（微信/QQ 均可），然后进入信息填写与简历上传页。
        if not (click_by_text(page, "申请", contains=True) or click_by_text(page, "立即投递", contains=True) or click_by_text(page, "投递", contains=True)):
            raise Blocked("详情页未找到「申请/投递」按钮", "岗位可能已关闭或需内推；请人工检查", portal=self.name)
        page.wait_for_load_state("domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(2000)

    def fill_form(self, page: Any, job: JobInfo, profile: dict[str, Any], resume: Path | None) -> list[str]:
        # 主路径（依操作指引）：上传简历 → 补填已知信息 → 勾选授权 → 校验。
        # 结构不符 → probe 落盘并停下，等待人工探路补全字段映射。
        filled: list[str] = []
        upload = page.locator("input[type=file]")
        if upload.count() > 0:
            if resume is None:
                resume = config.find_resume(job.company)
            if resume is None:
                raise Blocked("未找到可上传的简历文件（请用 --cv 指定）", portal=self.name)
            upload.first.set_input_files(str(resume))
            filled.append(f"简历附件={resume.name}")
            page.wait_for_timeout(6000)
            if not wait_for_text(page, r"上传成功|已上传|删除|更换|解析", timeout_s=config.UPLOAD_WAIT_S):
                raise Blocked("上传后未检测到成功信号", "人工确认页面是否出现文件名/已上传（超时≠失败）",
                              probe=dump_form_snapshot(page), portal=self.name)
            print(f"[tencent] 简历已上传: {resume.name}")
            # 腾讯会自动解析附件并回填姓名、经历和学历。只记录命中布尔/计数，
            # 不把任何字段值写入日志。
            parsed = page.evaluate(
                """({candidate, schools}) => {
                  const controls = [...document.querySelectorAll('input, textarea')]
                    .filter(el => el.type !== 'file' && (el.value || '').trim());
                  const body = document.body.innerText;
                  return {
                    count: controls.length,
                    hasName: !!candidate && body.includes(candidate),
                    hasSchool: schools.some(s => s && body.includes(s))
                  };
                }""",
                {
                    "candidate": profile.get("identity", {}).get("name") or "",
                    "schools": [e.get("school", "") for e in profile.get("education", [])],
                },
            )
            if parsed.get("hasName") or parsed.get("hasSchool") or parsed.get("count", 0) >= 5:
                marks = [f"{parsed.get('count', 0)}字段"]
                if parsed.get("hasName"):
                    marks.append("姓名✓")
                if parsed.get("hasSchool"):
                    marks.append("学历✓")
                filled.append("解析回填(" + ",".join(marks) + ")")
        # 已知字段补填（申请表内常见；值缺失/结构不同则跳过，交给探路）
        for label, key in [("姓名", "name"), ("手机", "phone"), ("邮箱|Email", "email")]:
            val = profile.get("identity", {}).get(key)
            if val and fill_by_placeholder(page, label, val):
                filled.append(label)
        # 联系信息：国家为必填，省/市为普通文本。location 是“城市，省份”自由文本，
        # 按事实源填写，不臆造更细行政区。
        if _select_dropdown(page, "input[placeholder='选择国家/地区']", ["中国内地"]):
            filled.append("当前国家/地区=中国内地")
        identity_location = profile.get("identity", {}).get("location") or ""
        current_city = identity_location.split("/")[0].strip().replace("，", "")
        if current_city and fill_by_placeholder(page, r"^省/市$", current_city):
            filled.append(f"当前省/市={current_city}")

        # 工作意向优先跟随当前岗位地点，退回档案首选城市。
        job_location = (job.raw or {}).get("location") or ""
        city = job_location.split("·")[-1].strip() if job_location else ""
        if not city:
            city = ((profile.get("availability", {}).get("cities") or [""])[0]).strip()
        if _select_dropdown(page, "input[placeholder='请选择国家/地区']", ["中国内地"]):
            filled.append("期望国家/地区=中国内地")
        if city and _select_dropdown(page, "input.el-select__input", [city, f"{city}市"]):
            filled.append(f"期望工作城市={city}")

        # 页面含大量城市复选框，只能精确勾选最终隐私政策控件，不能使用首个
        # checkbox 兜底，以免误改工作地点。
        policy = page.locator("input[name='policy']").first
        if policy.count() > 0:
            try:
                if not policy.is_checked():
                    policy.check(timeout=3000)
                if policy.is_checked():
                    filled.append("腾讯招聘隐私政策勾选")
            except Exception:
                pass
        # 保守校验：若页面明显是表单却一个字段都没命中，转探路
        if not filled and page.locator("input[type=file]").count() == 0:
            raise Blocked(
                "腾讯申请表结构未知，已暂停并写入探路快照；请人工在浏览器查看表单后补充 portals/tencent.py 的字段映射",
                "运行 probe 模式（apply_one.py --probe <url>）可自动生成 state/probe_tencent.json，把关键字段中文名/占位发给维护者即可完成适配",
                probe=dump_form_snapshot(page),
                portal=self.name,
            )
        return filled

    def verify(self, page: Any, job: JobInfo) -> list[str]:
        """校验可见必填空项、隐私勾选及站点已显示的红色错误。"""
        result = page.evaluate(
            r"""() => {
              const visible = el => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
              };
              const required = [...document.querySelectorAll(
                "input.required, textarea.required, input[class*='-required'], textarea[class*='required'], input[placeholder='请选择城市']"
              )].filter(el => visible(el) && el.type !== 'file' && !(el.value || '').trim())
                .map(el => el.id || el.placeholder || el.className || el.tagName.toLowerCase());
              const errors = [...document.querySelectorAll(
                ".error, .error-msg, .error-message, .el-form-item__error, [class*='error-tip'], [class*='invalid-tip']"
              )].filter(visible).map(el => (el.textContent || '').trim())
                .filter(t => t && t.length <= 160);
              const redCandidates = [...document.querySelectorAll('body *')].filter(el => {
                if (!visible(el)) return false;
                const t = (el.innerText || el.textContent || '').trim();
                const m = getComputedStyle(el).color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
                if (!m || t.length < 4 || t.length > 160 || t === '删除') return false;
                const [r, g, b] = m.slice(1).map(Number);
                return r > 160 && r > g * 1.25 && r > b * 1.25;
              }).map(el => (el.innerText || el.textContent || '').trim());
              // 复合提示的父子节点可能继承同一红色；只保留最短、最具体的文本。
              const redWarnings = redCandidates.filter(t =>
                !redCandidates.some(other => other !== t && t.includes(other) && other.length >= 4));
              const policy = document.querySelector("input[name='policy']");
              return {required: [...new Set(required)], errors: [...new Set([...errors, ...redWarnings])],
                      policyChecked: !!policy && policy.checked};
            }"""
        )
        issues = [f"可见必填项为空：{name}" for name in result.get("required", [])]
        issues.extend(f"页面校验：{msg}" for msg in result.get("errors", []))
        if not result.get("policyChecked"):
            issues.append("腾讯招聘隐私政策未勾选")
        return list(dict.fromkeys(issues))

    def submit(self, page: Any, job: JobInfo) -> None:
        for label in ["提交简历", "立即投递", "确认投递", "提交"]:
            if click_by_text(page, label, contains=True):
                return
        raise Blocked("未找到腾讯申请表提交按钮", "请人工检查", portal=self.name)

    def wait_receipt(self, page: Any, job: JobInfo, timeout_s: int = 90) -> str | None:
        if wait_for_text(page, r"投递成功|已投递|提交成功|完成", timeout_s=timeout_s):
            return "投递成功"
        return None
