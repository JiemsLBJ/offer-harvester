# 求职进度中心

本机私有的投递状态与表单学习控制台。页面读取
`automation/apply_bot/state/job_search.db`，并在启动时兼容导入已有的
`apply_log.json` 与 `job_search_tracker.csv`。

## 启动

```powershell
cd automation
python -m apply_bot.dashboard
```

命令会启动只绑定 `127.0.0.1` 的数据 API 和网页，并打开
`http://127.0.0.1:4173/`。按 `Ctrl+C` 同时停止两项服务。

仅启动数据 API：

```powershell
python -m apply_bot.dashboard --api-only
```

## 能力

- 总览：岗位总数、推进中、面试、Offer、活动节奏、渠道分布。
- 投递管线：准备中、已投递、面试、结果四阶段；可更新状态、下一步、日期、
  地点、行业、联系人、标签和备注。
- 表单学习：每次填表后保存字段的静态结构，不保存输入框值；显示缺失资料、
  未映射字段、出现次数和岗位上下文。
- 资料补全：用户明确填写后写入本机 `supplemental_profile.json`，下一次投递由
  `model.load_profile()` 合并，并由通用学习回填器尝试填写同站同字段。
- 来源监控：按通用平台、重点公司官网和历史来源分组；区分日常主来源、按需浏览器
  来源、人工辅助和未接入；显示最近运行、发现/新增数量、空结果、失败原因与岗位数。
- 来源地图中的“未接入”是开发清单，不代表已经成功爬取；启用来源的每次真实运行会
  单独记为正常、空结果警告或失败。
- 兼容同步：网页中的规范状态会同步回 `job_search_tracker.csv`，供 `/outcome`、
  `/interview` 与原有报告流程继续使用。

## 隐私与安全

- API 只监听 `127.0.0.1`，不向局域网或公网开放。
- 数据库、补充档案、审计日志与截图均已 gitignore。
- 抓取运行通过 SQLite 与 `state/source_runs.jsonl` 保存在本机。
- 表单快照不读取 `input.value`。
- `identity.id_card` 路径在模型加载和网页写入两层被拒绝；身份证号只能在单次
  投递确认时人工输入，永不持久化。
- 网页更新岗位状态不会触发第三方网站提交或发送消息。

## 开发验证

```powershell
cd automation\dashboard
npm install
npm run build
npx tsc --noEmit
```
