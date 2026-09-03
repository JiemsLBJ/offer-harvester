"""在一个可见 Chrome 会话中准备多份申请，并保留所有审核标签页。

本模块永远不调用 ``adapter.submit``，只执行岗位校验、登录等待、定向简历上传、
安全字段填写、表单学习和截图。全部岗位处理完后阻塞在终端，直到用户按回车才
关闭浏览器，因而适合 ``run_batch --fill-only --retain-all`` 的人工审核流程。
"""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any

from . import config, form_learning, materials, model, state
from .browser import BrowserError, launch, wait_for_login
from .portals import adapter_for_url
from .portals.base import Blocked, JobInfo, dump_form_snapshot


def _save_probe(error: Blocked, page: Any, job: JobInfo | None, url: str, profile: dict[str, Any]) -> None:
    snapshot = error.probe or dump_form_snapshot(page)
    path = config.STATE_DIR / f"probe_{error.portal}.json"
    payload = {
        "portal": error.portal,
        "reason": error.reason,
        "url": job.url if job else url,
        "snapshot": snapshot,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        form_learning.learn_snapshot(
            snapshot,
            portal=error.portal,
            url=job.url if job else url,
            company=job.company if job else "",
            title=job.title if job else "",
            profile=profile,
            issues=[error.reason],
        )
    except Exception as learn_error:
        print(f"  （表单学习失败: {learn_error}）")
    print(f"  表单快照: {path}")


def _prepare_one(page: Any, entry: dict[str, Any], resume: Path, profile: dict[str, Any], index: int) -> dict[str, Any]:
    url = str(entry.get("url") or "")
    adapter = adapter_for_url(url)
    if adapter is None:
        return {"index": index, "status": "unsupported", "url": url, "page": page}

    job: JobInfo | None = None
    page.set_default_timeout(config.ELEMENT_TIMEOUT_MS)
    try:
        home = adapter.home_url or adapter.login_url
        if home:
            page.goto(home, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
            if not adapter.is_logged_in(page):
                print(f"[{index}] [登录] 当前 {adapter.name} 未登录，等待人工完成…")
                if adapter.login_url:
                    page.goto(adapter.login_url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
                wait_for_login(page.context, page, adapter.is_logged_in, adapter.login_hint())

        job = adapter.open_job(page, url)
        print(f"[{index}] [岗位] {job.company} — {job.title}\n    {job.url}")
        expected_company = str(entry.get("company") or "").strip()
        expected_title = str(entry.get("title") or "").strip()
        if expected_company and job.company and expected_company not in job.company:
            raise Blocked(
                f"公司不匹配：期望 {expected_company}，页面 {job.company}",
                "已停止该标签页，避免把简历传给错误公司",
                portal=adapter.name,
            )
        if expected_title and expected_title not in job.title:
            raise Blocked(
                f"岗位名不匹配：期望 {expected_title}，页面 {job.title}",
                "已停止该标签页，避免投递到错误岗位",
                portal=adapter.name,
            )

        adapter.open_apply_form(page, job)
        if not adapter.is_logged_in(page):
            print(f"[{index}] [登录] 点击申请后 {adapter.name} 要求登录，等待人工完成…")
            wait_for_login(page.context, page, adapter.is_logged_in, adapter.login_hint())

        steps = ["打开申请表"]
        fields = adapter.fill_form(page, job, profile, resume)
        learned_filled = form_learning.fill_learned_fields(page, adapter.name, profile)
        if learned_filled:
            fields.extend(f"历史补充:{label}" for label in learned_filled)
        fields = list(dict.fromkeys(fields))
        resume_record = str(resume)
        if any("站点复用在线简历" in field for field in fields):
            resume_record = "Hotjob账号在线简历（岗位页未上传本次定向PDF）"
        steps.append("填写:" + ",".join(fields) if fields else "填写")
        issues = adapter.verify(page, job)
        if issues:
            steps.append("校验:" + "; ".join(issues))

        snapshot = dump_form_snapshot(page)
        learned = form_learning.learn_snapshot(
            snapshot,
            portal=adapter.name,
            url=job.url,
            company=job.company,
            title=job.title,
            profile=profile,
            issues=issues,
        )
        steps.append(f"表单学习:{learned['learned']}字段,缺资料{learned['missing']},待映射{learned['unmapped']}")
        record = state.record(
            adapter.name,
            job.company,
            job.title,
            job.url,
            "filled",
            resume=resume_record,
            steps=steps,
        )
        shot = config.STATE_DIR / f"fill_{adapter.name}_{index}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        page.screenshot(path=str(shot), full_page=True)
        print(f"[{index}] 已填写并保留：{record['status']}；校验问题 {len(issues)} 项；截图 {shot}")
        return {
            "index": index,
            "status": "filled",
            "portal": adapter.name,
            "company": job.company,
            "title": job.title,
            "url": job.url,
            "resume": resume_record,
            "fields": fields,
            "issues": issues,
            "screenshot": str(shot),
            "page": page,
        }
    except Blocked as error:
        if job is not None:
            state.record(
                adapter.name,
                job.company,
                job.title,
                job.url,
                "blocked",
                resume=str(resume),
                error=error.reason,
            )
        print(f"[{index}] ⛔ 需要人工介入：{error}")
        if error.hint:
            print(f"  提示: {error.hint}")
        _save_probe(error, page, job, url, profile)
        return {
            "index": index,
            "status": "blocked",
            "portal": adapter.name,
            "company": job.company if job else str(entry.get("company") or ""),
            "title": job.title if job else str(entry.get("title") or ""),
            "url": job.url if job else url,
            "resume": str(resume),
            "error": error.reason,
            "page": page,
        }
    except Exception as error:
        print(f"[{index}] ⛔ 未预期错误：{error}")
        traceback.print_exc()
        return {
            "index": index,
            "status": "error",
            "url": job.url if job else url,
            "error": str(error),
            "page": page,
        }


def prepare_all(entries: list[dict[str, Any]], resumes: list[Path]) -> int:
    """准备所有队列项并让浏览器保持开启；不会点击任何最终提交按钮。"""
    if len(entries) != len(resumes):
        raise ValueError("队列与简历数量不一致")
    if not entries:
        return 0

    config.ensure_dirs()
    prepared_resumes: list[Path] = []
    try:
        for entry, resume in zip(entries, resumes):
            requested_name = str(entry.get("resume_filename") or entry.get("cv_upload_name") or "").strip() or None
            prepared_resumes.append(materials.prepare_upload_file(resume, requested_name))
    except materials.MaterialError as error:
        print(f"简历材料预检失败，未启动浏览器：{error}")
        return 2
    profile = model.load_profile()
    playwright = None
    results: list[dict[str, Any]] = []
    try:
        playwright, context, first_page = launch(headless=False)
        for offset, (entry, resume) in enumerate(zip(entries, prepared_resumes)):
            page = first_page if offset == 0 else context.new_page()
            page.bring_to_front()
            print(f"\n{'=' * 64}\n准备第 {offset + 1}/{len(entries)} 个申请标签页\n{'=' * 64}")
            results.append(_prepare_one(page, entry, resume, profile, offset + 1))

        print("\n所有申请页处理完毕（未提交）：")
        for result in results:
            print(
                f"  {result['index']}. [{result['status']}] "
                f"{result.get('company', '')} — {result.get('title', '')}\n"
                f"     {result.get('url', '')}"
            )
            if result.get("issues"):
                for issue in result["issues"]:
                    print(f"     待人工检查: {issue}")
            if result.get("error"):
                print(f"     待人工处理: {result['error']}")

        # 将第一个未完全填写的标签页置前；若全部成功则保留最后一个在前台。
        attention = next((item for item in results if item["status"] != "filled"), results[-1])
        attention["page"].bring_to_front()
        input("\n浏览器中的全部申请标签页将保持打开。逐页检查完成后，回到终端按回车才关闭…")
        return 0 if all(item["status"] == "filled" for item in results) else 5
    except BrowserError as error:
        print(f"\n⛔ 浏览器错误：{error}")
        return 6
    finally:
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
