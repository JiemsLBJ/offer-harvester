# Search Queries for Job Scraper

<!-- SETUP: Customized for [姓名] via /setup Path A -->
<!-- Target market: 中国大陆 | Focus: 实习岗位（数据分析/行业研究/量化研究） -->

## Installed portal CLIs (primary for `/scrape`)

`/scrape` discovers every portal skill under `.agents/skills/*/SKILL.md` and runs its CLI first. Shipped country-agnostic CLIs include `linkedin-search` and `freehire-search`; Danish demos and any skill you add with `/add-portal` are included the same way. You do **not** need a matching `site:` line below for those CLIs to run.

The `site:` query templates in this file are the **WebSearch fallback** — for portals without a CLI, company career pages, or when a CLI fails.

**Language scope:** write every query category in every language listed in your CLAUDE.md Languages table (typically 1-2, sometimes more). A posting requiring a language you have *not* declared, as a job condition, is excluded before scoring; a posting requiring a *higher level* than you declared in a language you *do* work in is flagged for your own judgment, not excluded — see `04-job-evaluation.md`'s Language Gate, the single source of truth for this rule. Translate each category's keywords rather than machine-translating word-for-word (e.g. "Frontend Developer" -> "Desarrollador Frontend", not a literal word-for-word translation) if you work in more than one language.

## Search Sites

中国主要招聘平台：
- **51job.com**（前程无忧）—— 国内最大综合招聘平台，实习岗位丰富
- **zhaopin.com**（智联招聘）—— 综合招聘，覆盖金融/互联网行业
- **liepin.com**（猎聘）—— 中高端及专业岗位，含实习生
- **lagou.com**（拉勾）—— 互联网/科技方向
- **linkedin.com/jobs** —— 外企及跨国公司岗位；also covered by `linkedin-search` CLI
- **shixiseng.com**（实习僧）—— 专注实习岗位
- **zhipin.com**（BOSS直聘）—— 直聊模式，反馈快

For Chinese job boards, queries can include Chinese keywords directly.

## Query Categories

Queries are grouped by priority. Each query should target Shanghai/Beijing/Shenzhen or include "远程/线上" for remote roles. Write **each category in every language from your Languages table** (see Language scope above). Combine each query with your location terms (e.g. your city, region, or metro area) where the site supports it.

**Organize by function, not job title.** The same underlying work carries different titles across companies and markets (a "Data Scientist" role at one employer may be posted as "Insights Analyst" or "Data Consultant" at another). Name each priority category after the function it covers, and list several plausible job titles as query variants within that category rather than betting an entire priority tier on one exact title string.

### Priority 1: 数据分析 / 量化研究 实习

These match the strongest skill fit: Python + 数据分析 + 经济学背景.

```
site:51job.com 数据分析 实习生 上海
site:51job.com 量化 实习生 上海 OR 北京 OR 深圳
site:zhaopin.com 数据分析 实习 上海 金融
site:liepin.com 量化研究 实习
site:shixiseng.com 数据分析 实习 金融
site:linkedin.com/jobs "data analyst" intern Shanghai China
site:zhipin.com 量化分析 实习 上海
```

### Priority 2: 行业研究 / 经济分析 实习

These match the domain expertise: 经济学研究 + 金融分析.

```
site:51job.com 行业研究 实习生 上海 OR 北京 OR 深圳
site:51job.com 研究助理 实习 金融 上海
site:zhaopin.com 宏观研究 实习 上海
site:zhaopin.com 产业研究 实习
site:liepin.com 行业分析师 实习 金融
site:shixiseng.com 行业研究 实习
site:linkedin.com/jobs "research analyst" intern Shanghai China finance
```

### Priority 3: 金融科技 / 数字经济

Adjacent roles leveraging the 数字经济 master's direction.

```
site:51job.com 金融科技 实习生 上海
site:51job.com 数字金融 实习
site:zhaopin.com 金融科技 数据分析 实习 上海
site:liepin.com 金融科技 实习
site:lagou.com 金融科技 数据分析
site:linkedin.com/jobs fintech intern Shanghai China
```

### Priority 4: Broader 商业分析 / 咨询

Wider net for analytical roles with transferable skills.

```
site:51job.com 商业分析 实习生 上海
site:51job.com 经济咨询 实习
site:zhaopin.com 数据分析师 实习 互联网 上海
site:lagou.com 数据分析 实习 上海
site:shixiseng.com 商业分析 实习 上海
site:linkedin.com/jobs "business analyst" intern Shanghai China
```

### Priority 5: 互联网大厂 数据分析/战略分析

Targeting big tech companies for data/business/strategy intern roles.

```
site:zhipin.com 字节跳动 数据分析 实习
site:zhipin.com 腾讯 数据分析 实习 上海 OR 北京 OR 深圳
site:zhipin.com 阿里巴巴 数据分析 实习
site:zhipin.com 美团 商业分析 实习 上海 OR 北京
site:51job.com 字节跳动 OR 腾讯 OR 阿里巴巴 OR 美团 实习 数据分析
site:lagou.com 字节跳动 OR 腾讯 OR 阿里巴巴 OR 美团 数据分析 实习
site:shixiseng.com 字节跳动 OR 腾讯 OR 阿里巴巴 OR 美团 数据分析
site:jobs.bytedance.com 实习 数据分析 OR 商业分析 OR 研究
site:careers.tencent.com 实习 数据分析 OR 研究
site:jobs.bilibili.com 数据分析 OR 商业分析 OR 运营 实习
```

## Priority Target Companies

Monitor career pages directly for these companies:
- **券商/基金:** 中金公司（cicc.com/careers）、华泰证券（htsc.com.cn）
- **互联网/金融科技:** 蚂蚁集团、字节跳动（jobs.bytedance.com）、腾讯（careers.tencent.com）、阿里巴巴、美团、哔哩哔哩（jobs.bilibili.com）
- Search pattern: `site:<company-careers-domain> 实习 数据分析 OR 研究 OR 量化`

## 寒假/日常实习 专项查询

日常实习全年滚动；寒假实习通常于 **10-11月** 集中放出（12月-次年2月到岗）。放量期用以下查询：

```
site:shixiseng.com 寒假实习 数据分析 OR 行业研究 OR 量化
site:zhipin.com 寒假实习 数据分析 上海
site:jobs.bytedance.com 寒假实习
site:careers.tencent.com 寒假实习
site:jobs.bilibili.com 寒假实习
site:shixiseng.com 日常实习 数据分析 上海
```

## Side Gigs (also monitor)

家教和考研辅导类兼职：
- 可通过本地分类信息、校园论坛、专门家教平台关注
- 这类岗位不适合通过主流招聘网站搜索，建议关注高校BBS/微信群/熟人介绍

## Location Filter

[姓名] is based in 上海（[硕士院校]）and willing to work in:
- **理想:** 上海（线下优先，在读地）
- **可接受:** 远程/线上实习
- **可接受（短期或暑期）:** 北京、深圳（线下）
- **需要评估:** 其他城市线下（需考虑住宿成本与学业安排）
- **不可:** 长期驻场海外（当前不考虑出国工作）

## Language Filter

Your working languages and levels are in CLAUDE.md's Languages table. When filtering scraped results, apply `04-job-evaluation.md`'s Language Gate: a posting requiring a language you haven't declared at all is excluded; a posting requiring a higher level than you declared in a language you do work in is not excluded, flag it clearly instead (see `job-scraper/SKILL.md`'s Step 3 "Quick Fit Assessment" for how the flag surfaces in `/scrape` output). Postings simply *written* in a language you don't work in, that don't require it on the job, are fine.

## Date Filter

Only include jobs posted within the last 14 days, or with an application deadline that has not yet passed. If a posting date cannot be determined, include it but flag as "date unknown".

## 适应中国市场说明

中国实习招聘特点：
- 实习岗位通常通过实习僧（shixiseng.com）、BOSS直聘（zhipin.com）、牛客网（nowcoder.com）以及各公司官网/公众号发布
- 券商/基金实习常有内推渠道，LinkedIn上中国金融实习较少
- 部分岗位使用"日常实习""暑期实习""寒假实习"等标签
- 建议同时关注目标公司官网"加入我们/校园招聘/实习生招聘"页面

## Adapting Queries

If the user specifies a focus area, select queries from the matching category and also generate 2-3 custom queries for that focus. For example:
- "/scrape 量化" -> Priority 1 queries + custom "量化研究员""量化开发""因子挖掘" queries
- "/scrape 券商" -> Priority 2 queries + 券商名称 site 定向搜索
- "/scrape 互联网" -> Priority 4 queries + 大厂名称定向搜索
