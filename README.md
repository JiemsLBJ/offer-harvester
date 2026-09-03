<p align="center">
  <img src="assets/logo.svg" width="140" alt="Offer Harvester logo">
</p>

<h1 align="center">Offer Harvester · offer 收割机</h1>

<p align="center">
  <i>面向中国招聘网站的 AI 求职流水线 —— 岗位发现、匹配打分、自动填表、人工确认、投递追踪。</i>
</p>

<p align="center">
  <a href="https://github.com/JiemsLBJ/offer-harvester/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/JiemsLBJ/offer-harvester/ci.yml?label=CI" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT"></a>
  <a href="https://github.com/JiemsLBJ/offer-harvester/stargazers"><img src="https://img.shields.io/github/stars/JiemsLBJ/offer-harvester?style=social" alt="Stars"></a>
  <img src="https://img.shields.io/badge/PRs-welcome-22c55e" alt="PRs welcome">
  <a href="#联系与讨论"><img src="https://img.shields.io/badge/WeChat-加我讨论-07c160" alt="WeChat"></a>
</p>

> **Agent 无关**:Claude Code / Codex / ZCode (GLM) / Gemini CLI 等任何能读取
> `AGENTS.md` 的编码代理,都可以驱动整条流水线。核心资产是工作流与站点适配器,
> 换模型 = 换引擎,车还是那辆车。

基于 [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search)(MIT)
的中国市场 fork 扩展:上游提供了「评估 → 起草 → 审稿」的求职申请框架,
本仓库在其上新增了国内招聘门户的搜索技能与**自动化投递管线**。

---

## ⚠️ 使用声明(请先读)

- 本项目仅供**个人求职**使用。自动化访问/投递可能违反目标招聘平台的服务条款,
  请自行了解并承担风险;请保持低频、克制地使用。
- **每个岗位提交前都有人工确认门**:流水线在「提交简历」一步前停止、截图留证,
  等你确认后才继续。默认永远不会自动提交任何申请。
- 不绕过、不破解任何验证码/扫码登录;不做批量群投;不伪造任何简历信息。
- 所有数据(个人档案、登录态、投递记录)只存在你本机;项目不收集、不上传任何用户数据。
- 身份证号等敏感字段不写入任何文件:仅在确认关卡由你人工输入,用后即弃。

## 功能

| 模块 | 说明 |
|------|------|
| **岗位发现** | 实习僧 / 腾讯招聘 / 德勤 Hotjob / LinkedIn / freehire 零依赖 CLI,统一 `search`/`detail` 契约,`--format json\|table\|plain` |
| **自动入库打分** | `sync_seen.ts` 去重 + fit 打分入 `seen_jobs.json`,配合 `/rank` 出候选清单 |
| **自动投递** | Playwright + 本机 Chrome 持久化登录;内置字节 / 实习僧 / 腾讯 / 牛客 / BOSS(只读辅助)五站适配器 |
| **人工确认门** | 每个岗位到「提交」前一步停下,截图留证,等你点头(`confirm.py`) |
| **投递看板** | 本地 Next.js 深色控制台:状态流转、回执、下一步提醒、表单资料缺口 |
| **表单学习** | `form_learning.py` 记录各站表单结构,越用填得越准 |
| **邮件投递** | 截图招聘帖 → 结构化 → 本地审阅页 → 确认后经 QQ/Gmail SMTP 发送 |
| **简历工场** | LaTeX / Word 模板按岗位裁剪,编译后自动检查排版与 ATS 可读性 |
| **申请全流程** | `/setup` `/scrape` `/rank` `/apply` `/interview` `/outcome` 等 14 个工作流命令 |

## 演示

**岗位发现层**——零依赖 CLI,终端即跑、无需登录(真实查询输出):

```text
$ bun run .agents/skills/tencent-search/cli/src/cli.ts search --query 数据分析 --limit 5 --format table
#   Title                               Company     Location        BG      Date        URL
1   企业微信-数据分析师                 腾讯        中国 · 广州     WXG     2026-08-04  https://careers.tencent.com/jobdesc.html?postId=2051914911923224576
2   企业微信-数据分析师                 腾讯        中国 · 广州     WXG     2026-08-04  https://careers.tencent.com/jobdesc.html?postId=2051914910073532416
3   微信小程序-数据分析师               腾讯        中国 · 广州     WXG     2026-08-27  https://careers.tencent.com/jobdesc.html?postId=2068969302056419328
4   灰境行者-游戏数据分析师             腾讯        中国 · 上海     IEG     2026-08-21  https://careers.tencent.com/jobdesc.html?postId=2088099779505733632
5   高级数据分析师-成本方向             腾讯        中国 · 深圳     TEG     2026-08-19  https://careers.tencent.com/jobdesc.html?postId=1834553761285038080

5 results (total 249, page 1)
```

**投递看板**——本地 Next.js 深色控制台(`python -m apply_bot.dashboard`,仅监听 127.0.0.1):投递管线四阶段、状态流转、面试/Offer 提醒、来源健康监控。演示动图筹备中。

**人工确认门**——流水线在每个岗位「提交」按钮前一步停下,展示截图与已填字段,由你确认后才继续。详见[架构](#架构)。

## 架构

```text
发现层  *-search CLI(公开读,无需登录)
          │  sync_seen.ts 去重 + 打分
          v
材料层  automation/profile/profile.json(表单填写唯一事实源)
          │
投递层  automation/apply_bot/(Python + Playwright + 系统 Chrome 持久化登录态)
          apply_one.py 单岗位全流程 / run_batch.py 批量队列
          portals/ 五站适配器 →【每岗位提交前人工确认】→ 回执
          │
追踪层  job_search_tracker.csv(单一事实源)+ 投递看板(仅监听 127.0.0.1)
```

## 快速开始

前置:Python 3.10+、[Bun](https://bun.sh)、Playwright(`pip install playwright`),
可选 LaTeX(MiKTeX / TeX Live)用于编译简历。

```bash
git clone https://github.com/JiemsLBJ/offer-harvester
cd offer-harvester

# 1. 安装搜索技能依赖(其余技能零依赖)
for tool in shixiseng-search tencent-search hotjob-search; do
  (cd .agents/skills/$tool/cli && bun install)
done

# 2. 填写你的档案(两处,均为本地文件,已被 .gitignore 排除)
cp automation/profile/profile.example.json automation/profile/profile.json
#    然后编辑 profile.json + CLAUDE.md + .claude/skills/job-application-assistant/01-candidate-profile.md
#    (或在编码代理里运行 /setup 引导填写)

# 3. 在你喜欢的编码代理里跑工作流
#    Claude Code / Codex / ZCode(GLM)/ Gemini CLI 均可:
/apply-auto        # 自动投递管线(带人工确认门)
```

投递看板:

```bash
cd automation/dashboard && npm install && npm run dev   # 打开 http://localhost:3000
```

## Agent 无关性

| 模块 | 依赖特定 agent? | 说明 |
|------|----------------|------|
| 岗位搜索 CLI | 否 | 独立 bun 程序,谁调都一样 |
| 投递流水线 | 否 | Python + Playwright,本地运行 |
| 投递看板 | 否 | Next.js 本地服务 |
| 工作流编排 | 弱依赖 | 任何能读 `AGENTS.md` 的代理均可;子代理 / MCP 等高级特性因 agent 而异 |
| 简历起草质量 | 取决于模型 | 同一套写作规范,不同模型执行水平有差异 |

## 常用命令

```text
/apply-auto            自动投递管线(发现→打分→填表→人工确认→回执)
/scrape /rank          搜索岗位、批量打分出候选清单
/apply <url>           单岗位完整申请(评估→定制简历→审稿→PDF)
/apply-email           截图招聘帖 → 结构化求职邮件(本地审阅后发送)
/interview /outcome    面试准备、投递结果记录与追踪
```

## 联系与讨论

使用问题、新站点适配、功能建议——欢迎开 [Issue](https://github.com/JiemsLBJ/offer-harvester/issues),或加开发者微信一起讨论:

<p align="center">
  <img src="assets/wechat-qrcode.jpg" width="200" alt="开发者微信二维码">
</p>

## 致谢

- 上游框架:[MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search)(MIT)
- 搜索 CLI 模式源自 [mikkelkrogsholm/skills](https://github.com/mikkelkrogsholm/skills)

## License

MIT(继承上游,详见 [LICENSE](LICENSE))。如果你觉得这个项目省下了你一个个
周末的投递时间,欢迎点个 Star ⭐。
