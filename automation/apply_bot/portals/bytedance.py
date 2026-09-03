"""字节跳动校园招聘适配器。

依据 2026-08-21 实测（AUTOMATED_APPLICATION_WORKFLOW.md §7）：
  职位详情 /campus/position/<job-id>/detail
    → 点击「投递」→ 申请表 /campus/resume/<job-id>/apply
    → 上传简历（成功后页面显示 文件名+上传时间+更新/删除）
    → 「解析并覆盖」→ 补填城市等 → 勾选隐私政策 → 「提交简历」（最终确认点）

上传后浏览器控制可能先返回超时——不能凭超时判失败：重新读取页面，确认
「文件名 + 上次上传时间 + 更新/删除」作为成功信号（服务器接收后会清空
input.files，属正常表现）。
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .base import (
    PortalAdapter,
    JobInfo,
    Blocked,
    click_by_text,
    fill_by_placeholder,
    upload_file,
    check_if_present,
    checkbox_checked,
    wait_for_text,
    dump_form_snapshot,
)
from .. import config


class BytedanceAdapter(PortalAdapter):
    name = "bytedance"
    url_patterns = ["jobs.bytedance.com"]
    home_url = "https://jobs.bytedance.com/campus/job"
    login_url = "https://jobs.bytedance.com/"
    resume_prefers_docx = True  # 2026-08-21 实测：Word 上传解析回填最完整

    def is_logged_in(self, page: Any) -> bool:
        try:
            url = page.url
        except Exception:
            return False
        if "login" in url.lower():
            return False
        # 表单页可见（简历上传/申请字段）即视为已登录
        if "/apply" in url or "/resume" in url:
            return True
        body = page.locator("body").inner_text(timeout=3000).lower()
        return "登录" not in body or "立即投递" in body

    def login_hint(self) -> str:
        return "在浏览器完成字节登录（手机号+验证码 / 扫码均可）"

    def open_job(self, page: Any, url: str) -> JobInfo:
        # 线上审计（2026-08-23）：服务器对 /campus/position* 直连不稳定 404
        # （WAF 按 IP/时序放行；外壳真实路由为 /campus/job），浏览器带完整
        # 会话与来源链时正常。此处容错：直连失败则提示从 /campus/job 进入。
        resp = page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(2500)
        shell_loaded = False
        try:
            shell_loaded = bool(page.locator("#mainBox, #app, body").count()) and "字节" in page.title()
        except Exception:
            pass
        if (resp is not None and resp.status >= 400) or not shell_loaded:
            raise Blocked(
                "字节岗位详情页直连失败（服务器对 /campus/position* 直连会 404/被风控）",
                "请在浏览器中先打开 https://jobs.bytedance.com/campus/job 从列表进入该岗位详情，"
                "然后重开本命令（或直接复制进入后的详细 URL）",
                portal=self.name,
            )
        title = ""
        company = "字节跳动"
        m = re.search(r"/campus/(?:position|resume)/(\d+)", page.url)
        job_id = m.group(1) if m else None
        # 标题提取：申请表页的职位标题在 .resumeEditForm-headerText（线上嗅探
        # 2026-08-23）；h1 是隐藏 SEO 文本（"校园招聘"/logo），必须过滤。
        for sel in [".resumeEditForm-headerText", "h1", "h2", "h3", ".job-detail-name", "[class*=jobName]"]:
            try:
                t = page.locator(sel).first.inner_text(timeout=2500).strip()
            except Exception:
                continue
            if t and len(t) > 2 and not t.startswith(".") and "校园招聘" not in t and "字节跳动" not in t and t not in ("投递简历",):
                title = t
                break
        if not title:
            title = (page.title() or "").split("-")[0].strip()
        if not title or title == "字节跳动":
            raise Blocked("未能从详情页解析岗位名称", "请人工确认页面是否正确打开", portal=self.name)
        if "猎头" in title or "talents" in title.lower():
            # WAF 放行后可能回退到「字节跳动猎头平台」外壳：主题不对，立即中止防止误投
            raise Blocked("页面为猎头平台外壳而非校园岗位详情", "请人工确认链接是否为 /campus/position/ 详情页", portal=self.name)
        return JobInfo(title=title, company=company, url=page.url, id=job_id)

    def open_apply_form(self, page: Any, job: JobInfo) -> None:
        # 已直接在申请表（/campus/resume/<id>/apply 或 path 以 /apply 结尾）：
        # 无需再找「投递」按钮
        if "/campus/resume/" in page.url or page.url.rstrip("/").endswith("/apply"):
            return
        if not click_by_text(page, "投递", contains=True):
            raise Blocked("详情页找不到「投递」按钮", "可能是内推/已投递或页面结构变化；请人工检查", portal=self.name)
        page.wait_for_load_state("domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        page.wait_for_timeout(2000)
        if "login" in page.url.lower():
            return  # 由 wait_for_login 处理

    def fill_form(self, page: Any, job: JobInfo, profile: dict[str, Any], resume: Path | None) -> list[str]:
        filled: list[str] = []
        # 1. 上传简历（字节：Word 优先——2026-08-21 实测 Word 上传解析回填最完整）
        if resume is None:
            resume = config.find_resume(job.company, prefer_docx=True)
        if resume is not None and not upload_file(page, resume):
            raise Blocked("申请表未找到文件上传控件", "请人工检查上传区域", portal=self.name)
        if resume is not None:
            print(f"[bytedance] 已上传简历: {resume.name}，等待解析…")
            # 成功信号：文件名+更新/删除 或 解析回填提示；服务器会清空 input.files（正常）
            ok = (
                wait_for_text(page, r"解析|更新|删除|已上传", timeout_s=config.UPLOAD_WAIT_S)
                or wait_for_text(page, re.escape(resume.stem), timeout_s=config.UPLOAD_WAIT_S)
            )
            if not ok:
                raise Blocked("上传后未检测到成功信号", "人工确认页面是否出现 文件名+上传时间+更新/删除（超时≠失败）", probe=dump_form_snapshot(page), portal=self.name)
            filled.append("简历附件")
            page.wait_for_timeout(8000)  # 给自动解析/回填时间（2026-08-23 实测无独立「解析」按钮）
            # 值级回填确认：只返回布尔/计数，不输出敏感值
            candidate_name = (profile.get("identity") or {}).get("name") or ""
            schools = [e.get("school") for e in (profile.get("education") or []) if e.get("school")]
            probe = page.evaluate(
                """(args) => {
                  const vals = [...document.querySelectorAll('input, textarea')]
                    .map(i => (i.value || '').trim()).filter(v => v && v !== 'on' && v !== 'checked');
                  const body = document.body.innerText;
                  return {count: vals.length,
                          hasCandidateName: args.name !== '' && body.includes(args.name),
                          hasSchool: args.schools.some(s => body.includes(s))};
                }""",
                {"name": candidate_name, "schools": schools},
            )
            if probe.get("hasCandidateName") or probe.get("count", 0) >= 2:
                filled.append("解析回填(" + ("姓名✓" if probe.get("hasCandidateName") else f"{probe.get('count')}字段") + ")")
            else:
                print("[bytedance] 回填字段暂未显示值（可能解析较慢；已保持页面供人工确认）")
        # 2. 解析回填（可选：按钮文案 解析并覆盖/使用解析结果/解析；无按钮则跳过）
        page.wait_for_timeout(3000)
        parsed = False
        for text in ["解析并覆盖", "使用解析结果", "解析"]:
            if click_by_text(page, text, contains=True):
                parsed = True
                page.wait_for_timeout(6000)
                filled.append("解析回填")
                break
        if not parsed:
            print("[bytedance] 未发现「解析」按钮（可能已自动解析或需人工点击）")
        # 2.5 回填校验：姓名/手机/邮箱/教育 是否出现在页面
        try:
            body_txt = page.locator("body").inner_text(timeout=3000)
            backfill_hits = [k for k in ["基本信息", "教育经历", "姓名", "手机"] if k in body_txt]
            if backfill_hits:
                filled.append("回填确认(" + ",".join(backfill_hits) + ")")
            else:
                print("[bytedance] 未检测到回填区块（表单可能不再展示个人信息区）")
        except Exception:
            pass
        # 3. 补填城市
        city = (profile.get("availability", {}).get("cities") or [""])[0]
        if city and fill_by_placeholder(page, r"城市|工作地|期望城市", city):
            filled.append(f"城市={city}")
        # 4. 隐私政策（label 级兜底 + 勾选状态校验）
        checked = check_if_present(
            page,
            [
                "input[type=checkbox]",
                "[class*=agree] input",
                "[class*=check] input",
                "label:has-text('隐私政策')",
                "[class*=protocol] label",
                "[class*=agreement] label",
            ],
        )
        if checked:
            state_now = checkbox_checked(page)
            if state_now is False:
                print("[bytedance] 隐私勾选未生效（自定义控件），请在最终确认时人工勾选")
                self._privacy_issue = "隐私勾选需人工确认"
            filled.append("隐私政策勾选")
        return filled

    def verify(self, page: Any, job: JobInfo) -> list[str]:
        issues: list[str] = []
        try:
            body = page.locator("body").inner_text(timeout=3000)
        except Exception:
            return ["无法读取页面文本"]
        for marker in ["请选择", "必填", "请输入"]:
            if marker in body:
                issues.append(f"可能存在未填必填项（检测到「{marker}」提示）")
                break
        if getattr(self, "_privacy_issue", None):
            issues.append(self._privacy_issue)
        return issues

    def submit(self, page: Any, job: JobInfo) -> None:
        if not click_by_text(page, "提交简历", contains=True) and not click_by_text(page, "提交", contains=True):
            raise Blocked("找不到「提交简历」按钮", "请人工检查最终提交按钮位置", portal=self.name)

    def wait_receipt(self, page: Any, job: JobInfo, timeout_s: int = 90) -> str | None:
        if wait_for_text(page, r"投递成功|已投递|提交成功|感谢", timeout_s=timeout_s):
            return "投递成功"
        return None


# ---------------------------------------------------------------------------
# 岗位发现（浏览器渲染；jobs.bytedance.com 的岗位 JSON API 已失效/
# 需要签名，经确认 GET /api/... 只回 SPA 外壳 —— 2026-08 探测）
# 2026-08 进一步实证：同一 URL（/campus/job）连续 8 次请求全部 404（WAF 按
# 请求/IP 概率拦截，偶发放行一次即回 200+外壳）。结论：该站 HTTP 通道（API 或
# 页面）对非常规来源完全不可靠，岗位发现与投递必须走真实浏览器会话。
# ---------------------------------------------------------------------------

def discover_jobs(page: Any, keyword: str = "", limit: int = 20, location: str = "", list_url: str | None = None) -> list[dict[str, Any]]:
    """在校园招聘职位列表页按关键词渲染抓取岗位卡片。

    返回 [{title, company, url, id}]；卡片结构未知时返回空列表并打印页面提示
    （首次运行请人工确认列表选择器后补全定位逻辑）。
    list_url 可直接指定列表页（带筛选参数的完整 URL）。
    注意：外壳真实路由是 https://jobs.bytedance.com/campus/job（列表/详情均为
    客户端路由；服务器对 /campus/position* 直连 404 且有 WAF 波动——HTTP 层
    抓取不可靠，本函数必须在真实浏览器会话内运行）。
    """
    if list_url:
        url = list_url
    else:
        base = "https://jobs.bytedance.com/campus/job"
        params: list[str] = []
        if keyword:
            params.append(f"keywords={quote(keyword)}")
        if location:
            params.append(f"city={quote(location)}")
        url = f"{base}?{'&'.join(params)}" if params else base
    page.goto(url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
    # SPA 渲染：等列表出现（最多 ~15s）
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            links = page.locator("a[href*='/campus/position/']")
            if links.count() > 0:
                break
        except Exception:
            pass
        page.wait_for_timeout(1000)

    jobs: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    loc = page.locator("a[href*='/campus/position/']")
    n = loc.count()
    for i in range(min(n, limit * 3)):
        try:
            href = loc.nth(i).get_attribute("href") or ""
        except Exception:
            continue
        if not href or "/position/" not in href:
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        full = href if href.startswith("http") else f"https://jobs.bytedance.com{href}"
        m = re.search(r"/position/(\d+)", full)
        job_id = m.group(1) if m else None
        try:
            text = (loc.nth(i).inner_text(timeout=2000) or "").strip()
        except Exception:
            text = ""
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = lines[0] if lines else ""
        company = next((l for l in lines[1:] if re.search(r"字节|飞书|抖音|火山|剪映|CapCut", l)), "字节跳动")
        if not title:
            continue
        jobs.append({"title": title, "company": company, "url": full, "id": job_id})
        if len(jobs) >= limit:
            break
    if not jobs:
        print("[bytedance.discover] 未解析到岗位卡片——请人工确认列表页选择器（a[href*='/campus/position/']）后重启")
    return jobs
