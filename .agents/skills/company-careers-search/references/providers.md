# 公司来源配置与移植范围

接口字段和路由改编自本地 career-ops v1.32.0 的 `providers/{meituan,feishu-jobs,mokahr,greenhouse,lever,ashby}.mjs`。
原项目：https://github.com/career-ops-hq/career-ops 。保留 `LICENSE.career-ops` 的 MIT 版权声明。
没有复制其个人数据、模式系统、评分、tracker、仪表板、自动更新或全量 ATS 扫描数据库。
未移植其为绕过站点风控而设置的伪装 User-Agent，也不重试限流响应。

| 系统 | 可配置 URL 形态 | 当前范围 |
|---|---|---|
| 美团 | `https://zhaopin.meituan.com/web/social` | 社招列表，不能据此声称覆盖全部校招/实习频道 |
| 飞书招聘 | `https://jobs.bytedance.com`、`https://<tenant>.jobs.feishu.cn` | 公共 job/posts；字节已有浏览器采集作为独立后续选择 |
| Moka | `https://app.mokahr.com/social-recruitment/<org>/<siteId>`，也接受 `campus-recruitment`、`apply` 路由 | 真实租户/org/siteId 必须来自公司官方入口；公开列表响应以站点提供的密钥解码 |
| Greenhouse | `https://job-boards.greenhouse.io/<board>`、`https://boards.greenhouse.io/<board>` | 公共 jobs API（含 JD）；未移植 offices 地点补全、EU 专有端点 |
| Lever | `https://jobs.lever.co/<board>`、`https://jobs.eu.lever.co/<board>` | 公共 postings API；不枚举租户 |
| Ashby | `https://jobs.ashbyhq.com/<board>` | 公共 posting-api；保留多地点与远程字段，不导入薪资估算 |

扩展时先核对公司官网确实指向该 ATS，不能从一个 slug 猜测雇主归属。再做低量真实验证：

```json
[
  {
    "id": "deepseek",
    "name": "DeepSeek",
    "url": "https://app.mokahr.com/social-recruitment/high-flyer/140576",
    "enabled": true
  }
]
```

私有文件 `automation/profile/company_sources.json` 是完整替代列表，不是增量覆盖；不创建时使用公开示例。
不支持任意 `api` 覆盖、HTTP、本机地址、嵌入账号密码或自定义端口。
公司名/id 和配置 URL 不包含个人档案；岗位数据仍不受信任。

分页按原始列表长度计算，避免一条损坏记录截断后续页面。中途失败保留此前结果并标记 partial；到达页数/输出上限明确提示，不宣称全量。
Moka 返回的 createdAt 常无时区，保守输出 `date=null`。地点缺失不猜；Greenhouse 只有 Hybrid 等工作模式时也不能猜测城市。
补抓详情只在这次扫描覆盖范围内查找，保留“未找到不等于已下架”的区别。

只新增岗位发现能力。阿里巴巴、Workday、北森等系统本次没有移植，遇到它们应继续原人工/浏览器流程或另行开发。

## 本地低量验证快照（2026-09-05）

下列仅是当日网络下、每家公司至多一页的验证，不是长期可用性保证或岗位总数。
仓库内回归测试使用合成数据、不联网；运行 `bun test ./.agents/skills/company-careers-search/cli/src/providers.test.ts`。

| 公司/引擎 | 结果 |
|---|---|
| 美团 | “数据分析”首批读取 100 条，明确提示仍有后续页；包含上海岗位 |
| DeepSeek / Moka | “实习”读取 2 条；日期未提供时区，保持未知 |
| 智谱 / Moka | “实习”读取 34 条；部分地点为空，不能假定城市 |
| 月之暗面 / Moka | 公共接口可读，“实习”返回 0 条；不能推断公司无其他岗位 |
| Anthropic / Greenhouse | 公共列表读取 595 条；含 JD，非中国岗位专属来源 |
| 字节、MiniMax / 飞书 | 请求返回 HTTP 405，停止，未复制上游的伪装 UA 绕过规则 |
| ElevenLabs / Ashby | robots 请求返回 HTTP 401，停止；未声称实测接通 |
| Lever | 解析、字段、多地点和请求路径有离线回归；本轮未选择真实公司做线上验证 |

美团的 robots.txt 会同源跳转到正常招聘首页；只允许这一类有限的同源 robots 跳转，API 仍禁止自动跳转。
Greenhouse 完整 JD 响应可能较大，最大允许 32 MB；超过上限记录错误，不返回伪造空结果。
