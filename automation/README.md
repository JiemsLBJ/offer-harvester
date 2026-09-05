# 全自动求职流水线（中国站点版）

`automation/` 把 ai-job-search 工作区的求职流程扩展为：**抓取/图片识别 → 评估 → 定向材料 → 网页填表或邮件草稿 → 人工审核 → 确认提交 → 追踪** 的完整流水线。抓取/评估/材料复用仓库既有工作流（`/scrape`、`/rank`、`/apply`），本目录新增**中国站点抓取 CLI**、**Playwright 投递自动化**与安全邮件草稿通道。

```
┌─ 发现层（无登录，公开读）───────────────────────────────────┐
│  .agents/skills/tencent-search   腾讯招聘公开 JSON API ✓ 实测  │
│  .agents/skills/shixiseng-search 实习僧 Nuxt SSR 页面 ✓ 实测    │
│  .agents/skills/freehire-search  FreeHire 聚合 API ✓ 实测       │
│  .agents/skills/linkedin-search  LinkedIn 公开职位页（低频）     │
│  （/scrape 自动发现并调用；写入 job_scraper/seen_jobs.json 去重）│
│  小红书/B站：官方招聘接口；字节：浏览器会话渲染抓取              │
│  BOSS：只读当前页（不翻页、不绕风控）→ 入库后交 /rank             │
└────────────────────────────────────────────────────────────┘
        ↓
┌─ 评估层（既有）─────────────────────────────────────────────┐
│  /rank 打分排序 → 高匹配岗位清单                              │
└────────────────────────────────────────────────────────────┘
        ↓
┌─ 材料层（既有 + 新增）──────────────────────────────────────┐
│  /apply → CV PDF + 求职信（LaTeX，默认1页/1页，ATS 校验）     │
│  automation/profile/profile.json 结构化档案（表单填写唯一事实源）│
├────────────────────────────────────────────────────────────┤
│  apply_bot（Python + Playwright + channel=chrome）            │
│  ├─ 持久化登录态：专用 Chrome profile，扫码登录一次长期复用      │
│  ├─ 适配器：bytedance / shixiseng / tencent / xiaohongshu /  │
│  │   bilibili / zhaopin / hotjob / nowcoder(半自动) /         │
│  │   boss(只读辅助) / generic（未知官网仅填不提交）            │
│  ├─ 上传 → 解析回填 → 补填 → 校验 → 【每岗位提交前人工确认】     │
│  ├─ 回执采集 → state/apply_log.json → job_search_tracker.csv  │
│  ├─ 表单学习 → 字段要求/资料缺口 → 补齐后跨次复用               │
│  └─ 本机控制台 → 状态管线/面试/Offer/下一步/可视化               │
└────────────────────────────────────────────────────────────┘
```

## 快速开始

```bash
# 1. 安装依赖（Python 3.10+，复用系统 Chrome，无需下载 Chromium）
pip install -r automation/apply_bot/requirements.txt

# 2. 环境自检（不启动浏览器）
cd automation && python -m apply_bot.apply_one --selfcheck

# 3. 单岗位投递（第一次会弹 Chrome，在窗口里扫码登录一次，之后复用）
python -m apply_bot.apply_one "https://careers.tencent.com/jobdesc.html?postId=..."

# 4. 批量队列（从 seen_jobs.json 按 fit=high 取，逐个处理，逐个确认）
python -m apply_bot.run_batch --dry-run            # 先看队列
python -m apply_bot.run_batch --limit 3            # 实际跑前 3 个

# 5. 站点首次探路（只打开页面输出表单快照，不填写不提交）
python -m apply_bot.apply_one <url> --probe

# 6. 填写后在浏览器中人工复核；命令结束后 Chrome 仍保留（仍不提交）
python -m apply_bot.apply_one <url> --fill-only --review

# 6a. 完整队列：单一独立 Chrome、多标签页全部填完并保留（仍不提交）
python -m apply_bot.run_batch --from queue --queue <queue.json> --fill-only --retain-all --require-tailored-cv

# 6b. 未知官网：必须给“申请表直达 URL”，只填普通字段；仅明确简历控件可上传，绝不提交
python -m apply_bot.apply_one <form-url> --portal generic --fill-only --review

# 7. 打开本机求职进度与表单学习控制台
python -m apply_bot.dashboard

# 8. 图片/帖子岗位：只生成可审核邮件草稿，不发送
python -m apply_bot.email_apply prepare --recipient "jobs@example.com" --subject "..." `
  --body-file "body.txt" --attachment "resume.pdf" --company "公司" --role "岗位" `
  --source-image "posting.jpg"
```

## 求职进度中心

控制台位于 `automation/dashboard/`，默认地址 `http://127.0.0.1:4173/`。它把
`apply_log.json`、`job_search_tracker.csv` 和新建的 SQLite 状态库统一为一个可编辑界面：

- 总览投递数量、推进中、面试、Offer、最近活动与渠道分布；
- 按“准备中 / 已投递 / 面试 / 结果”推进岗位，并维护下一步日期、联系人和标签；
- 每次填表自动学习字段静态结构，把缺失资料放进待办队列；
- 用户补齐的事实写入 gitignored 补充档案，之后由机器人自动合并和回填；
- “来源监控”列出主要入口、抓取层级、最近运行、岗位数量和具体错误；
- 图片/帖子来源的邮件岗位在草稿生成时以 `email / drafted` 入库，服务器明确接受后才变为 `applied`；
- 网页状态更新同步回 tracker，但不会触发第三方网站提交或发送消息。

详细说明见 `automation/dashboard/README.md`。服务仅绑定本机回环地址，不发布个人数据。

## 站点状态矩阵

| 站点 | 抓取 | 投递 | 说明 |
|---|---|---|---|
| LinkedIn Jobs | 🟡 CLI 已接通 | 通用/人工 | 当前网络区域实测返回 HTTP 451 时会记为失败，不伪报空结果 |
| FreeHire | ✅ 聚合公开 API | 通用/人工 | 已实测返回上海数据分析岗位；日常仅取精简卡片 |
| 腾讯招聘 careers.tencent.com | ✅ 公开 API（tencent-search CLI） | ✅ 真机完成上传与填写；提交仍需 `y` | `--fill-only` 有截图证据；校验项需人工补完 |
| 德勤 Hotjob/Wecruit | ✅ 官网公开接口（hotjob-search CLI） | 🟡 专用适配器已建，待首次登录态表单探路 | 精确岗位 URL、职责/要求/截止日已实测；旧版 Hotjob 站点不冒充兼容 |
| 实习僧 shixiseng.com | ✅ SSR 页面（shixiseng-search CLI） | 🟡 适配器已建，需首次探路 | 登录墙/VIP 限制会明确报告，不绕过 |
| 字节跳动校园 jobs.bytedance.com | 🟡 浏览器渲染（`apply_bot.discover`，API 已失效） | ✅ 适配器按 2026-08-21 实测流程固化 | 昨晚已验证到「提交简历」前 |
| 小红书招聘 job.xiaohongshu.com | ✅ 官方接口/浏览器发现 | ✅ 真机完成上传与填写；提交仍需 `y` | 未确认生日会清空并列为人工校验项 |
| 哔哩哔哩招聘 jobs.bilibili.com | 🟡 官方接口可访问，当前 `total=0` | 🟡 适配器与双确认提交路径已建 | 社会招聘入口已硬拒绝，不再混入实习结果；0 条会记录为警告 |
| 智联招聘 zhaopin.com | 🟡 用户提供单岗位 URL | 🟡 安全的一键投递适配器已建 | `立即投递` 可能直接提交；确认前只去简历中心准备材料 |
| 牛客网 nowcoder.com | 🟡 登录+JS 渲染，浏览器会话内浏览 | ⛔ 不自动投递（常跳企业官网） | 转用对应企业适配器 |
| BOSS直聘 zhipin.com | 🟡 用户给列表页后只读当前页 | ⛔ 不自动打招呼/发简历 | 可入库 `/rank`；`boss_assist` 仅生成本地、可核对的话术草稿 |
| 小红书/微信群招聘图片 | 用户提供图片并结构化 | 🟡 本地 `.eml` 草稿；QQ SMTP 单封确认发送 | 匿名公司、个人邮箱、纯图片来源自动标风险；不群发 |

## 安全与确认关卡（不可关闭）

1. **填完再审核**：用户确认岗位队列后，流水线直接生成并上传该岗位绑定的定向简历、
   自动填写已确认字段，然后通过 `--fill-only --review` 停在浏览器供人工检查；不再要求
   上传前重复确认同一份材料。该授权只覆盖上传与填写，不覆盖提交。
2. **每岗位提交前人工确认**：自动化只负责填表；最终点击「提交/投递」前必须看见
   「将提交什么、发给谁、包含哪些信息」清单并输入 `y`。
3. **证件号等敏感字段**：不写入任何文件/日志/追踪表（`profile.json` 中
   `identity.id_card.value` 恒为 `null`）；仅当确认关卡明确授权时人工输入一次。
4. **验证码/扫码/短信验证码**：由用户完成，所有适配器不做绕过。
5. **投递前防错位校验**：`--expect-company` / `--expect-title` 可与 seen_jobs
   记录核对，不匹配立即中止。
6. **回执与追踪**：提交后自动写 `apply_bot/state/apply_log.json`（含回执/失败
   原因）并同步 `job_search_tracker.csv`（沿用 `/outcome` 的词汇表与表头）。
7. **表单学习不保存网页输入值**：只存标签、placeholder、name 等静态结构；身份证号
   永不进入 SQLite、补充档案或审计日志。
8. **邮件投递双关卡**：图片岗位先生成本地审核草稿；只有后续对单个草稿明确授权，且
   CLI 再收到精确 `SEND <draft-id>` 口令，才连接 QQ SMTP。授权码只读环境变量，永不落盘。
9. **审核浏览器独立保活**：`--review` 与 `--retain-all` 通过仅绑定 `127.0.0.1` 的调试端口
   连接独立系统 Chrome。脚本结束、填写被阻塞或自动化报错时只断开 Playwright，页面继续
   保留到用户手动关闭；异常阶段写入本机 `state/browser_events.jsonl`，URL 会去掉查询参数和
   fragment，且不记录表单值、Cookie 或令牌。

## 抓取 CLI 使用

```bash
# 腾讯：岗位公开 API
bun run .agents/skills/tencent-search/cli/src/cli.ts search -q "实习" -l 上海 --format table
bun run .agents/skills/tencent-search/cli/src/cli.ts detail <postId> --format plain

# 实习僧：SSR 页面（无需登录）
bun run .agents/skills/shixiseng-search/cli/src/cli.ts search -q "数据分析" -l 上海 --format table
bun run .agents/skills/shixiseng-search/cli/src/cli.ts detail inn_xxx --format plain
```

## 发现入库（自动化通道）

`sync_seen.ts` 直接调用实习僧、腾讯、LinkedIn、FreeHire、Hotjob（默认德勤）五个 CLI 的搜索函数，把真实岗位按 `/scrape` 的 schema
合并进 `job_scraper/seen_jobs.json`（seen 去重 + tracker 排除）。默认开启
**确定性快速匹配**（`--auto-fit`）：标题含"数据分析/量化/行业研究"等强信号词
→ `fit: high`，"研究员/金融/策略"→ `medium`，否则 `unknown`（改进型只升不降，
绝不虚标；`unknown` 交 `/rank` 或人工评估）：

```bash
bun run automation/sync_seen.ts                  # 预览（默认关键词组：数据分析/量化/行业研究/商业分析，上海）
bun run automation/sync_seen.ts --write          # 实际写入
bun run automation/sync_seen.ts --keyword 量化 --location "" --limit 10 --write
bun run automation/sync_seen.ts --no-auto-fit    # 关闭自动标记（fit 全部 unknown）
bun run automation/sync_seen.ts --sources shixiseng,tencent  # 只跑指定来源
bun run automation/sync_seen.ts --sources hotjob --keyword 数据分析 --write  # 只同步德勤
```

批量队列按 fit 过滤（可组合）：
`python -m apply_bot.run_batch --dry-run --min-fit high`（默认）
`python -m apply_bot.run_batch --dry-run --min-fit high,medium`（含待评估的 medium）

字节跳动校园（无公开 API）：用浏览器会话渲染抓取列表：

```bash
python -m apply_bot.discover bytedance --keyword 数据分析 --location 上海 --write
python -m apply_bot.discover xiaohongshu --keyword 数据分析 --location 上海 --write
python -m apply_bot.discover bilibili --keyword 数据分析 --location 上海 --write

# BOSS：只读取用户明确提供的列表页当前页；不会翻页、发消息或投简历
python -m apply_bot.discover boss --list-url "<BOSS列表页URL>" --keyword 数据分析 --location 上海 --write

# BOSS：读取一个明确岗位并生成本地沟通草稿；不会发送
python -m apply_bot.boss_assist "https://www.zhipin.com/job_detail/<岗位ID>.html"
```

代理：CLI 与浏览器自动使用系统代理（Windows 注册表 ProxyServer / HTTPS_PROXY
环境变量），无需配置。

当前日常同步已接入实习僧、腾讯、LinkedIn、FreeHire 与 Hotjob/德勤；单个来源失败会单独记入控制台，
不会影响其他来源，也不会把失败伪装成 0 条。字节、小红书和 B站是按需浏览器来源，
BOSS只读用户指定页面。51job、智联发现、猎聘、拉勾、牛客、国家大学生就业平台及
重点公司官网均已进入“来源地图”，未实现的条目明确显示“未接入”。

## 专用与通用填表

已验证站点优先使用专用适配器。Hotjob/Wecruit 的新一代 `wecruit.hotjob.cn` 页面由
`hotjob` 专用适配器处理；旧版 `www.hotjob.cn/wt/...` 必须另行验证，不能假定兼容。
未知公司官网可以显式选择 `--portal generic`，但必须
提供申请表直达 URL，且只能配合 `--probe` 或 `--fill-only`。通用模式复用表单学习器，
只填写档案中已有的空白普通字段，不猜答案、不上传含义不明的附件、不点击申请按钮、
永不提交；只有可见控件明确标注“简历/CV”时才允许上传选定简历（含已严格识别的腾讯文档
简历问卷），缺失字段会进入本机控制台。对应可复用入口为
`.agents/skills/job-form-filler/SKILL.md`。

## 图片岗位与邮件投递

`.agents/skills/image-email-application/SKILL.md` 将小红书、微信群等招聘图片路由到
`/apply-email`：先提取并核验岗位、邮箱和主题规则，再按需调用 `/apply` 生成定向简历，
最后创建 `manifest.json`、`message.eml` 与深色 `review.html`。准备命令不联网、不发送；
QQ 邮箱发送使用 `smtp.qq.com:465`，账号和授权码只从当前终端环境变量读取。Gmail 插件
若已安装可作为 OAuth 通道，但必须先检查实际可用的草稿/发送能力，并保留同样的单封确认。

## 回归测试（无浏览器）

### 原生公司官网采集

`.agents/skills/company-careers-search` 将 career-ops 的六类招聘系统接口思路移植为本地 Bun CLI，
不依赖另一份源码或个人档案。`companies.example.json` 默认启用美团、字节、MiniMax、DeepSeek、
月之暗面、智谱，另附默认关闭的 Greenhouse/Ashby 示例。真实可用性必须看每次返回的 `meta.runs`，
不得把登记的公司数当作成功抓取数。

```bash
bun run .agents/skills/company-careers-search/cli/src/cli.ts companies --format table
bun run automation/sync_seen.ts --sources company --companies deepseek,zhipu --keyword 实习 --location "" --limit 20
# 确认预览后再加 --write；仅导入候选岗位，fit=unknown，不提交申请。
bun test ./.agents/skills/company-careers-search/cli/src/providers.test.ts
```

`--company-config` 可给 sync_seen 指定 JSON 公司表；`--company-max-pages` 默认 3、最大 10。
CLI 的对应参数是 `--config`、`--max-pages`。默认私有配置路径为 `automation/profile/company_sources.json`，已忽略。
`sync_seen` 的原五个默认来源不变；新增官网源需显式 `--sources company`；`/scrape` 则自动发现新技能。
预览不写岗位库或来源日志。写入时保留已有条目，按 URL/公司岗位去重，排除 tracker。
API 受限时停下并报告；不会自动登录、伪装绕过风控或运行申请步骤。详细接口范围见技能的 `references/providers.md`。

### 原有投递回归

```bash
python automation/apply_bot/tests/test_core.py   # 无 pytest 环境直跑
pytest automation/apply_bot/tests/test_core.py   # CI / 正常环境
```

覆盖：档案加载与敏感字段、适配器注册、状态日志（不覆盖已提交）、SQLite 状态管线、
表单学习与补充档案、追踪表追加/更新、简历选择优先级、队列过滤、确认关卡和发现模块。

## 与既有工作流的关系

- `/scrape`（job-scraper skill）自动发现 `.agents/skills/*/SKILL.md` → 新 CLIs 自动加入。
- `/rank` 打分后的高匹配岗位（`fit: high`）即 `run_batch` 的默认队列来源。
- `/apply` 生成针对性 CV/求职信（LaTeX）；`run_batch`/`apply_one` 上传的简历默认取
  `cv/main_<company>_*.pdf`，其次 `documents/` 下的通用简历，可用 `--cv` 覆盖。
- 项目生成的简历在上传前会检查模板来源：检测到旧 `moderncv` 将停止，必须先用
  `onepagecv` 单页模板重做。岗位明确要求文件名时，单岗位使用
  `--cv-upload-name "<实际文件名.pdf>"`，队列使用 `resume_filename`；程序会生成同哈希
  的精确命名副本并上传，浏览器里看到的 basename 必须与招聘原文一致。
- `profile.json` 与 CV 同源（`01-candidate-profile.md` + `CLAUDE.md`），改事实先改源。

## 已知限制

- **实习僧/Hotjob/牛客/B站/智联的表单仍需要「带登录的探路」**（适配器会自动输出
  `state/probe_*.json`，把快照里的字段中文名补进 `portals/*.py` 即可固化）。
- **站点改版使选择器失效时**，行为同上：probe 落盘 + 人工介入，不会静默出错。
- **字节跳动对非常规 HTTP 来源已全站封锁**（2026-08-23 实测：首页/列表/详情连续多次
  404，偶发放行；WAF 按 IP/指纹放行）——`apply_bot.discover` 与字节投递**必须**在
  真实浏览器会话内运行（首跑遇到直连 404 时适配器会提示从列表进入）。
- **实习僧详情页无 `<h1>`**（2026-08-23 线上审计）：`open_job` 改为**浏览器无关**的
  SSR 状态解析（`.iname=` / `.cname=`，已在真实页面实测提取"数据分析实习生/Halara"），
  浏览器 `window.__NUXT__` 与 h1 作为兜底。
- **腾讯 `jobdesc.html` 是 ~2KB JS 空壳**（标题/DOM 客户端渲染）：`open_job`
  直接调公开 `ByPostId` API 取真实岗位名/地点/BG（已实测）。投递入口按钮为
  **「申请」**（微信/QQ 登录 → 上传简历+填写信息 → 提交），适配器已按此固化
  主路径（上传→补填→勾选→确认），结构不符时自动转探路。
- **智联「立即投递」可能是一键提交**：确认前绝不点击岗位页按钮，先在独立简历中心
  上传或核验简历；只有终端确认关卡收到 `y` 后才点击。
- **`--fill-only` 不进入提交确认**；不加 `--review` 时仍沿用运行结束即关闭浏览器的行为。
  单岗位加 `--review` 后使用独立 Chrome，脚本结束只断开自动化，页面不会被关闭；多岗位
  使用 `--retain-all`，系统只启动一个独立 Chrome，为每个岗位保留标签页。审核后由用户
  手动关闭窗口，期间不会调用任何最终提交按钮。不同站点需要并行保留或隔离登录态时，使用
  `--profile-dir apply_bot/.chrome-profile-<site>`。
- 本流水线只覆盖「应聘者本人投递」；不做批量海投，不针对任一站点的风控做规避。
