<p align="center">
  <img src="assets/logo.svg" width="144" alt="Offer Harvester logo">
</p>

<h1 align="center">Offer Harvester · Offer 收割机</h1>

<p align="center">
  <strong>面向中国招聘网站的本地优先 AI 求职流水线</strong><br>
  发现岗位、匹配排序、定制材料、浏览器填表、人工确认、持续追踪。
</p>

<p align="center">
  <a href="https://github.com/JiemsLBJ/offer-harvester/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/JiemsLBJ/offer-harvester/ci.yml?branch=main&label=core%20CI" alt="Core CI"></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776ab" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Bun-search%20CLI-f472b6" alt="Bun search CLI">
  <img src="https://img.shields.io/badge/Node.js-22.13%2B-339933" alt="Node.js 22.13+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT"></a>
  <a href="https://github.com/JiemsLBJ/offer-harvester/stargazers"><img src="https://img.shields.io/github/stars/JiemsLBJ/offer-harvester?style=social" alt="GitHub stars"></a>
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="#能力与边界">能力与边界</a> ·
  <a href="#安全与隐私">安全与隐私</a> ·
  <a href="#命令速查">命令速查</a> ·
  <a href="#参与贡献">参与贡献</a>
</p>

> [!NOTE]
> Offer Harvester 不是“一键海投器”。它把搜索、整理、材料生成和重复填表自动化，
> 但把事实核对、验证码处理和最终提交决定留给求职者。

基于 [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search)
的求职申请框架，本项目针对中国招聘市场补充了招聘站点搜索 CLI、浏览器表单适配器、
邮件草稿、人工确认门和本地进度看板。Claude Code、Codex、ZCode / GLM、
Gemini CLI 等能够读取 <code>AGENTS.md</code> 的编码代理均可驱动这些工作流；
搜索与投递核心也可以直接通过 Bun / Python 命令运行。

> [!IMPORTANT]
> 如果你要填写真实姓名、电话、邮箱、学校、简历或登录招聘网站，请使用**私有仓库或仅本地副本**。
> <code>/setup</code> 不只生成被忽略的 <code>profile.json</code>，还会个性化仓库中若干受 Git
> 跟踪的配置和简历文件。不要把完成个性化后的分支推送到公开 GitHub 仓库。

## 为什么做这个项目

求职真正耗时的部分，往往不是点一次“投递”，而是反复完成下面这些小任务：

| 常见痛点 | Offer Harvester 的处理方式 |
|---|---|
| 多个平台重复搜索，结果格式不一致 | 将多个站点包装为统一的 <code>search</code> / <code>detail</code> CLI |
| 岗位很多，但不知道先看哪一个 | 去重、记录来源，并按候选人事实与岗位要求做匹配排序 |
| 每个岗位都要重写材料 | 基于同一事实源定制简历、求职信、邮件和面试准备 |
| 表单字段重复、页面经常变化 | Playwright 复用本机 Chrome 登录态；不确定时安全停止 |
| 自动化容易误投或填错 | 填写后进入审核；专用投递路径在最终提交前要求逐岗位确认 |
| 投完之后没有记录 | 统一追踪状态、回执、联系人、下一步日期和结果 |

这个项目的目标不是“投得最多”，而是让你用更少的重复劳动完成**可核对、可撤回、可追踪**
的高质量申请。

## 30 秒了解工作流

~~~mermaid
flowchart LR
    A["公开岗位来源<br>Search CLI / 浏览器发现"] --> B["去重与匹配<br>sync + rank"]
    B --> C["岗位评估<br>值得投吗？"]
    C --> D["定制材料<br>简历 / 求职信 / 邮件"]
    D --> E["浏览器填表<br>复用系统 Chrome"]
    E --> F{"人工审核与确认"}
    F -- "确认提交" --> G["站点提交 / 邮件发送"]
    F -- "暂不提交" --> H["保留草稿或退出"]
    G --> I["回执与进度<br>SQLite / CSV / Dashboard"]
    I --> J["面试准备与结果追踪"]
~~~

贯穿全流程的规则只有几条：**不猜事实、不绕验证、不静默提交、失败要留下可读原因。**

## 能力与边界

### 功能全景

| 模块 | 当前能力 | 主要入口 |
|---|---|---|
| 岗位发现 | 实习僧、腾讯招聘、Hotjob、LinkedIn、FreeHire 的独立搜索技能 | <code>.agents/skills/*-search</code> |
| 聚合与排序 | 岗位去重、来源同步、fit 评分、候选清单 | <code>sync_seen.ts</code>、<code>/rank</code> |
| 申请评估 | JD 分析、事实差距、申请建议、风险说明 | <code>/apply</code> |
| 材料定制 | 定向简历、求职信、邮件正文、面试准备 | <code>/apply</code>、<code>/interview</code> |
| 浏览器填表 | Playwright + 系统 Chrome 持久化登录态 | <code>apply_one</code>、<code>run_batch</code> |
| 人工确认 | 最终提交前展示目标岗位、已填字段与截图 | <code>confirm.py</code> |
| 邮件申请 | 招聘图片结构化、本地 EML / HTML 审核、单封确认发送 | <code>/apply-email</code> |
| 进度追踪 | SQLite / CSV、状态流转、提醒、来源健康 | 本地 Dashboard |
| 表单学习 | 保存非敏感字段结构和资料缺口，辅助后续填写 | <code>form_learning.py</code> |
| 扩展开发 | 新增站点适配器或简历模板 | <code>/add-portal</code>、<code>/add-template</code> |

### 站点支持不是一个简单的“支持 / 不支持”

招聘网站会改版、登录会过期、岗位可能跳到第三方页面，同一平台不同岗位也可能使用不同表单。
因此这里按自动化深度说明能力，而不是承诺“所有岗位都能自动投”。

| 层级 | 平台 / 入口 | 能做什么 | 明确边界 |
|---|---|---|---|
| 公开搜索 | 腾讯招聘、实习僧、Hotjob、FreeHire | 搜索、详情、结构化输出 | 数据和接口随平台变化 |
| 受限搜索 | LinkedIn | 尝试读取公开岗位 | 某些网络环境会返回 451 或触发限制 |
| 专用表单路径 | 字节跳动、腾讯、实习僧、小红书、哔哩哔哩、智联招聘、Hotjob | 识别页面、上传材料、填写并进入确认流程 | 需要真实登录；页面变化或验证会安全停止 |
| 只读 / 辅助 | BOSS 直聘、牛客 | 读取当前页面、整理信息、辅助填写 | 不自动打招呼，不自动完成最终投递 |
| 通用表单 | 其他已知官方申请页 | 探测字段、<code>fill-only</code>、人工审阅 | 不自动上传未知附件，不自动提交 |

详细的实时状态、已验证入口与站点限制见
[automation/README.md](automation/README.md)。站点适配器“存在”不等于某个具体岗位“当前可投”；
请先使用 <code>--probe</code> 或 <code>--fill-only --review</code>。

## 快速开始

### 1. 准备运行环境

| 工具 | 版本 / 用途 | 是否必需 |
|---|---|---|
| Git | 获取代码和管理本地修改 | 必需 |
| [Python](https://www.python.org/downloads/) | 3.10+；投递管线、邮件草稿、测试 | 必需 |
| [Google Chrome](https://www.google.com/chrome/) | Playwright 复用系统浏览器与登录态 | 使用浏览器填表时必需 |
| [Bun](https://bun.sh/) | 运行 TypeScript 岗位搜索 CLI | 使用搜索技能时必需 |
| [Node.js](https://nodejs.org/) + npm | 22.13+；本地 Dashboard | 使用看板时必需 |
| LaTeX / Word 工具链 | 编译或检查部分简历模板 | 按模板可选 |
| GitHub CLI <code>gh</code> | 一条命令创建私有工作仓库 | 可选 |

项目复用系统安装的 Google Chrome，不要求额外下载 Playwright Chromium。

### 2. 选择公开试用还是私有工作区

只想阅读代码、运行无个人信息的搜索命令：

~~~bash
git clone https://github.com/JiemsLBJ/offer-harvester.git
cd offer-harvester
~~~

要录入真实资料并长期使用，推荐把公开仓库保留为 <code>upstream</code>，再创建自己的私有仓库：

~~~bash
git clone https://github.com/JiemsLBJ/offer-harvester.git offer-harvester-workspace
cd offer-harvester-workspace
git remote rename origin upstream

# 将 YOUR_GITHUB_USER 替换为你的 GitHub 用户名
gh repo create YOUR_GITHUB_USER/offer-harvester-workspace --private --source=. --remote=origin --push
~~~

没有安装 <code>gh</code> 时，可以在 GitHub 网页新建一个空的 Private repository，再把它添加为
<code>origin</code>。不要把个性化后的工作区 fork 成公开仓库。

### 3. 安装 Python 投递依赖

Windows PowerShell：

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r automation/apply_bot/requirements.txt
~~~

Linux / macOS shell：

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r automation/apply_bot/requirements.txt
~~~

### 4. 安装搜索 CLI 依赖

Windows PowerShell：

~~~powershell
$skills = @(
  "shixiseng-search",
  "tencent-search",
  "hotjob-search",
  "linkedin-search",
  "freehire-search"
)

foreach ($skill in $skills) {
  Push-Location ".agents/skills/$skill/cli"
  bun install
  Pop-Location
}
~~~

Linux / macOS shell：

~~~bash
for tool in shixiseng-search tencent-search hotjob-search linkedin-search freehire-search
do
  (cd ".agents/skills/$tool/cli" && bun install)
done
~~~

### 5. 建立事实档案

如果只想直接测试 Python 管线，可以先复制本地档案模板：

~~~powershell
Copy-Item automation/profile/profile.example.json automation/profile/profile.json
~~~

~~~bash
cp automation/profile/profile.example.json automation/profile/profile.json
~~~

随后编辑 <code>automation/profile/profile.json</code>，只填写真实、愿意用于申请的内容。
字段说明见 [automation/profile/README.md](automation/profile/README.md)。

如果希望由编码代理引导完成完整个性化：

- Claude Code：运行 <code>/setup</code>。
- Codex、ZCode / GLM、Gemini CLI：让代理先完整阅读 <code>AGENTS.md</code> 和
  <code>.claude/commands/setup.md</code>，再执行 setup 工作流。

可以直接使用这句话：

> 请先完整阅读 AGENTS.md 和 .claude/commands/setup.md，然后执行 setup。
> 只使用我确认的事实，不要猜测；开始前先提醒我检查当前仓库是否为私有仓库。

> [!CAUTION]
> 不要把身份证号写入提示词、档案、日志或 Issue。需要站点临时填写时，只能在当次人工确认环节手动输入。

### 6. 先跑一个不会提交的最小验证

先测试无需登录的腾讯岗位搜索：

~~~bash
bun run .agents/skills/tencent-search/cli/src/cli.ts search -q "数据分析" -l 上海 --limit 5 --format table
~~~

再检查投递环境：

~~~bash
cd automation
python -m apply_bot.apply_one --selfcheck
~~~

对一个你已确认属于官方招聘域名的 URL 做只读探测：

~~~bash
python -m apply_bot.apply_one "https://官方招聘页面.example/job/123" --probe
~~~

需要试填但绝不提交时：

~~~bash
python -m apply_bot.apply_one "https://官方招聘页面.example/job/123" --fill-only --review
~~~

把示例 URL 替换为真实官方岗位页。运行前检查浏览器地址栏、公司名称、岗位名称和附件，
验证或域名不一致时立即停止。

## 三条常用使用路径

### 路径 A：让 Agent 编排完整流程

适合希望从搜索开始、逐步审核的人：

~~~text
/scrape
  → /rank
  → /apply <岗位 URL>
  → 人工检查定制材料
  → /apply-auto 或浏览器 fill-only
  → 逐岗位确认
  → /interview
  → /outcome
~~~

不同 Agent 对 slash command 的支持不完全相同。没有 slash command 时，直接说：

> 阅读 AGENTS.md 和对应的 .claude 工作流规范，搜索上海的数据分析实习；
> 先给我去重、排序后的候选清单，不要填写或提交任何申请。

### 路径 B：直接运行单岗位浏览器管线

~~~bash
cd automation

# 只检查环境
python -m apply_bot.apply_one --selfcheck

# 只探测页面，不填写
python -m apply_bot.apply_one "JOB_URL" --probe

# 填写并保留页面供人工检查，绝不提交
python -m apply_bot.apply_one "JOB_URL" --fill-only --review

# 不熟悉的网站：明确使用通用适配器，仍然只填不投
python -m apply_bot.apply_one "FORM_URL" --portal generic --fill-only --review

# 队列预览，不启动浏览器投递
python -m apply_bot.run_batch --dry-run
~~~

普通专用适配器流程会在最终提交前进入确认门；验证码、扫码登录或风控出现时交给用户处理。
批量入口也应保持低频，并先用 <code>--dry-run</code> 检查目标列表。

### 路径 C：从招聘图片生成可审核邮件草稿

适合小红书、微信群、朋友圈或海报中的邮箱岗位：

1. 提取公司、岗位、收件邮箱、主题规则和截止日期；
2. 逐字符核对邮箱，不清楚就停在草稿；
3. 按岗位要求定制并核验附件；
4. 生成本地 <code>message.eml</code>、<code>manifest.json</code> 和 <code>review.html</code>；
5. 每封邮件单独确认后，才允许使用配置好的发送通道。

示例只创建草稿，不发送：

~~~powershell
cd automation
python -m apply_bot.email_apply prepare --recipient "jobs@example.com" --subject "按招聘方要求填写的主题" --body-file "body.txt" --attachment "resume.pdf" --company "示例公司" --role "示例岗位" --source-image "posting.jpg"
~~~

完整规则见 <code>.claude/commands/apply-email.md</code>。

## 输出长什么样

岗位搜索 CLI 统一支持 <code>json</code>、<code>table</code>、<code>plain</code> 等输出格式，
便于人读、脚本消费或交给 Agent 继续分析。下面是腾讯搜索技能的表格输出示例；
岗位内容和数量会随线上数据变化：

~~~text
#  Title                     Company  Location     BG   Date        URL
1  企业微信-数据分析师       腾讯     中国 · 广州  WXG  2026-08-04  https://careers.tencent.com/...
2  微信小程序-数据分析师     腾讯     中国 · 广州  WXG  2026-08-27  https://careers.tencent.com/...
3  游戏数据分析师            腾讯     中国 · 上海  IEG  2026-08-21  https://careers.tencent.com/...

3 results
~~~

JSON 输出可以进入去重、评分和追踪流程；Plain 输出适合快速复制到对话或笔记中。

## 本地进度看板

看板将申请记录、状态流转、最近活动、渠道分布、下一步日期、资料缺口和来源健康集中在一个界面。

首次使用先安装前端依赖：

~~~powershell
Push-Location automation/dashboard
npm install
Pop-Location
~~~

然后从 <code>automation</code> 目录启动前端和本地 API：

~~~powershell
cd automation
python -m apply_bot.dashboard
~~~

- 页面：<http://127.0.0.1:4173/>
- 本地 API：<http://127.0.0.1:8765/api/dashboard>
- 按 <code>Ctrl+C</code> 同时停止两项服务

只需要 API 时：

~~~bash
cd automation
python -m apply_bot.dashboard --api-only
~~~

> [!WARNING]
> 当前 Dashboard 面向单机可信环境，不提供账号登录。不要端口转发、反向代理或暴露到局域网 / 公网。
> 更详细的运行方式见 [automation/dashboard/README.md](automation/dashboard/README.md)。

## 安全与隐私

### 数据究竟在哪里

“本地优先”不等于“申请时永不联网”。搜索会访问招聘来源；只有在你决定申请时，
姓名、联系方式、简历等必要资料才会被填入你选择的招聘网站或邮件通道。

| 数据 | 默认处理 |
|---|---|
| <code>automation/profile/profile.json</code> | 本地事实源，已被 <code>.gitignore</code> 排除 |
| Chrome 登录态与自动化状态 | 本地状态目录，已被 <code>.gitignore</code> 排除 |
| 求职追踪 CSV、岗位去重缓存 | 本地生成，已被 <code>.gitignore</code> 排除 |
| 邮件草稿与审核材料 | 本地状态目录；只有明确确认后才发送 |
| 个性化工作流配置与简历源码 | 部分文件受 Git 跟踪，必须在私有工作区保存 |
| 招聘网站收到的申请资料 | 由对应招聘方和平台处理，不再只存在本机 |

### 不可协商的安全规则

1. **逐岗位确认**：专用提交路径在点击最终提交前必须停下，展示目标、字段和截图。
2. **不保存身份证号**：不得进入仓库、档案、日志、追踪表或截图。
3. **不绕过验证**：验证码、扫码登录、短信、风控都由用户本人处理。
4. **遵守平台规则**：仅用于个人求职，了解目标站点条款，保持低频，不做批量群投。
5. **不伪造事实**：材料与表单必须来自已确认的候选人事实源。
6. **先验证 URL**：只对已核对的官方招聘域名运行；上传简历前再次检查浏览器地址栏。
7. **看板不对外暴露**：本地 API 当前无用户认证，不应监听或转发到外部网络。

如果你发现可能导致资料外传、绕过确认或错误提交的问题，请不要在公开 Issue 中附带真实个人数据、
Cookie、令牌或完整截图；按照 [SECURITY.md](SECURITY.md) 的渠道报告。

### 公开仓库用户最容易忽略的风险

下面这些内容可能被 setup 流程个性化，而且属于 Git 跟踪范围：

- <code>CLAUDE.md</code>；
- <code>.claude/skills/job-application-assistant/</code> 下的候选人资料；
- <code>.claude/skills/job-scraper/search-queries.md</code>；
- <code>cv/</code> 中个性化后的简历源码与生成物。

因此，<code>git status</code> 没有出现 <code>profile.json</code>，并不代表整个仓库已经适合公开。
推送前至少运行：

~~~bash
git status --short
git diff --cached
git ls-files
~~~

逐项检查姓名、手机号、邮箱、学校、地址、Cookie、令牌和真实附件名。

## Agent 兼容性

| 组件 | 是否依赖特定 Agent | 说明 |
|---|---|---|
| 岗位搜索 CLI | 否 | 独立 Bun 程序，可由人或任何 Agent 调用 |
| 浏览器投递管线 | 否 | Python + Playwright，本地运行 |
| 本地 Dashboard | 否 | Node.js 前端 + Python API |
| 工作流规范 | 弱依赖 | 权威规范在 <code>.claude/commands</code>、<code>.claude/skills</code> 和 <code>AGENTS.md</code> |
| Slash command | 取决于 Agent | 不支持 slash command 时改用自然语言并要求读取对应规范 |
| 材料起草质量 | 取决于模型 | 同一事实和规则，不同模型的分析与写作质量会不同 |

项目采用“薄指针”设计：<code>AGENTS.md</code> 告诉 Agent 去哪里读取权威工作流，
核心代码不要求绑定某一家模型服务。

## 命令速查

### Agent 工作流

| 命令 / 触发词 | 用途 | 默认会提交吗 |
|---|---|---|
| <code>/setup</code> | 建立候选人档案、偏好和搜索配置 | 否 |
| <code>/scrape</code> | 调用搜索技能发现岗位 | 否 |
| <code>/rank</code> | 对候选岗位去重、打分和排序 | 否 |
| <code>/apply &lt;url&gt;</code> | 评估岗位并定制定向材料 | 否 |
| <code>/apply-auto</code> | 进入浏览器投递流水线 | 最终提交前必须确认 |
| <code>/apply-email</code> | 从招聘图片准备单封邮件申请 | 先生成草稿；发送前必须确认 |
| <code>/interview</code> | 生成岗位相关的面试准备 | 否 |
| <code>/outcome</code> | 记录投递、面试、Offer 或拒信结果 | 否 |
| <code>/html-report</code> | 生成本地求职报告 | 否 |
| <code>/add-portal</code> | 按契约新增招聘站点适配器 | 否 |
| <code>/add-template</code> | 新增并验证简历模板 | 否 |

执行任何工作流前，请以对应规范文件为准，不要只凭 README 猜测参数。

### Python 投递管线

~~~bash
cd automation

python -m apply_bot.apply_one --selfcheck
python -m apply_bot.apply_one "JOB_URL" --probe
python -m apply_bot.apply_one "JOB_URL" --fill-only --review
python -m apply_bot.run_batch --dry-run
python -m apply_bot.run_batch --limit 3
python -m apply_bot.dashboard
~~~

### 搜索 CLI

~~~bash
# 腾讯招聘
bun run .agents/skills/tencent-search/cli/src/cli.ts search -q "实习" -l 上海 --format table

# 实习僧
bun run .agents/skills/shixiseng-search/cli/src/cli.ts search -q "数据分析" -l 上海 --format table

# 每个技能的参数和限制见各自 SKILL.md
~~~

## 项目结构

~~~text
offer-harvester/
├─ AGENTS.md                         Agent 接入、工作顺序与安全红线
├─ SECURITY.md                       漏洞报告范围与渠道
├─ .claude/
│  ├─ commands/                      14 个工作流的权威规范
│  └─ skills/                        申请评估、岗位搜索、技能差距分析
├─ .agents/skills/
│  ├─ *-search/                      可移植招聘站点搜索 CLI
│  ├─ job-form-filler/               表单填写技能入口
│  └─ image-email-application/       图片招聘帖邮件申请入口
├─ automation/
│  ├─ apply_bot/
│  │  ├─ portals/                    站点适配器与通用安全适配器
│  │  ├─ tests/                      无浏览器核心回归测试
│  │  ├─ apply_one.py                单岗位入口
│  │  ├─ run_batch.py                低频队列入口
│  │  ├─ confirm.py                  最终提交确认关卡
│  │  └─ email_apply.py              邮件草稿与确认发送
│  ├─ dashboard/                     本地进度看板
│  ├─ profile/                       事实档案模板与说明
│  ├─ sync_seen.ts                   岗位同步、去重和评分
│  └─ README.md                      自动化层详细操作手册
├─ cv/                               简历源码与模板
├─ assets/                           Logo 等公开资源
└─ tests/                            仓库级保护测试
~~~

## 开发与验证

修改 <code>automation/apply_bot</code> 后，至少运行：

~~~bash
python automation/apply_bot/tests/test_core.py
python tests/test_cv_identity_guard.py
python -m compileall automation -q
~~~

当前 GitHub Actions 只执行无浏览器核心回归、简历模板身份保护和 Python 语法检查；
它不会自动访问真实招聘网站。真实站点冒烟测试必须在本地、低频、无敏感日志的条件下按需进行。

新增站点时：

1. 先阅读 <code>.claude/commands/add-portal.md</code>；
2. 区分搜索、探测、填写、上传、提交五种能力；
3. 对未知页面默认安全停止；
4. 保留最终人工确认门；
5. 添加无浏览器单元测试和失败说明；
6. 不在测试夹具中提交真实姓名、电话、邮箱、Cookie 或简历。

## 常见问题

<details>
<summary><strong>它能完全自动投递吗？</strong></summary>

不能，也不应该。项目可以搜索、评估、生成材料和填写表单，但专用投递路径在最终提交前必须由用户确认。
BOSS、牛客和通用适配器的自动化边界更严格。
</details>

<details>
<summary><strong>为什么有适配器，某个岗位还是不能投？</strong></summary>

同一平台可能存在不同招聘系统，岗位也可能下线、跳转、要求扫码或触发风控。
适配器遇到未知页面应停止并报告，而不是猜按钮或绕过验证。
</details>

<details>
<summary><strong>公开 fork 后再填写个人资料安全吗？</strong></summary>

不安全。即使 <code>profile.json</code> 被忽略，setup 仍可能修改受 Git 跟踪的资料和简历文件。
请把个人工作区放在私有仓库或只保存在本机。
</details>

<details>
<summary><strong>能在 Linux 或 macOS 上运行吗？</strong></summary>

搜索 CLI 和无浏览器 Python 测试具备跨平台基础；浏览器适配器主要围绕系统 Chrome 开发，
不同平台的登录态路径和页面行为可能不同。Windows 是当前主要验证环境，其他系统请先跑
<code>--selfcheck</code> 和 <code>--probe</code>。
</details>

<details>
<summary><strong>遇到验证码、扫码登录或短信验证怎么办？</strong></summary>

暂停自动化，由用户本人在浏览器中完成。项目不提供绕过方法，也不应把验证码或会话令牌写入日志。
</details>

<details>
<summary><strong>陌生公司的自建表单怎么处理？</strong></summary>

先核对域名和公司主体，再使用通用适配器的 <code>--fill-only --review</code>。
它只用于辅助填写和人工检查，不自动处理未知附件或最终提交。
</details>

<details>
<summary><strong>如何更新上游代码？</strong></summary>

如果按快速开始把公开仓库命名为 <code>upstream</code>，可以先运行
<code>git fetch upstream</code>，审阅差异后再合并 <code>upstream/main</code>。
个性化文件可能冲突，合并前请备份私有资料并检查 Git diff。
</details>

## 路线图

当前优先方向：

- 强化站点 URL / 来源校验、任意档案目录约束和 CSV 导出安全；
- 为本地 Dashboard 增加 Host 校验与可选认证；
- 将“公开模板”和“私有个人工作区”的边界做得更显式；
- 扩充站点健康检查、页面变化回归样本和可复现的演示；
- 增加跨平台验证和更完整的隐私保护测试；
- 补齐第三方字体与资源的许可证清单；
- 改进文档导航、版本发布说明和贡献者上手体验。

路线图不承诺具体日期。页面适配的稳定性、安全边界和隐私保护优先于新增“自动提交”数量。

## 参与贡献

欢迎提交 Issue、文档改进和 Pull Request，尤其欢迎：

- 新招聘来源的公开搜索适配；
- 已有站点改版后的字段修复；
- 无浏览器测试、失败样本和跨平台兼容；
- 隐私、安全、可访问性和文档改进；
- 不依赖虚构经历的简历与面试工作流优化。

提交问题时请说明平台、入口 URL 的公开部分、预期行为、实际错误和运行环境。
请先清理截图与日志，绝不要公开真实简历、手机号、邮箱、Cookie、验证码、授权码或内部岗位链接。

开始编码前先阅读 [AGENTS.md](AGENTS.md) 和相关工作流规范。修改自动化代码后运行
[开发与验证](#开发与验证) 中的检查。

## 致谢

- 上游求职申请框架：
  [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search)（MIT）
- 可移植搜索 CLI 的技能组织方式参考：
  [mikkelkrogsholm/skills](https://github.com/mikkelkrogsholm/skills)

## 联系与讨论

使用问题、新站点适配和功能建议，欢迎开
[GitHub Issue](https://github.com/JiemsLBJ/offer-harvester/issues)。
也可以扫描下方二维码联系维护者；添加时请注明 <code>Offer Harvester</code>，不要通过微信发送账号密码、
Cookie、验证码、身份证号或未脱敏简历。

<p align="center">
  <img src="assets/wechat-qrcode.jpg" width="200" alt="开发者微信二维码">
</p>

## License

项目代码采用 [MIT License](LICENSE)。第三方依赖和资源仍遵循各自许可证。

如果这个项目帮你把重复劳动变成了可控流程，欢迎 Star ⭐；如果它哪里说得不清楚，
一个具体的 Issue 会比沉默更有帮助。
