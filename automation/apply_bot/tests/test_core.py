"""apply_bot 核心逻辑回归测试（无浏览器）。

用法：
  pytest automation/apply_bot/tests/test_core.py        # CI / 正常环境
  python automation/apply_bot/tests/test_core.py        # 无 pytest 环境直跑

覆盖：档案加载/字段、适配器注册、状态日志（不覆盖已提交）、追踪表（追加/更新）、
简历选择优先级、队列过滤、确认关卡渲染与判定、发现模块导入。
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
AUTOMATION_DIR = TESTS_DIR.parents[1]
sys.path.insert(0, str(AUTOMATION_DIR))

from apply_bot import application_store, browser, config, email_apply, form_learning, gmail_draft, materials, model, source_monitor, state, tracker  # noqa: E402
from apply_bot.confirm import ConfirmContext, confirm, render  # noqa: E402
from apply_bot.portals import adapter_for_name, adapter_for_url, portal_names  # noqa: E402
from apply_bot.run_batch import resolve_queue_cv  # noqa: E402

TMP = TESTS_DIR / ".tmp"
shutil.rmtree(TMP, ignore_errors=True)  # 每次运行从干净状态开始（避免陈旧数据影响断言）
TMP.mkdir(exist_ok=True)


def _ensure_profile_fixture() -> None:
    """全新克隆没有 profile.json(个人数据,已 gitignore):用示例档案顶上,保证 CI 可跑。"""
    if not config.PROFILE_JSON.exists():
        example = config.AUTOMATION_DIR / "profile" / "profile.example.json"
        if example.exists():
            config.PROFILE_JSON.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(example, config.PROFILE_JSON)


_ensure_profile_fixture()


def _fresh_state(tmp: Path) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    config.APPLY_LOG = tmp / "apply_log.json"
    config.TRACKER_CSV = tmp / "tracker.csv"
    config.APPLICATION_DB = tmp / "job_search.db"


def test_application_store_pipeline():
    db = TMP / "store" / "pipeline.db"
    first = application_store.record_application(
        "tencent", "公司A", "数据分析实习", "https://jobs.example/1", "filled", db_path=db,
        location="上海", tags=["高优先级", "数据分析"],
    )
    assert first["status"] == "filled" and first["location"] == "上海"
    applied = application_store.update_application(first["id"], {"status": "applied", "next_action": "等待回复"}, db)
    assert applied and applied["status"] == "applied" and applied["next_action"] == "等待回复"
    # 机器人重复填表不得把人工更新后的已投递状态降回 filled。
    same = application_store.record_application(
        "tencent", "公司A", "数据分析实习", "https://jobs.example/1", "filled", db_path=db,
    )
    assert same["status"] == "applied"
    assert application_store.dashboard_payload(db)["summary"]["applied"] == 1


def test_batch_queue_explicit_cv_binding():
    relative = "cv/main_公司A_数据分析实习.pdf"
    assert resolve_queue_cv({"cv": relative}) == (config.WORKSPACE / relative).resolve()
    assert resolve_queue_cv({"company": "公司A"}) is None


def test_source_monitor_payload():
    tmp = TMP / "sources"
    tmp.mkdir(parents=True, exist_ok=True)
    db = tmp / "sources.db"
    seen = tmp / "seen_jobs.json"
    seen.write_text(json.dumps({"seen": {
        "shixiseng:1": {"portal": "shixiseng-search"},
        "tencent:2": {"portal": "tencent-search"},
    }}), encoding="utf-8")
    old_log = config.SOURCE_RUN_LOG
    config.SOURCE_RUN_LOG = tmp / "source_runs.jsonl"
    try:
        source_monitor.record_run(
            "tencent", status="success", mode="cli-api", keyword="数据分析", location="上海",
            discovered_count=8, new_count=2, entry_url="https://careers.tencent.com/search.html", db_path=db,
        )
        payload = source_monitor.source_payload(db, seen)
        tencent = next(item for item in payload["sources"] if item["portal"] == "tencent")
        assert tencent["health"] == "success" and tencent["seen_count"] == 1
        assert payload["source_summary"]["primary"] == 5 and payload["source_runs"][0]["discovered_count"] == 8
        assert payload["scrape_activity"][0]["new_count"] == 2
        assert {item["category"] for item in payload["sources"]} >= {"platform", "company"}
    finally:
        config.SOURCE_RUN_LOG = old_log


def test_seen_jobs_imported_to_dashboard():
    tmp = TMP / "seen_import"
    tmp.mkdir(parents=True, exist_ok=True)
    db = tmp / "applications.db"
    seen = tmp / "seen_jobs.json"
    seen.write_text(json.dumps({"seen": {
        "shixiseng:abc": {
            "portal": "shixiseng-search", "company": "公司D", "title": "数据分析实习生",
            "url": "https://jobs.example/seen-1", "first_seen": "2026-08-25",
            "location": "上海", "fit": "high", "deadline": "2026-09-30",
        },
    }}, ensure_ascii=False), encoding="utf-8")
    old_seen, old_log, old_tracker = config.SEEN_JOBS_JSON, config.APPLY_LOG, config.TRACKER_CSV
    config.SEEN_JOBS_JSON = seen
    config.APPLY_LOG = tmp / "missing_apply_log.json"
    config.TRACKER_CSV = tmp / "missing_tracker.csv"
    try:
        result = application_store.import_existing_sources(db)
        apps = application_store.list_applications(db)
        assert result["seen_jobs"] == 1 and len(apps) == 1
        assert apps[0]["status"] == "discovered" and apps[0]["url"] == "https://jobs.example/seen-1"
        assert apps[0]["portal"] == "shixiseng" and apps[0]["fit_rating"] == "high"
    finally:
        config.SEEN_JOBS_JSON, config.APPLY_LOG, config.TRACKER_CSV = old_seen, old_log, old_tracker


def test_bilibili_discovery_rejects_social_jobs():
    from apply_bot.portals.base import Blocked
    from apply_bot.portals.bilibili import _validate_discovery_url

    _validate_discovery_url("https://jobs.bilibili.com/campus/positions?type=2")
    try:
        _validate_discovery_url("https://jobs.bilibili.com/social/positions")
        raise AssertionError("社会招聘入口不得进入实习岗位发现")
    except Blocked:
        pass


def test_form_learning_and_profile_supplement():
    tmp = TMP / "learning"
    tmp.mkdir(parents=True, exist_ok=True)
    db = tmp / "learning.db"
    old_supplement = config.SUPPLEMENTAL_PROFILE_JSON
    old_audit = config.PROFILE_UPDATE_LOG
    config.SUPPLEMENTAL_PROFILE_JSON = tmp / "supplemental_profile.json"
    config.PROFILE_UPDATE_LOG = tmp / "profile_updates.json"
    try:
        application_store.record_application(
            "xiaohongshu", "公司B", "商业分析实习", "https://jobs.example/2", "filled", db_path=db,
        )
        result = form_learning.learn_snapshot(
            {"inputs": [{"tag": "input", "placeholder": "出生年月", "type": "text", "visible": True, "required": ""}]},
            portal="xiaohongshu", url="https://jobs.example/2", company="公司B", title="商业分析实习",
            profile=model.load_profile(), db_path=db,
        )
        assert result["missing"] == 1
        req = application_store.list_requirements(db)[0]
        assert req["profile_path"] == "identity.birthday" and req["resolution_status"] == "missing"
        form_learning.save_profile_answer(req["id"], "identity.birthday", "2003-01", db)
        merged = model.load_profile()
        assert merged["identity"]["birthday"] == "2003-01"
        assert "2003-01" not in config.PROFILE_UPDATE_LOG.read_text(encoding="utf-8")
        try:
            form_learning.save_profile_answer(req["id"], "identity.id_card.value", "forbidden", db)
            raise AssertionError("身份证号写入必须被拒绝")
        except ValueError:
            pass
    finally:
        config.SUPPLEMENTAL_PROFILE_JSON = old_supplement
        config.PROFILE_UPDATE_LOG = old_audit


def test_form_learning_sensitive_id_and_certificate_do_not_map_to_major():
    id_path, id_type, id_sensitive = form_learning.infer_profile_path("ID number")
    assert id_path == "identity.id_card.value" and id_type == "sensitive" and id_sensitive
    cert_path, _, cert_sensitive = form_learning.infer_profile_path("专业证书及等级（如有）")
    assert cert_path == "form_answers.professional_certificates" and not cert_sensitive


def test_profile_load_and_fields():
    p = model.load_profile()
    assert p["identity"]["name"] and p["identity"]["phone"] and p["identity"]["email"]
    assert p["identity"]["id_card"]["value"] is None  # 敏感字段恒空
    assert len(p["education"]) >= 1
    edu = model.education_lines(p)
    assert edu[-1]["gpa"] and edu[-1]["ranking"]
    assert model.sensitive_fields(p) == ["手机号", "邮箱", "姓名"]


def test_adapter_registry():
    assert portal_names() == ["bytedance", "shixiseng", "tencent", "nowcoder", "boss", "xiaohongshu", "bilibili", "zhaopin", "hotjob", "generic"]
    assert adapter_for_url("https://www.shixiseng.com/intern/inn_x").name == "shixiseng"
    assert adapter_for_url("https://careers.tencent.com/jobdesc.html?postId=1").name == "tencent"
    assert adapter_for_url("https://jobs.bytedance.com/campus/position/1/detail").name == "bytedance"
    assert adapter_for_url("https://www.nowcoder.com/jobs/detail/1").name == "nowcoder"
    assert adapter_for_url("https://www.zhipin.com/job_detail/1.html").name == "boss"
    assert adapter_for_url("https://job.xiaohongshu.com/campus/position/1").name == "xiaohongshu"
    assert adapter_for_url("https://jobs.bilibili.com/campus/positions/1").name == "bilibili"
    assert adapter_for_url("https://www.zhaopin.com/jobdetail/CC1J1.htm").name == "zhaopin"
    assert adapter_for_url("https://wecruit.hotjob.cn/SU64365a780dcad43c5ae82bab/pb/posDetail.html?postId=66875e421c240e3d86dafec5&postType=intern").name == "hotjob"
    assert adapter_for_url("https://example.com/other") is None
    assert adapter_for_name("generic").name == "generic"


def test_generic_adapter_never_submits():
    from apply_bot.portals.base import Blocked, JobInfo

    generic = adapter_for_name("generic")
    assert generic is not None and generic.url_patterns == []
    try:
        generic.submit(None, JobInfo(title="岗位", company="公司", url="https://example.com/apply"))
        raise AssertionError("通用适配器不得提交")
    except Blocked as exc:
        assert "禁止自动提交" in exc.reason


def test_qqdocs_identity_line_uses_supplied_profile_only():
    from apply_bot.portals.generic import _qqdocs_identity_line

    profile = {
        "identity": {"name": "测试候选人"},
        "education": [
            {"level": "本科", "school": "甲大学", "major": "经济学"},
            {
                "level": "硕士（一年级在读）",
                "school": "乙大学",
                "major": "数据科学",
                "end": "2028-06（预计）",
            },
        ],
    }
    assert _qqdocs_identity_line(profile) == (
        "测试候选人 + 本科：甲大学经济学，"
        "研究生：乙大学数据科学 + 预计2028年6月毕业"
    )
    assert _qqdocs_identity_line({"identity": {"name": "测试候选人"}, "education": []}) == ""


def test_browser_diagnostics_strip_url_secrets_and_runtime_disconnects():
    assert browser._event_url("https://jobs.example/apply?token=secret#answer") == (
        "https://jobs.example/apply"
    )

    old_state_dir = config.STATE_DIR
    event_dir = TMP / "browser_events"
    config.STATE_DIR = event_dir
    try:
        browser.record_browser_event(
            "automation_error",
            stage="填写申请表",
            url="https://jobs.example/apply?token=secret#answer",
            error_type="RuntimeError",
            message="must never be persisted",
        )
        event = json.loads((event_dir / "browser_events.jsonl").read_text(encoding="utf-8"))
        assert event["url"] == "https://jobs.example/apply"
        assert "message" not in event and "secret" not in json.dumps(event)
    finally:
        config.STATE_DIR = old_state_dir

    class _Playwright:
        stopped = False

        def stop(self):
            self.stopped = True

    fake = _Playwright()
    runtime = browser.BrowserRuntime(fake, retained=True)
    runtime.stop()
    assert fake.stopped and runtime.retained


def test_generic_login_modal_takes_precedence_over_background_form():
    class _Locator:
        def __init__(self, *, count=0, text=""):
            self._count = count
            self._text = text

        def count(self):
            return self._count

        def inner_text(self, timeout=None):
            return self._text

    class _Page:
        url = "https://app.mokahr.com/example#/job/id/apply"

        def locator(self, selector):
            if selector == "input[type=password]":
                return _Locator(count=0)
            if selector == "body":
                return _Locator(text="Email login Verification code Sign in")
            if "verification code" in selector:
                return _Locator(count=2)
            if selector == "input:visible, textarea:visible, select:visible":
                return _Locator(count=30)
            return _Locator(count=0)

    generic = adapter_for_name("generic")
    assert generic is not None and generic.is_logged_in(_Page()) is False


def test_hotjob_url_identity():
    from apply_bot.portals.hotjob import canonical_hotjob_url, parse_hotjob_url, resume_readiness_issues

    url = canonical_hotjob_url("SU64365a780dcad43c5ae82bab", "66875e421c240e3d86dafec5")
    assert parse_hotjob_url(url) == ("SU64365a780dcad43c5ae82bab", "66875e421c240e3d86dafec5", "intern")
    assert parse_hotjob_url("https://wecruit.hotjob.cn/SU64365a780dcad43c5ae82bab/pb/interns.html") is None
    assert resume_readiness_issues("待完善 简历完整度：中文79% 英文22% 请完善英文简历") == [
        "Hotjob在线简历完整度：中文79%，英文22%",
        "Hotjob在线简历状态为待完善",
        "Hotjob提示请完善英文简历",
    ]


def test_state_no_overwrite():
    tmp = TMP / "t1"
    _fresh_state(tmp)
    state.record("tencent", "公司A", "数据分析实习", "https://u", "filled")
    state.record("tencent", "公司A", "数据分析实习", "https://u", "submitted", receipt="投递成功")
    # 已提交后再次写 blocked 不得覆盖
    r = state.record("tencent", "公司A", "数据分析实习", "https://u", "blocked", error="x")
    assert r["status"] == "submitted"
    assert state.is_submitted("tencent", "公司A", "数据分析实习")


def test_tracker_upsert():
    tmp = TMP / "t2"
    _fresh_state(tmp)
    tracker.upsert("公司A", "数据分析实习", portal="shixiseng", url="https://u1", cv_file="cv.pdf", fit_rating="85")
    with open(config.TRACKER_CSV, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2 and rows[1][1] == "公司A" and rows[1][3] == "数据分析实习"
    # 同 公司+岗位：更新而非追加，source 刷新
    tracker.upsert("公司A", "数据分析实习", portal="shixiseng", url="https://u2", cv_file="cv.pdf", fit_rating="85")
    with open(config.TRACKER_CSV, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2 and rows[1][12] == "https://u2"
    # 新 公司+岗位：追加
    tracker.upsert("公司B", "量化实习", portal="tencent", url="https://u3")
    with open(config.TRACKER_CSV, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 3 and rows[2][1] == "公司B"


def test_find_resume_priority():
    cv_dir = TMP / "cv_fixtures"
    word_dir = TMP / "word_fixtures"
    cv_dir.mkdir(parents=True, exist_ok=True)
    word_dir.mkdir(parents=True, exist_ok=True)
    (word_dir / "main_公司B_测试岗.docx").write_bytes(b"docx")
    (cv_dir / "main_公司C_测试岗.pdf").write_bytes(b"pdf")
    old_cv, old_word = config.CV_DIR, config.WORD_DIR
    config.CV_DIR, config.WORD_DIR = cv_dir, word_dir
    try:
        r_docx = config.find_resume("公司B", prefer_docx=True)
        assert r_docx is not None and r_docx.suffix == ".docx"
        r_pdf = config.find_resume("公司C", prefer_docx=False)
        assert r_pdf is not None and r_pdf.suffix == ".pdf"
    finally:
        config.CV_DIR, config.WORD_DIR = old_cv, old_word


def test_build_queue_filters():
    from apply_bot.run_batch import build_queue

    tmp = TMP / "queue"
    tmp.mkdir(parents=True, exist_ok=True)
    seen = tmp / "seen_jobs.json"
    seen.write_text(json.dumps({"seen": {
        "shixiseng:1": {"portal": "shixiseng-search", "company": "公司A", "title": "数据分析实习", "url": "https://u/1", "fit": "high"},
        "shixiseng:2": {"portal": "shixiseng-search", "company": "公司B", "title": "量化实习", "url": "https://u/2", "fit": "medium"},
        "tencent:3": {"portal": "tencent-search", "company": "公司C", "title": "数据实习", "url": "https://u/3", "fit": "high"},
        "tencent:4": {"portal": "tencent-search", "company": "公司D", "title": "运营实习", "url": "https://u/4", "fit": "unknown"},
    }}, ensure_ascii=False), encoding="utf-8")
    old_seen = config.SEEN_JOBS_JSON
    config.SEEN_JOBS_JSON = seen
    try:
        q_high = build_queue("seen", None, ["high"], None)
        assert len(q_high) == 2 and all(e["fit"] == "high" for e in q_high)
        q_h_u = build_queue("seen", None, ["high", "unknown"], None)
        assert len(q_h_u) == 3
        q_portal = build_queue("seen", None, ["high"], ["shixiseng"])
        assert len(q_portal) == 1 and all("shixiseng" in e.get("portal", "") for e in q_portal)
    finally:
        config.SEEN_JOBS_JSON = old_seen


def test_confirm_gate():
    ctx = ConfirmContext(
        portal="tencent", job_title="数据分析实习", company="腾讯",
        url="https://u", resume="cv.pdf", fields=["姓名", "手机号"],
        notes=["身份证号必填时人工输入"],
    )
    text = render(ctx)
    for token in ("tencent", "数据分析实习", "腾讯", "cv.pdf", "姓名", "手机号", "身份证号"):
        assert token in text
    assert confirm(ConfirmContext(portal="x", job_title="y", company="z", url="u", raw_input="y")) is True
    assert confirm(ConfirmContext(portal="x", job_title="y", company="z", url="u", raw_input="n")) is False


def test_email_draft_is_local_auditable_and_single_recipient():
    tmp = TMP / "email_draft"
    tmp.mkdir(parents=True, exist_ok=True)
    resume = tmp / "resume.pdf"
    source_image = tmp / "posting.jpg"
    resume.write_bytes(b"%PDF-1.4\nlocal-test")
    source_image.write_bytes(b"jpeg-test")

    draft = email_apply.prepare_draft(
        recipient="recruiter@gmail.com",
        subject="[硕士院校]+[专业]+[姓名]+2026级硕士+每周5天+至少3个月+可立即到岗",
        body="您好，附件为我的简历，申请行业研究实习生。",
        attachments=[resume],
        company="某券商",
        role="机械/大制造行业研究实习生",
        source_images=[source_image],
        custom_risk_notes=["原帖要求自行评估高强度工作安排"],
        draft_root=tmp / "drafts",
        sync_tracking=False,
    )
    assert draft["status"] == "drafted"
    assert Path(draft["files"]["eml"]).is_file()
    assert Path(draft["files"]["review"]).is_file()
    assert Path(draft["source_images"][0]["archived_path"]).is_file()
    assert {item["code"] for item in draft["risk_flags"]} == {
        "public_recipient_domain", "anonymized_employer", "image_only_source", "recipient_from_image",
        "posting_specific_review",
    }
    assert any("高强度" in item["detail"] for item in draft["risk_flags"])
    raw_manifest = Path(draft["files"]["manifest"]).read_text(encoding="utf-8")
    assert "AUTH_CODE" not in raw_manifest and "jpeg-test" not in raw_manifest
    try:
        email_apply.validate_single_recipient("a@example.com,b@example.com")
        raise AssertionError("邮件投递首版不得允许群发")
    except email_apply.EmailApplicationError:
        pass


def test_resume_template_guard_and_exact_upload_filename():
    tmp = TMP / "named_upload"
    tmp.mkdir(parents=True, exist_ok=True)
    current_pdf = tmp / "main_current.pdf"
    current_tex = tmp / "main_current.tex"
    current_pdf.write_bytes(b"%PDF-1.4\ncurrent-template")
    current_tex.write_text("\\documentclass{article}\n\\usepackage{onepagecv}\n", encoding="utf-8")
    legacy_pdf = tmp / "main_legacy.pdf"
    legacy_tex = tmp / "main_legacy.tex"
    legacy_pdf.write_bytes(b"%PDF-1.4\nlegacy-template")
    legacy_tex.write_text("\\documentclass{moderncv}\n", encoding="utf-8")

    old_state = config.STATE_DIR
    config.STATE_DIR = tmp / "state"
    try:
        prepared = materials.prepare_upload_file(
            current_pdf, "[硕士院校]+[专业]+[姓名]+2028年6月+可立即到岗+3个月以上每周5天.pdf",
        )
        assert prepared.name == "[硕士院校]+[专业]+[姓名]+2028年6月+可立即到岗+3个月以上每周5天.pdf"
        assert prepared.read_bytes() == current_pdf.read_bytes()
        assert prepared.with_suffix(".pdf.upload.json").is_file()
        try:
            materials.prepare_upload_file(legacy_pdf, "[姓名].pdf")
            raise AssertionError("旧 moderncv 简历必须在上传前被拒绝")
        except materials.MaterialError as exc:
            assert "moderncv" in str(exc)
        for invalid in ("../resume.pdf", "resume?.pdf", "resume.docx"):
            try:
                materials.validate_upload_filename(invalid, ".pdf")
                raise AssertionError(f"非法或扩展名不一致的文件名必须被拒绝: {invalid}")
            except materials.MaterialError:
                pass
    finally:
        config.STATE_DIR = old_state


def test_email_attachment_name_is_the_real_mime_filename():
    tmp = TMP / "email_named_attachment"
    tmp.mkdir(parents=True, exist_ok=True)
    resume = tmp / "source.pdf"
    resume.write_bytes(b"%PDF-1.4\nexact-name-test")
    expected = "院校+专业+姓名+毕业时间+到岗时间+实习时长.pdf"
    old_state = config.STATE_DIR
    config.STATE_DIR = tmp / "state"
    try:
        draft = email_apply.prepare_draft(
            recipient="jobs@example.org",
            subject="附件命名校验",
            body="附件为严格按招聘要求命名的简历。",
            attachments=[resume],
            attachment_names=[expected],
            company="测试研究所",
            role="行业研究实习生",
            draft_root=tmp / "drafts",
            sync_tracking=False,
        )
        assert draft["attachments"][0]["name"] == expected
        assert Path(draft["attachments"][0]["path"]).name == expected
        from email import policy as email_policy
        from email.parser import BytesParser

        message = BytesParser(policy=email_policy.default).parsebytes(Path(draft["files"]["eml"]).read_bytes())
        assert [item.get_filename() for item in message.iter_attachments()] == [expected]
    finally:
        config.STATE_DIR = old_state


def test_email_send_requires_exact_token_and_never_persists_auth_code():
    tmp = TMP / "email_send"
    tmp.mkdir(parents=True, exist_ok=True)
    resume = tmp / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nsend-test")
    draft = email_apply.prepare_draft(
        recipient="jobs@example.org",
        subject="单封确认测试",
        body="这是一封只在精确确认后发送的测试邮件。",
        attachments=[resume],
        company="测试公司",
        role="测试岗位",
        draft_root=tmp / "drafts",
        sync_tracking=False,
    )
    env = {
        "AI_JOB_QQ_SMTP_USER": model.load_profile()["identity"]["email"],
        "AI_JOB_QQ_SMTP_AUTH_CODE": "super-secret-auth-code",
    }

    class FakeSMTP:
        instances = []

        def __init__(self, host, port, timeout):
            self.host, self.port, self.timeout = host, port, timeout
            self.sent = 0
            FakeSMTP.instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def login(self, user, password):
            assert user == env["AI_JOB_QQ_SMTP_USER"]
            assert password == env["AI_JOB_QQ_SMTP_AUTH_CODE"]

        def send_message(self, message):
            self.sent += 1
            return {}

    try:
        email_apply.send_draft(
            draft["draft_id"], draft_root=tmp / "drafts", environ=env,
            input_func=lambda _: "y", smtp_factory=FakeSMTP, sync_tracking=False,
        )
        raise AssertionError("非精确确认口令不得发送")
    except email_apply.SendCancelled:
        pass
    assert FakeSMTP.instances == []

    sent = email_apply.send_draft(
        draft["draft_id"], draft_root=tmp / "drafts", environ=env,
        input_func=lambda _: draft["confirmation_token"], smtp_factory=FakeSMTP, sync_tracking=False,
    )
    assert sent["status"] == "sent" and FakeSMTP.instances[0].sent == 1
    raw_manifest = Path(sent["files"]["manifest"]).read_text(encoding="utf-8")
    assert env["AI_JOB_QQ_SMTP_AUTH_CODE"] not in raw_manifest
    assert "AI Job Search · 已发送" in Path(sent["files"]["review"]).read_text(encoding="utf-8")
    try:
        email_apply.send_draft(
            draft["draft_id"], draft_root=tmp / "drafts", environ=env,
            input_func=lambda _: draft["confirmation_token"], smtp_factory=FakeSMTP, sync_tracking=False,
        )
        raise AssertionError("已发送草稿不得重复发送")
    except email_apply.EmailApplicationError:
        pass


def test_gmail_clone_preserves_real_risks_without_assuming_qq_send():
    tmp = TMP / "gmail_clone"
    draft_root = tmp / "drafts"
    attachment = tmp / "resume.pdf"
    tmp.mkdir(parents=True, exist_ok=True)
    attachment.write_bytes(b"%PDF-1.4\n%%EOF\n")
    old_draft_dir = config.EMAIL_DRAFT_DIR
    config.EMAIL_DRAFT_DIR = draft_root
    try:
        source = email_apply.prepare_draft(
            recipient="jobs@example.org",
            subject="Gmail clone risk test",
            body="Auditable draft body.",
            attachments=[attachment],
            company="测试公司",
            role="测试岗位",
            custom_risk_notes=["岗位真实风险"],
            sync_tracking=False,
        )
        cloned, _ = gmail_draft._clone_local_draft(source["draft_id"], "candidate@gmail.com")
        details = [item["detail"] for item in cloned["risk_flags"]]
        assert "岗位真实风险" in details
        assert "本次仅保存Gmail草稿，必须由用户人工决定是否发送" in details
        assert not any("已通过QQ邮箱投递" in detail for detail in details)
    finally:
        config.EMAIL_DRAFT_DIR = old_draft_dir


def test_parse_detail_html():
    """实习僧 SSR 状态赋值解析（线上审计：详情页无 <h1>，标题/公司来自 .iname=/.cname=）。"""
    from apply_bot.portals.shixiseng import parse_detail_html

    html = 'var i={};i.iname="数据分析实习生";h.industry="互联网";i.cname="Halara";'
    title, company = parse_detail_html(html)
    assert title == "数据分析实习生" and company == "Halara"
    # 带转义内容不越界
    html2 = 'i.iname="量化研究\\u5b9e\\u4e60"; i.cname="德邦基金";'
    title2, company2 = parse_detail_html(html2)
    assert title2 == "量化研究\\u5b9e\\u4e60" and company2 == "德邦基金"


def test_discover_module_imports():
    from apply_bot.discover import main  # noqa: F401
    from apply_bot.prepare_batch import prepare_all  # noqa: F401
    from apply_bot.portals.bytedance import discover_jobs  # noqa: F401
    from apply_bot.portals.xiaohongshu import discover_jobs as discover_xiaohongshu  # noqa: F401
    from apply_bot.portals.bilibili import discover_jobs as discover_bilibili  # noqa: F401
    import apply_bot.portals.zhaopin  # noqa: F401
    from apply_bot.portals.boss import discover_jobs as discover_boss  # noqa: F401


def test_dashboard_tracker_sync():
    from apply_bot.dashboard import _sync_tracker

    tmp = TMP / "dashboard_sync"
    tmp.mkdir(parents=True, exist_ok=True)
    config.TRACKER_CSV = tmp / "tracker.csv"
    _sync_tracker({
        "company": "公司C", "title": "量化实习", "portal": "tencent",
        "url": "https://jobs.example/3", "resume": "cv.pdf", "fit_rating": "high",
        "status": "interview", "deadline": "", "sector": "金融", "role_type": "intern",
    })
    with open(config.TRACKER_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["status"] == "interview" and rows[0]["channel"] == "tencent"
    assert "dashboard:interview" in rows[0]["notes"]


def test_boss_draft_is_grounded():
    from apply_bot.boss_assist import draft_message

    profile = model.load_profile()
    draft = draft_message("数据分析实习生", "需要Python SQL", profile)
    assert profile["identity"]["name"] in draft and "数据分析实习生" in draft
    assert "至少3个月" in draft
    assert "已发送" not in draft


def _run_all() -> int:
    import inspect

    funcs = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in funcs:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n=== {len(funcs) - failed} passed, {failed} failed ===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
