"""批量队列：从 seen_jobs.json 选出高匹配新岗位，逐个 apply_one。

用法：
  python -m apply_bot.run_batch [--limit 3] [--from seen|queue] [--queue queue.json]
                    [--min-fit high] [--portal bytedance,shixiseng,tencent]
                    [--fill-only] [--review-last | --retain-all] [--dry-run]

--dry-run 只打印队列，不启动浏览器。
默认每个岗位独立调用 apply_one.run()；``--retain-all`` 则在一个 Chrome 会话中
为每个岗位保留独立审核标签页，并且永远不进入最终提交。确认关卡保留在每个
岗位的正式提交阶段。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import config, materials, state
from .apply_one import run as run_one
from .portals import adapter_for_url


def resolve_queue_cv(entry: dict[str, Any]) -> Path | None:
    """解析队列显式绑定的岗位定向简历，不做通用简历回退。"""
    raw = str(entry.get("cv") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = config.WORKSPACE / path
    return path.resolve()


def resolve_queue_upload_name(entry: dict[str, Any]) -> str | None:
    """Read the posting-mandated filename from the queue without inventing one."""
    raw = str(entry.get("resume_filename") or entry.get("cv_upload_name") or "").strip()
    return raw or None


def build_queue(source: str, queue_file: Path | None, min_fit: list[str], portal_filter: list[str] | None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if source == "queue" and queue_file and queue_file.exists():
        with open(queue_file, encoding="utf-8") as f:
            data = json.load(f)
        entries = data if isinstance(data, list) else data.get("entries", [])
    else:
        if not config.SEEN_JOBS_JSON.exists():
            print(f"未找到 {config.SEEN_JOBS_JSON}；可用 --from queue --queue <file>")
            return []
        with open(config.SEEN_JOBS_JSON, encoding="utf-8") as f:
            seen = json.load(f).get("seen", {})
        for key, e in seen.items():
            url = e.get("url")
            if not url:
                continue
            info = {"url": url, "company": e.get("company", ""), "title": e.get("title", ""),
                    "fit": e.get("fit", ""), "status": e.get("status", ""), "portal": e.get("portal", "")}
            entries.append(info)
    out: list[dict[str, Any]] = []
    for e in entries:
        if min_fit and e.get("fit") not in min_fit:
            continue
        if portal_filter and not any(p in str(e.get("portal", "")) for p in portal_filter):
            continue
        out.append(e)
    # 去除已提交
    res: list[dict[str, Any]] = []
    for e in out:
        if state.is_submitted(str(e.get("portal", "")), e.get("company", ""), e.get("title", "")):
            continue
        res.append(e)
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="批量投递队列（每岗位提交前人工确认）")
    ap.add_argument("--limit", type=int, default=0, help="最多处理 N 个（0=全部）")
    ap.add_argument("--from", dest="source", choices=["seen", "queue"], default="seen")
    ap.add_argument("--queue", type=Path, help="队列 JSON 文件（--from queue 时用）")
    ap.add_argument("--min-fit", default="high",
                    help="按 fit 过滤（逗号分隔，可选 high/medium/low/unknown；默认 high。"
                         "sync_seen --auto-fit 标记的岗位可直接选 high,medium；unknown 需人工或 /rank 评估后再投）")
    ap.add_argument("--portal", help="限定站点（逗号分隔，如 bytedance,shixiseng）")
    ap.add_argument("--fill-only", action="store_true",
                    help="安全实验：逐个填表和校验，不进入提交确认，不点击提交")
    ap.add_argument("--review-last", action="store_true",
                    help="与 --fill-only 配合：最后一个岗位填完后保留浏览器，按回车才关闭")
    ap.add_argument("--retain-all", action="store_true",
                    help="与 --fill-only 配合：单一 Chrome 多标签页填写全部岗位并全部保留，绝不提交")
    ap.add_argument("--require-tailored-cv", action="store_true",
                    help="完整流水线护栏：每个队列项必须显式提供存在的 cv 路径，禁止回退通用简历")
    ap.add_argument("--dry-run", action="store_true", help="只打印队列")
    args = ap.parse_args(argv)

    if args.review_last and not args.fill_only:
        ap.error("--review-last 必须与 --fill-only 一起使用")
    if args.retain_all and not args.fill_only:
        ap.error("--retain-all 必须与 --fill-only 一起使用")
    if args.retain_all and args.review_last:
        ap.error("--retain-all 与 --review-last 不能同时使用")

    portal_filter = [p.strip() for p in (args.portal or "").split(",") if p.strip()] or None
    fit_filter = [f.strip() for f in (args.min_fit or "").split(",") if f.strip()] or ["high"]
    invalid = [f for f in fit_filter if f not in {"high", "medium", "low", "unknown"}]
    if invalid:
        print(f"无效 --min-fit 取值: {invalid}（可选 high/medium/low/unknown）")
        return 2
    queue = build_queue(args.source, args.queue, fit_filter, portal_filter)
    if args.limit:
        queue = queue[: args.limit]

    if not queue:
        print("队列为空。")
        return 0

    queue_cvs = [resolve_queue_cv(entry) for entry in queue]
    if args.require_tailored_cv:
        material_errors: list[str] = []
        for index, (entry, cv_path) in enumerate(zip(queue, queue_cvs), 1):
            if cv_path is None:
                material_errors.append(f"{index}. {entry.get('company')} {entry.get('title')}：队列缺少 cv")
            elif not cv_path.exists():
                material_errors.append(f"{index}. {entry.get('company')} {entry.get('title')}：cv 不存在 {cv_path}")
            elif config.CV_DIR not in cv_path.parents:
                material_errors.append(f"{index}. {entry.get('company')} {entry.get('title')}：cv 必须位于 {config.CV_DIR}")
            elif cv_path.suffix.lower() not in {".pdf", ".doc", ".docx"}:
                material_errors.append(f"{index}. {entry.get('company')} {entry.get('title')}：cv 文件格式不支持 {cv_path.suffix}")
            else:
                try:
                    materials.require_current_project_template(cv_path)
                    upload_name = resolve_queue_upload_name(entry)
                    if upload_name:
                        materials.validate_upload_filename(upload_name, cv_path.suffix)
                except materials.MaterialError as error:
                    material_errors.append(f"{index}. {entry.get('company')} {entry.get('title')}：{error}")
        if material_errors:
            print("定向材料预检失败，未启动浏览器：")
            for error in material_errors:
                print(f"  - {error}")
            return 2
    print(f"待处理 {len(queue)} 个岗位：")
    for i, e in enumerate(queue, 1):
        upload_note = f"  上传名={resolve_queue_upload_name(e)}" if resolve_queue_upload_name(e) else ""
        print(f"  {i:2d}. [{e.get('fit')}] {e.get('company')} — {e.get('title')}  {e.get('url')}{upload_note}")

    if args.dry_run:
        return 0

    if args.retain_all:
        from .prepare_batch import prepare_all

        # --require-tailored-cv 已在上方完成严格预检；retain-all 不允许没有
        # 显式简历的队列，因为多岗位同公司时自动回退可能上传错版本。
        missing = [
            f"{entry.get('company')} — {entry.get('title')}"
            for entry, cv_path in zip(queue, queue_cvs) if cv_path is None
        ]
        if missing:
            print("--retain-all 要求每个队列项显式绑定 cv：")
            for item in missing:
                print(f"  - {item}")
            return 2
        return prepare_all(queue, [path for path in queue_cvs if path is not None])

    ok = skipped = 0
    for index, (e, cv_path) in enumerate(zip(queue, queue_cvs)):
        url = e.get("url")
        adapter = adapter_for_url(url)
        print(f"\n{'=' * 64}\n处理: {e.get('company')} — {e.get('title')}\n{'=' * 64}")
        if adapter is None:
            print(f"  ⏭ 跳过（站点未适配）: {url}")
            skipped += 1
            continue
        code = run_one(
            url,
            portal=adapter.name,
            cv=cv_path,
            cv_upload_name=resolve_queue_upload_name(e),
            fill_only=args.fill_only,
            review=args.review_last and index == len(queue) - 1,
            expect_company=e.get("company") or None,
            expect_title=e.get("title") or None,
        )
        if code == 0:
            ok += 1
        else:
            skipped += 1
    print(f"\n完成：成功 {ok}，跳过/需人工 {skipped}。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
