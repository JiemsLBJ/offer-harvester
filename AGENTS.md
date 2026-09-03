# Agent Guidelines: Offer Harvester

本仓库是面向中国招聘网站的 AI 求职流水线。任何编码代理(Claude Code、Codex、
ZCode/GLM、Gemini CLI 等)按本文件接入:先读结构,再守红线,然后按用户指令
调用对应工作流。

## 目录结构(薄指针设计)

- **`.claude/commands/`** —— 全部工作流的权威规范:`/setup` `/scrape` `/rank`
  `/apply` `/apply-auto` `/apply-email` `/interview` `/outcome` `/html-report` 等。
  执行任何工作流前,先读对应命令文件,不要凭记忆自由发挥。
- **`.claude/skills/`** —— 核心技能:`job-application-assistant`(评估/简历/求职信/
  面试框架)、`job-scraper`(搜索编排)、`upskill`(技能差距分析)。
- **`.agents/skills/`** —— 门户搜索 CLI(可移植 Agent Skills 格式,每个目录一个
  `SKILL.md` + 零依赖 bun CLI):`shixiseng-search` `tencent-search` `hotjob-search`
  `linkedin-search` `freehire-search` `job-form-filler` `image-email-application` 等。
  `/scrape` 自动发现遵循契约的技能,无需注册。
- **`automation/`** —— 自动投递管线。**动手前先读 `automation/README.md`**:
  - 事实源:`automation/profile/profile.json`(结构化档案,从
    `profile.example.json` 复制后填写)与 `job_search_tracker.csv`(追踪表)。
  - 代码:`apply_bot/`(Playwright + 系统 Chrome 持久化登录态;`portals/` 为
    bytedance / shixiseng / tencent / nowcoder / boss 五站适配器)、
    `dashboard/`(本地投递看板)。
  - 回归测试:`python automation/apply_bot/tests/test_core.py`(无浏览器,改动
    apply_bot 后必须跑)。

## 安全红线(不可协商)

1. **每个岗位提交前必须人工确认**:流水线在「提交」一步前停止,展示截图与
   回执,等用户明确确认。不得移除或绕过 `confirm.py` 的确认关卡。
2. **身份证号不落盘**:不写入任何文件、日志、追踪表;仅在确认关卡用户明确
   授权该次填写时由人工输入,用后即弃。
3. **不绕过验证码 / 扫码登录 / 风控**;遇到验证阻塞明确报告并交人工处理。
4. **不批量群投**:批量队列保持低频,尊重目标站点。
5. **不伪造简历信息**:所有提交内容必须与 profile.json 事实源一致。
6. 个人数据(`profile.json`、登录态、`state/`、tracker)已被 `.gitignore`
   排除,永远不要提交或外传。

## 开工顺序建议

新用户:先跑 `.claude/commands/setup.md`(`/setup`)建立个人档案 →
`/scrape` 搜索 → `/rank` 打分 → `/apply-auto` 或 `/apply` 投递。
改动代码:先读 `automation/README.md`,改完跑 `test_core.py`。
