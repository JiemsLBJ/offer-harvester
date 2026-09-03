"""BOSS 直聘只读辅助：读取单岗位并生成本地沟通草稿，绝不发送。

用法：
  python -m apply_bot.boss_assist <BOSS岗位URL> [--save] [--headless]

岗位读取受登录/安全验证限制时明确阻塞，不尝试绕过。草稿只使用 profile.json
已确认事实；用户必须自己在 BOSS 页面复制、检查并点击发送。
"""
from __future__ import annotations

import argparse
import re
import sys
import time

from . import config, model
from .browser import BrowserError, launch
from .portals.base import Blocked
from .portals.boss import BossAdapter


def draft_message(title: str, description: str, profile: dict) -> str:
    identity = profile["identity"]
    availability = profile["availability"]
    pitch = (profile.get("self_intro") or {}).get("zh_60") or "具备数据分析背景，熟悉Python与SQL"
    if not pitch.endswith(("。", "！", "！")):
        pitch += "。"
    edu = (profile.get("education") or [{}])[0]
    edu_phrase = "".join(
        part for part in (edu.get("school"), edu.get("major"), edu.get("degree")) if part
    ) or "在读学生"
    days = str(availability.get("days_per_week") or "4-5")
    months = availability.get("min_months") or 3
    return (
        f"您好，我是{identity['name']}，{edu_phrase}。{pitch}"
        f"看到贵司的{title}岗位与我的方向匹配；可立即到岗，每周{days}天、至少{months}个月。"
        "若合适，烦请查看我的简历，谢谢。"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="BOSS 单岗位只读分析与沟通草稿（不发送）")
    ap.add_argument("url", help="BOSS 岗位详情 URL")
    ap.add_argument("--save", action="store_true", help="把草稿保存到 state（仍不发送）")
    ap.add_argument("--headless", action="store_true", help="无头读取；被验证拦截时改用可见浏览器人工处理")
    args = ap.parse_args(argv)
    if "/job_detail/" not in args.url:
        print("需要 BOSS /job_detail/ 单岗位 URL；不会对搜索结果自动发消息。")
        return 2

    p = None
    try:
        p, context, page = launch(headless=args.headless)
        job = BossAdapter().open_job(page, args.url)
        profile = model.load_profile()
        draft = draft_message(job.title, str(job.raw.get("description") or ""), profile)
        print(f"[岗位] {job.company} — {job.title}\n       {job.url}")
        print("\n沟通草稿（仅本地，未发送）：\n" + draft)
        print("\n请人工核对后复制到 BOSS；本工具没有点击打招呼、沟通或发送简历。")
        if args.save:
            config.ensure_dirs()
            safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", job.id or str(int(time.time())))
            out = config.STATE_DIR / f"boss_draft_{safe_id}.txt"
            out.write_text(draft + "\n", encoding="utf-8")
            print(f"已保存草稿: {out}")
        return 0
    except (Blocked, BrowserError) as e:
        reason = e.reason if isinstance(e, Blocked) else str(e)
        hint = e.hint if isinstance(e, Blocked) else ""
        print(f"⛔ {reason}")
        if hint:
            print(f"  {hint}")
        return 5
    finally:
        if p is not None:
            try:
                p.stop()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
