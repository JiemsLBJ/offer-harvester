"""岗位发现：用浏览器会话抓取「无公开 API」站点的职位列表。

用法：
  python -m apply_bot.discover bytedance [--keyword 数据分析] [--location 上海]
        [--limit 20] [--write] [--headless] [--list-url <完整列表页URL>]

--write 才写入 job_scraper/seen_jobs.json（portal=bytedance-search, source=browser），
缺省为预览。投递未验证前，发现结果 status=new / fit=unknown，由 /rank 接手评估。
--list-url 直接打开带筛选参数的列表页（如 from=xx&keywords=xx 的完整 URL）。
每次运行会把页面加载期间与 job/api 相关的 JSON 响应 URL 打印出来——若站点
暴露公开接口，可据此为 bytedance-search 建立免浏览器通道。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from . import config, source_monitor
from .browser import BrowserError, launch
from .portals.bytedance import discover_jobs as discover_bytedance
from .portals.xiaohongshu import discover_jobs as discover_xiaohongshu
from .portals.bilibili import discover_jobs as discover_bilibili
from .portals.boss import discover_jobs as discover_boss
from .portals.base import Blocked

TODAY = __import__("time").strftime("%Y-%m-%d")
DISCOVERERS = {
    "bytedance": discover_bytedance,
    "xiaohongshu": discover_xiaohongshu,
    "bilibili": discover_bilibili,
    "boss": discover_boss,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="浏览器会话岗位发现")
    ap.add_argument("portal", choices=sorted(DISCOVERERS), help="站点")
    ap.add_argument("--keyword", default="数据分析")
    ap.add_argument("--location", default="")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--list-url", help="直接打开完整列表页 URL（跳过关键词构造）")
    ap.add_argument("--write", action="store_true", help="写入 seen_jobs.json")
    ap.add_argument("--headless", action="store_true", help="无头（发现用）")
    args = ap.parse_args(argv)
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    entry_url = args.list_url or source_monitor.default_entry_url(args.portal)

    config.ensure_dirs()
    if not config.SEEN_JOBS_JSON.exists():
        config.SEEN_JOBS_JSON.parent.mkdir(parents=True, exist_ok=True)
        config.SEEN_JOBS_JSON.write_text('{"seen": {}}\n', encoding="utf-8")
    seen: dict[str, Any] = json.loads(config.SEEN_JOBS_JSON.read_text(encoding="utf-8")).get("seen", {})

    api_urls: list[str] = []

    p = None
    try:
        p, context, page = launch(headless=args.headless)
        page.on(
            "response",
            lambda res: api_urls.append(res.url)
            if ("api" in res.url and "json" in (res.headers.get("content-type") or ""))
            else None,
        )
        jobs = DISCOVERERS[args.portal](
            page,
            keyword=args.keyword,
            limit=args.limit,
            location=args.location,
            list_url=args.list_url,
        )
    except (BrowserError, Blocked) as e:
        source_monitor.record_run(
            args.portal, status="error", mode="browser", keyword=args.keyword,
            location=args.location, entry_url=entry_url, message=str(e), started_at=started_at,
        )
        print(f"⛔ {e}")
        return 1
    finally:
        if p is not None:
            try:
                p.stop()
            except Exception:
                pass

    if api_urls:
        print("\n页面加载期间发现的 JSON API 响应（可用于免浏览器抓取调研）:")
        for u in sorted(set(api_urls)):
            print(f"  {u}")
        try:
            out = config.STATE_DIR / f"{args.portal}_api_urls.json"
            out.write_text(json.dumps(sorted(set(api_urls)), ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  已存 {out}")
        except Exception:
            pass

    new: list[dict[str, Any]] = []
    for j in jobs:
        job_id = j.get("id") or ""
        key = f"{args.portal}:{job_id or j['url']}"
        if key in seen:
            continue
        entry = {
            "title": j["title"],
            "company": j["company"],
            "url": j["url"],
            "first_seen": TODAY,
            "deadline": None,
            "fit": "unknown",
            "status": "new",
            "portal": f"{args.portal}-search",
            "source": "browser",
        }
        seen[key] = entry
        new.append(entry)

    run_status = "success" if jobs else "warning"
    run_message = (
        f"成功读取 {len(jobs)} 条岗位。" if jobs
        else "官网返回 0 条岗位；没有把其他招聘类别当作实习结果。请检查入口、筛选条件或站点状态。"
    )
    source_monitor.record_run(
        args.portal, status=run_status, mode="browser", keyword=args.keyword,
        location=args.location, discovered_count=len(jobs), new_count=len(new),
        entry_url=entry_url, message=run_message, started_at=started_at,
        details={"write": args.write, "api_urls": len(set(api_urls))},
    )

    print(f"发现 {len(jobs)} 条，新增 {len(new)} 条：")
    for e in new:
        print(f"  + {e['company']} — {e['title']}  {e['url']}")

    if args.write and new:
        config.SEEN_JOBS_JSON.write_text(json.dumps({"seen": seen}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已写入 {config.SEEN_JOBS_JSON}")
    elif not args.write:
        print("预览模式；加 --write 写入。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
