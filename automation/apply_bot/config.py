"""全局配置：路径、浏览器、超时。所有路径相对工作区根目录解析。"""
from __future__ import annotations

import os
from pathlib import Path

# 工作区根 = automation/apply_bot 的上两级
WORKSPACE = Path(__file__).resolve().parents[2]
AUTOMATION_DIR = WORKSPACE / "automation"
PROFILE_JSON = AUTOMATION_DIR / "profile" / "profile.json"
CV_DIR = WORKSPACE / "cv"
DOCUMENTS_DIR = WORKSPACE / "documents"
TRACKER_CSV = WORKSPACE / "job_search_tracker.csv"
SEEN_JOBS_JSON = WORKSPACE / "job_scraper" / "seen_jobs.json"

# 专用 Chrome 用户数据目录：首次运行时打开浏览器由用户扫码登录一次，之后复用会话
CHROME_PROFILE_DIR = AUTOMATION_DIR / "apply_bot" / ".chrome-profile"
STATE_DIR = AUTOMATION_DIR / "apply_bot" / "state"
APPLY_LOG = STATE_DIR / "apply_log.json"
APPLICATION_DB = STATE_DIR / "job_search.db"
SUPPLEMENTAL_PROFILE_JSON = AUTOMATION_DIR / "profile" / "supplemental_profile.json"
PROFILE_UPDATE_LOG = STATE_DIR / "profile_updates.json"
SOURCE_RUN_LOG = STATE_DIR / "source_runs.jsonl"
EMAIL_DRAFT_DIR = STATE_DIR / "email_drafts"

# 超时（毫秒/秒）
NAV_TIMEOUT_MS = 60_000
ELEMENT_TIMEOUT_MS = 15_000
UPLOAD_WAIT_S = 90          # 上传后等待站点处理
LOGIN_WAIT_S = 600          # 等待人工登录上限
POLL_INTERVAL_S = 5

# 简历自动选择：按「公司针对性 → 通用 → 兜底」排序；prefer_docx=True 时 Word 优先
# （字节实测 Word 上传解析回填最好；其余站点 PDF 优先，风险更低）
WORD_DIR = WORKSPACE / "cv" / "word"


def find_resume(company: str | None = None, prefer_docx: bool = False) -> Path | None:
    """按优先级挑选一个简历文件用于上传。

    语义：
      prefer_docx=False（默认，多数站点）：针对性 PDF 优先；Word 版仅作兜底。
      prefer_docx=True（字节实测 Word 上传解析回填最好）：针对性 Word 优先。
    层内取最新修改；层序：
      1. 公司针对性 Word（prefer_docx 时）→ 公司针对性 PDF
      2. documents/*实习简历*   （人工复核过的通用简历）
      3. 任意 Word（最新）→ 任意针对性 PDF（仅当公司未知时）
      4. cv/main_example*（主 CV PDF）
      5. cv/*.pdf（最新兜底）
    """
    import glob

    def latest(patterns: list[str]) -> Path | None:
        hits: list[Path] = []
        for pat in patterns:
            hits += [Path(p) for p in glob.glob(pat)]
        if not hits:
            return None
        return max(hits, key=lambda p: p.stat().st_mtime)

    if company:
        safe = "".join(c for c in company if c.isalnum() or c in "_-")
        if prefer_docx:
            r = latest([str(WORD_DIR / f"main_{safe}_*.docx")])
            if r:
                return r
        r = latest([str(CV_DIR / f"main_{safe}_*.pdf")])
        if r:
            return r
    r = latest([str(DOCUMENTS_DIR / "*实习简历*.pdf"), str(DOCUMENTS_DIR / "*实习简历*.docx")])
    if r:
        return r
    if not company:
        r = latest([str(WORD_DIR / "main_*.docx")])
        if r:
            return r
    r = latest([str(CV_DIR / "main_example.pdf"), str(CV_DIR / "main_example.docx")])
    if r:
        return r
    return latest([str(CV_DIR / "*.pdf")])


def ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    EMAIL_DRAFT_DIR.mkdir(parents=True, exist_ok=True)


def env_flag(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}
