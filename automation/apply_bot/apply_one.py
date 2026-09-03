"""单岗位投递驱动：URL → 打开 → 登录检测 → 填写 → 校验 → 人工确认 → 提交 → 回执。

用法：
  python -m apply_bot.apply_one <岗位URL> [--portal 站点名]
        [--cv 简历路径] [--cv-upload-name 岗位指定文件名]
        [--expect-company 公司] [--expect-title 岗位名]
        [--probe] [--fill-only] [--review] [--profile-dir 浏览器档案目录]
        [--no-tracker] [--selfcheck]

--probe    只打开页面并输出表单快照（不填写、不提交），用于站点首次探路。
--review   填写后暂停，按回车才关闭浏览器，便于人工检查。
--selfcheck 检查依赖/档案/简历是否存在，不启动浏览器。
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path
from typing import Any

from . import config, form_learning, materials, model, state, tracker
from .browser import BrowserError, launch, wait_for_login
from .confirm import ConfirmContext, confirm
from .portals import adapter_for_url, adapter_for_name
from .portals.base import Blocked, JobInfo


def selfcheck() -> int:
    config.ensure_dirs()
    problems: list[str] = []
    try:
        profile = model.load_profile()
        assert profile["identity"]["name"]
    except Exception as e:
        problems.append(f"profile.json: {e}")
    try:
        import playwright  # noqa: F401
    except Exception:
        problems.append("playwright 未安装：pip install -r automation/apply_bot/requirements.txt")
    resume = config.find_resume()
    print("selfcheck:")
    print(f"  profile.json      : {'OK' if not problems or 'profile' not in str(problems) else 'MISSING'} ({config.PROFILE_JSON})")
    print(f"  playwright        : {'OK' if 'playwright' not in str(problems) else 'MISSING'}")
    print(f"  resume            : {resume.name if resume else 'NOT FOUND（上传步骤会中止）'}")
    print(f"  chrome profile    : {config.CHROME_PROFILE_DIR}")
    if problems:
        for p in problems:
            print("  PROBLEM:", p)
        return 1
    return 0


def run(url: str, *, portal: str | None = None, cv: Path | None = None,
        cv_upload_name: str | None = None,
        expect_company: str | None = None, expect_title: str | None = None,
        probe: bool = False, fill_only: bool = False,
        review: bool = False, update_tracker: bool = True,
        headless: bool = False, profile_dir: Path | None = None) -> int:
    config.ensure_dirs()
    profile = model.load_profile()
    adapter = adapter_for_name(portal) if portal else adapter_for_url(url)
    if adapter is None:
        print(f"无法为 URL 找到已适配的站点：{url}\n可用：{', '.join(portal_names_help())}")
        return 2

    if adapter.name == "generic":
        if not probe and not fill_only:
            print("通用适配器只允许 --probe 或 --fill-only；它不会自动提交未知站点表单。")
            return 2
        if headless and not probe:
            print("通用填表必须使用可见浏览器，不能与 --headless 同用。")
            return 2

    print(f"站点适配器: {adapter.name}")

    p = None
    job: JobInfo | None = None
    try:
        p, context, page = launch(profile_dir=profile_dir, headless=headless)
        page.set_default_timeout(config.ELEMENT_TIMEOUT_MS)

        if probe:
            # 探路模式不要求登录：直接打开页面、输出可见结构快照。
            # （申请表在登录后被渲染，因此快照后仍可能提示需要人工登录补一次探路）
            snap = adapter.probe(page, url)
            print(f"探路快照已写入 {config.STATE_DIR / f'probe_{adapter.name}.json'}")
            print(f"页面标题: {snap.get('title')}")
            print("可见输入控件数:", len(snap.get("inputs", [])))
            return 0

        # 登录检测：先在站点首页加载真实页面再判断（空白页会被 is_logged_in 判为
        # 未登录，避免"未等待登录就点击投递"的错误路径）
        home = adapter.home_url or adapter.login_url
        if home:
            page.goto(home, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
        if not adapter.is_logged_in(page):
            print(f"[登录] 当前 {adapter.name} 未登录，打开登录页等待人工完成…")
            if adapter.login_url:
                page.goto(adapter.login_url, wait_until="domcontentloaded", timeout=config.NAV_TIMEOUT_MS)
            wait_for_login(context, page, adapter.is_logged_in, adapter.login_hint())

        job = adapter.open_job(page, url)
        print(f"[岗位] {job.company} — {job.title}\n       {job.url}")
        if expect_company and job.company and expect_company not in job.company:
            print(f"✗ 公司不匹配：期望 {expect_company}，页面 {job.company}；中止")
            return 3
        if expect_title and expect_title not in job.title:
            print(f"✗ 岗位名不匹配：期望 {expect_title}，页面 {job.title}；中止")
            return 3

        resume = cv or config.find_resume(job.company, prefer_docx=adapter.resume_prefers_docx)
        if resume and not resume.exists():
            print(f"简历文件不存在: {resume}")
            return 3
        if cv_upload_name and not resume:
            print("指定了 --cv-upload-name，但没有可用简历")
            return 3
        if resume:
            try:
                source_resume = resume.resolve()
                resume = materials.prepare_upload_file(source_resume, cv_upload_name)
            except materials.MaterialError as error:
                print(f"简历材料预检失败: {error}")
                return 3
            if cv_upload_name:
                print(f"[简历] 源文件: {source_resume.name}\n       实际上传文件名: {resume.name}")

        adapter.open_apply_form(page, job)
        # 部分站点（腾讯已真机确认）允许匿名查看岗位详情，只有点击「申请」后
        # 才跳转到登录页。首页阶段无法可靠判断这种延迟登录，因此在进入申请
        # 表后再做一次通用检查；扫码/验证码仍完全由用户手动完成。
        if not adapter.is_logged_in(page):
            print(f"[登录] 点击申请后 {adapter.name} 要求登录，等待人工完成…")
            wait_for_login(context, page, adapter.is_logged_in, adapter.login_hint())
        steps: list[str] = ["打开申请表"]
        fields = adapter.fill_form(page, job, profile, resume)
        learned_filled = form_learning.fill_learned_fields(page, adapter.name, profile)
        if learned_filled:
            fields.extend(f"历史补充:{label}" for label in learned_filled)
        steps.append("填写:" + ",".join(fields) if fields else "填写")
        resume_record = str(resume) if resume else None
        if any("站点复用在线简历" in field for field in fields):
            resume_record = "Hotjob账号在线简历（岗位页未上传本次定向PDF）"
        issues = adapter.verify(page, job)
        if issues:
            steps.append("校验:" + "; ".join(issues))

        record = state.record(adapter.name, job.company, job.title, job.url, "filled",
                              resume=resume_record, steps=steps)
        try:
            from .portals.base import dump_form_snapshot

            snapshot = dump_form_snapshot(page)
            learned = form_learning.learn_snapshot(
                snapshot, portal=adapter.name, url=job.url, company=job.company,
                title=job.title, profile=profile, issues=issues,
            )
            steps.append(
                f"表单学习:{learned['learned']}字段,缺资料{learned['missing']},待映射{learned['unmapped']}"
            )
            record = state.record(adapter.name, job.company, job.title, job.url, "filled",
                                  resume=resume_record, steps=steps)
        except Exception as e:
            print(f"（表单学习未完成: {e}；不影响本次人工检查）")
        print(f"已填写完成并记录（{record['status']}），校验问题 {len(issues)} 项。")

        # 验证模式：填写+校验+截图证据后即退出，不进入提交确认、不写追踪表
        if fill_only:
            try:
                import time as _t

                shot = config.STATE_DIR / f"fill_{adapter.name}_{_t.strftime('%Y%m%d_%H%M%S')}.png"
                page.screenshot(path=str(shot), full_page=True)
                print(f"填写后全页截图: {shot}")
            except Exception as e:
                print(f"（截图失败: {e}）")
            if review and not headless:
                input("（--fill-only：未提交。浏览器将保持当前页面；检查完成后按回车关闭…）")
            else:
                print("（--fill-only：已填写并记录，未进入提交确认；本次运行结束后浏览器会关闭。）")
            return 0

        ctx = ConfirmContext(
            portal=adapter.name,
            job_title=job.title,
            company=job.company,
            url=job.url,
            resume=resume_record,
            fields=fields + model.sensitive_fields(profile),
            notes=issues + ["敏感字段（证件号等）如表单必填，请人工输入后由你确认提交"],
        )
        if not confirm(ctx):
            state.record(adapter.name, job.company, job.title, job.url, "cancelled",
                         resume=resume_record, error="用户取消")
            if review and not headless:
                input("已取消投递。浏览器将保持当前页面；检查完成后按回车关闭…")
            else:
                print("已取消投递；本次运行结束后浏览器会关闭。")
            return 4

        adapter.submit(page, job)
        receipt = adapter.wait_receipt(page, job)
        final = state.record(adapter.name, job.company, job.title, job.url, "submitted",
                             resume=resume_record,
                             receipt=receipt, steps=steps + ["提交"])
        if update_tracker:
            tracker.upsert(job.company, job.title, portal=adapter.name, url=job.url,
                           cv_file=resume_record or "", deadline="")
        print(f"✔ 已提交：{job.company} {job.title}（回执: {receipt or '未检测到明确回执，请人工确认页面'}）")
        print(f"  记录: {config.APPLY_LOG}")
        return 0
    except Blocked as e:
        if job is not None:
            state.record(
                adapter.name, job.company, job.title, job.url, "blocked",
                resume=str(resume) if 'resume' in locals() and resume else None,
                error=e.reason,
            )
        print(f"\n⛔ 需要人工介入：{e}")
        if e.hint:
            print(f"  提示: {e.hint}")
        if e.probe:
            path = config.STATE_DIR / f"probe_{e.portal}.json"
            config.ensure_dirs()
            import json

            with open(path, "w", encoding="utf-8") as f:
                json.dump({"portal": e.portal, "reason": e.reason, "snapshot": e.probe}, f, ensure_ascii=False, indent=2)
            print(f"  表单快照已写入 {path}")
            try:
                form_learning.learn_snapshot(
                    e.probe, portal=e.portal, url=job.url if job else url,
                    company=job.company if job else "", title=job.title if job else "",
                    profile=profile, issues=[e.reason],
                )
                print("  未识别字段已加入控制台的「资料缺口」队列")
            except Exception as learn_error:
                print(f"  （表单学习失败: {learn_error}）")
        return 5
    except BrowserError as e:
        print(f"\n⛔ 浏览器错误：{e}")
        return 6
    except Exception as e:
        print(f"\n⛔ 未预期错误：{e}")
        traceback.print_exc()
        return 7
    finally:
        if p is not None:
            try:
                p.stop()
            except Exception:
                pass


def portal_names_help() -> list[str]:
    from .portals import portal_names
    return portal_names()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="自动投递（单岗位，提交前人工确认）")
    ap.add_argument("url", nargs="?", help="岗位详情页 URL")
    ap.add_argument("--portal", choices=portal_names_help(), help="手动指定站点（缺省按 URL 自动识别）")
    ap.add_argument("--cv", type=Path, help="指定上传的简历文件")
    ap.add_argument("--cv-upload-name", help="岗位明确要求的实际上传文件名（扩展名可省略）")
    ap.add_argument("--expect-company", help="岗位公司名校验（防止错投）")
    ap.add_argument("--expect-title", help="岗位名称校验")
    ap.add_argument("--probe", action="store_true", help="仅打开页面输出表单快照（探路模式）")
    ap.add_argument("--fill-only", action="store_true",
                    help="只完成 打开+登录+上传+填写+校验 并落盘（含全页截图），不进入提交确认（验证用）")
    ap.add_argument("--review", action="store_true",
                    help="填完或取消后暂停在当前页面，按回车才关闭浏览器（不可与 --headless 同用）")
    ap.add_argument("--no-tracker", action="store_true", help="不写 job_search_tracker.csv")
    ap.add_argument("--headless", action="store_true", help="无头模式（仅探路/巡检）")
    ap.add_argument(
        "--profile-dir", type=Path,
        help="使用独立 Chrome 登录档案目录（可同时保留另一站点的审核浏览器）",
    )
    ap.add_argument("--selfcheck", action="store_true", help="检查环境，不启动浏览器")
    args = ap.parse_args(argv)

    if args.review and args.headless:
        ap.error("--review 需要可见浏览器，不能与 --headless 同用")

    if args.selfcheck:
        return selfcheck()
    if not args.url:
        ap.print_help()
        return 2
    return run(args.url, portal=args.portal, cv=args.cv, cv_upload_name=args.cv_upload_name,
               expect_company=args.expect_company, expect_title=args.expect_title,
               probe=args.probe, fill_only=args.fill_only,
               review=args.review, update_tracker=not args.no_tracker,
               headless=args.headless, profile_dir=args.profile_dir)


if __name__ == "__main__":
    sys.exit(main())
