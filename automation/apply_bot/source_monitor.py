"""岗位来源目录、抓取运行历史与控制台健康状态。"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import application_store, config


SOURCES: list[dict[str, Any]] = [
    # 通用招聘平台。enabled 只表示已有真实发现流程，不能把“已列入目录”
    # 和“已经能够稳定抓取”混为一谈。
    {
        "portal": "linkedin", "name": "LinkedIn Jobs", "category": "platform", "tier": "primary", "enabled": True,
        "mode": "CLI · 公开职位页", "entry_url": "https://www.linkedin.com/jobs/",
        "cadence": "日常同步", "description": "面向全球岗位的补充来源；低频读取公开职位页，遵守个人使用与限流约束。",
    },
    {
        "portal": "freehire", "name": "FreeHire", "category": "platform", "tier": "primary", "enabled": True,
        "mode": "CLI · 聚合公开 API", "entry_url": "https://freehire.me/jobs",
        "cadence": "日常同步", "description": "技术、数据和工程岗位聚合来源，日常同步只读取精简职位卡片。",
    },
    {
        "portal": "51job", "name": "前程无忧 51job", "category": "platform", "tier": "inactive", "enabled": False,
        "mode": "来源入口已核验", "entry_url": "https://search.51job.com/jobsearch/advance_search.php",
        "cadence": "待开发", "description": "已纳入来源地图；尚未建立稳定、合规的自动发现适配器。",
    },
    {
        "portal": "zhaopin", "name": "智联招聘", "category": "platform", "tier": "inactive", "enabled": False,
        "mode": "已有单岗位投递适配", "entry_url": "https://www.zhaopin.com/",
        "cadence": "待接入发现", "description": "可以安全处理给定岗位；职位搜索仍可能触发人机验证，不绕过。",
    },
    {
        "portal": "liepin", "name": "猎聘", "category": "platform", "tier": "inactive", "enabled": False,
        "mode": "来源入口已登记", "entry_url": "https://www.liepin.com/",
        "cadence": "待开发", "description": "尚未接入职位发现或专用投递适配；可对直达申请表使用通用填表。",
    },
    {
        "portal": "lagou", "name": "拉勾招聘", "category": "platform", "tier": "inactive", "enabled": False,
        "mode": "来源入口已登记", "entry_url": "https://campus.lagou.com/",
        "cadence": "待开发", "description": "尚未接入职位发现；登录、验证码和站点限制均只允许人工完成。",
    },
    {
        "portal": "shixiseng", "name": "实习僧", "category": "platform", "tier": "primary", "enabled": True,
        "mode": "CLI · 服务端页面", "entry_url": "https://www.shixiseng.com/interns",
        "cadence": "日常同步", "description": "实习岗位主来源，公开读取列表与详情，无需登录。",
    },
    {
        "portal": "boss", "name": "BOSS直聘", "category": "platform", "tier": "assist", "enabled": True,
        "mode": "浏览器 · 用户指定列表", "entry_url": "https://www.zhipin.com/",
        "cadence": "人工指定页面", "description": "只读当前列表与岗位，不自动打招呼、沟通或发送简历。",
    },
    {
        "portal": "nowcoder", "name": "牛客", "category": "platform", "tier": "inactive", "enabled": False,
        "mode": "已有官网跳转适配", "entry_url": "https://www.nowcoder.com/jobs/center",
        "cadence": "待接入发现", "description": "当前只处理给定岗位或企业官网跳转，不进入日常爬取。",
    },
    {
        "portal": "ncss", "name": "国家大学生就业服务平台", "category": "platform", "tier": "inactive", "enabled": False,
        "mode": "来源入口已核验", "entry_url": "https://xjbys.ncss.cn/student/jobs/index.html",
        "cadence": "待开发", "description": "已纳入来源地图；尚未验证稳定的职位发现与详情解析流程。",
    },

    # 重点公司官网。
    {
        "portal": "company", "name": "公司官网 · 多招聘系统", "category": "company", "tier": "supplemental", "enabled": True,
        "mode": "CLI · 官网公开接口", "entry_url": "",
        "cadence": "按需运行 --sources company", "description": "原生支持美团、飞书招聘、Moka、Greenhouse、Lever、Ashby；实际公司与可用性见配置及每次运行详情，不等于新增自动填表支持。",
    },
    {
        "portal": "tencent", "name": "腾讯招聘", "category": "company", "tier": "primary", "enabled": True,
        "mode": "CLI · 官方公开 API", "entry_url": "https://careers.tencent.com/search.html",
        "cadence": "日常同步", "description": "腾讯实习、校招和社招岗位主来源，可读取完整岗位详情。",
    },
    {
        "portal": "hotjob", "name": "德勤招聘（Hotjob/Wecruit）", "category": "company", "tier": "primary", "enabled": True,
        "mode": "CLI · 官网公开接口", "entry_url": "https://wecruit.hotjob.cn/SU64365a780dcad43c5ae82bab/pb/interns.html",
        "cadence": "日常同步", "description": "读取德勤实习岗位列表、单岗位职责、任职资格和截止日期；投递使用 Hotjob 专用适配器。",
    },
    {
        "portal": "bytedance", "name": "字节跳动", "category": "company", "tier": "supplemental", "enabled": True,
        "mode": "浏览器 · 官网列表", "entry_url": "https://jobs.bytedance.com/campus/job",
        "cadence": "按需运行", "description": "官网存在 WAF，使用真实浏览器读取校园招聘列表。",
    },
    {
        "portal": "alibaba", "name": "阿里巴巴招聘", "category": "company", "tier": "inactive", "enabled": False,
        "mode": "官网入口已登记", "entry_url": "https://campus-talent.alibaba.com/campus/position",
        "cadence": "待开发", "description": "已列入重点公司；尚未固化职位接口、分页和实习筛选规则。",
    },
    {
        "portal": "meituan", "name": "美团招聘", "category": "company", "tier": "inactive", "enabled": False,
        "mode": "官网入口已核验", "entry_url": "https://career.meituan.com/",
        "cadence": "待开发", "description": "官网提供日常实习与转正实习入口；尚未接入自动发现。",
    },
    {
        "portal": "bilibili", "name": "哔哩哔哩", "category": "company", "tier": "supplemental", "enabled": True,
        "mode": "浏览器 · 校园实习 API", "entry_url": "https://jobs.bilibili.com/campus/positions?type=2",
        "cadence": "按需运行", "description": "仅允许校园实习入口；社会招聘不会写入实习岗位库。",
    },
    {
        "portal": "ant", "name": "蚂蚁集团招聘", "category": "company", "tier": "inactive", "enabled": False,
        "mode": "官网入口已登记", "entry_url": "https://talent.antgroup.com/campus/home",
        "cadence": "待开发", "description": "已列入重点公司；尚未固化职位列表与申请页结构。",
    },
    {
        "portal": "huatai", "name": "华泰证券", "category": "company", "tier": "inactive", "enabled": False,
        "mode": "官方招聘系统入口", "entry_url": "https://www.hotjob.cn/wt/HTSC/mobweb/v8/index",
        "cadence": "待开发", "description": "已定位旧版 Hotjob 官方系统；它与已接通的 Wecruit 新版路由不同，尚未接入发现与表单适配。",
    },
    {
        "portal": "cicc", "name": "中金公司", "category": "company", "tier": "inactive", "enabled": False,
        "mode": "官方招聘系统入口", "entry_url": "https://cicc.zhiye.com/",
        "cadence": "待开发", "description": "已列入金融机构重点来源；尚未验证当前职位接口和筛选参数。",
    },
    {
        "portal": "mycapital", "name": "茂源量化", "category": "company", "tier": "inactive", "enabled": False,
        "mode": "官网招聘页", "entry_url": "https://www.mycapital.net/cn/careers",
        "cadence": "待开发", "description": "官网招聘页已登记；可能包含静态职位或邮件申请，外发邮件必须单独确认。",
    },
    {
        "portal": "zsfund", "name": "浙商基金实习招聘", "category": "company", "tier": "inactive", "enabled": False,
        "mode": "官网实习招聘页", "entry_url": "https://www.zsfund.com/aboutus/job/job2/index.html",
        "cadence": "待开发", "description": "官网实习岗位页已核验；当前为邮件投递，不自动发送邮件。",
    },
    {
        "portal": "zhurun", "name": "竹润投资", "category": "company", "tier": "inactive", "enabled": False,
        "mode": "官网招聘页", "entry_url": "https://www.zhuruntouzi.com/zhurun/job/index.html",
        "cadence": "待开发", "description": "官网招聘入口已登记；尚未接入职位解析或申请方式识别。",
    },
    {
        "portal": "xiaohongshu", "name": "小红书", "category": "company", "tier": "supplemental", "enabled": True,
        "mode": "浏览器 · 实习筛选页", "entry_url": "https://job.xiaohongshu.com/campus/position?campusRecruitTypes=term_intern",
        "cadence": "按需运行", "description": "只读取校园招聘中的日常实习入口。",
    },
]


def default_entry_url(portal: str) -> str:
    return next((str(item["entry_url"]) for item in SOURCES if item["portal"] == portal), "")


def _stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def record_run(
    portal: str,
    *,
    status: str,
    mode: str,
    keyword: str = "",
    location: str = "",
    discovered_count: int = 0,
    new_count: int = 0,
    entry_url: str = "",
    message: str = "",
    started_at: str = "",
    details: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    finished = _stamp()
    return application_store.record_source_run({
        "id": uuid.uuid4().hex,
        "portal": portal,
        "status": status,
        "mode": mode,
        "keyword": keyword,
        "location": location,
        "discovered_count": discovered_count,
        "new_count": new_count,
        "entry_url": entry_url,
        "message": message,
        "started_at": started_at or finished,
        "finished_at": finished,
        "details": details or {},
    }, db_path)


def import_event_log(db_path: Path | None = None, path: Path | None = None) -> int:
    """导入 Bun 抓取器写出的跨运行时 JSONL 事件。"""
    source = path or config.SOURCE_RUN_LOG
    if not source.exists():
        return 0
    imported = 0
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if isinstance(event, dict) and event.get("id") and event.get("portal"):
                application_store.record_source_run(event, db_path)
                imported += 1
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return imported


LEGACY_NAMES = {
    "websearch-shixiseng": "实习僧网页搜索历史",
    "freehire": "FreeHire 聚合",
    "websearch-streetintern": "实习街网页搜索历史",
    "websearch-bebee": "beBee 网页搜索历史",
    "websearch": "通用网页搜索历史",
    "websearch-moledao": "魔力岛网页搜索历史",
    "websearch-linkedin": "LinkedIn 网页搜索历史",
    "websearch-nankai": "南开就业信息网历史",
}


def _seen_inventory(path: Path | None = None) -> tuple[dict[str, int], dict[str, str]]:
    source = path or config.SEEN_JOBS_JSON
    counts: dict[str, int] = {}
    samples: dict[str, str] = {}
    try:
        seen = json.loads(source.read_text(encoding="utf-8")).get("seen", {})
    except (OSError, ValueError, AttributeError):
        return counts, samples
    for key, entry in seen.items():
        portal = str(entry.get("portal") or str(key).split(":", 1)[0]).replace("-search", "")
        if portal == "company-careers":
            portal = "company"
        counts[portal] = counts.get(portal, 0) + 1
        if portal not in samples and entry.get("url"):
            raw = str(entry["url"])
            parsed = urlsplit(raw)
            samples[portal] = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else raw
    return counts, samples


def _evidence_time(portal: str) -> str:
    candidates = [
        config.STATE_DIR / f"{portal}_api_urls.json",
        config.STATE_DIR / f"probe_{portal}.json",
    ]
    existing = [path for path in candidates if path.exists()]
    if not existing:
        return ""
    latest = max(existing, key=lambda path: path.stat().st_mtime)
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest.stat().st_mtime))


def source_payload(db_path: Path | None = None, seen_path: Path | None = None) -> dict[str, Any]:
    import_event_log(db_path)
    runs = application_store.list_source_runs(100, db_path)
    activity_by_day: dict[str, dict[str, int | str]] = {}
    batch_ids: set[str] = set()
    for run in runs:
        day = str(run.get("finished_at") or "")[:10]
        if not day:
            continue
        details = run.get("details") if isinstance(run.get("details"), dict) else {}
        batch_ids.add(str(details.get("batch_id") or run.get("id") or ""))
        bucket = activity_by_day.setdefault(day, {"date": day, "discovered_count": 0, "new_count": 0, "runs": 0})
        bucket["discovered_count"] = int(bucket["discovered_count"]) + int(run.get("discovered_count") or 0)
        bucket["new_count"] = int(bucket["new_count"]) + int(run.get("new_count") or 0)
        bucket["runs"] = int(bucket["runs"]) + 1
    latest: dict[str, dict[str, Any]] = {}
    for run in runs:
        latest.setdefault(run["portal"], run)
    counts, samples = _seen_inventory(seen_path)
    sources: list[dict[str, Any]] = []
    for definition in SOURCES:
        item = dict(definition)
        portal = item["portal"]
        last = latest.get(portal)
        item["seen_count"] = counts.get(portal, 0)
        item["last_run"] = last
        if last:
            item["health"] = last["status"]
            item["message"] = last.get("message") or "抓取运行已记录。"
        elif portal == "bilibili" and _evidence_time(portal):
            item["health"] = "warning"
            item["message"] = "最近一次校园实习接口返回 0 条；社会招聘探路结果未计入实习来源。"
            item["evidence_at"] = _evidence_time(portal)
        elif not item["enabled"]:
            item["health"] = "inactive"
            item["message"] = "尚未进入自动岗位发现流程。"
        elif item["seen_count"]:
            item["health"] = "historical"
            item["message"] = "已有历史入库数据；新监控从下一次抓取开始记录运行结果。"
        else:
            item["health"] = "not_run"
            item["message"] = "监控启用后尚未运行。"
        sources.append(item)
    known = {item["portal"] for item in sources}
    for portal, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])):
        if portal in known:
            continue
        sources.append({
            "portal": portal,
            "name": LEGACY_NAMES.get(portal, portal),
            "category": "history",
            "tier": "history",
            "enabled": False,
            "mode": "历史网页搜索或聚合来源",
            "entry_url": samples.get(portal, ""),
            "cadence": "非日常抓取",
            "description": "岗位库中的既有记录，来源监控启用前已入库。",
            "seen_count": count,
            "last_run": None,
            "health": "historical",
            "message": "保留用于去重和岗位评估，但目前不会由自动同步任务持续更新。",
        })
    return {
        "sources": sources,
        "source_runs": runs[:30],
        "scrape_activity": [activity_by_day[day] for day in sorted(activity_by_day)[-14:]],
        "source_summary": {
            "primary": sum(1 for item in sources if item["tier"] == "primary"),
            "enabled": sum(1 for item in sources if item["enabled"]),
            "healthy": sum(1 for item in sources if item["enabled"] and item["health"] in {"success", "historical"}),
            "warnings": sum(1 for item in sources if item["enabled"] and item["health"] in {"warning", "error"}),
            "tracked_jobs": sum(item["seen_count"] for item in sources),
            "batches": len(batch_ids),
        },
    }
