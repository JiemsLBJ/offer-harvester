// sync_seen.ts — 把已接通来源的真实岗位合并进 job_scraper/seen_jobs.json
//
// 直接复用门户 CLI 的 fetchSearch（无子进程、无重复解析逻辑）：
//   .agents/skills/shixiseng-search/cli/src/commands/search.ts
//   .agents/skills/tencent-search/cli/src/commands/search.ts
//   .agents/skills/linkedin-search/cli/src/commands/search.ts
//   .agents/skills/freehire-search/cli/src/commands/search.ts
//   .agents/skills/hotjob-search/cli/src/commands/search.ts（默认德勤实习）
//
// 用法：
//   bun run automation/sync_seen.ts                    # 只读：预览将与现库合并的岗位
//   bun run automation/sync_seen.ts --write            # 实际写入 seen_jobs.json
//   bun run automation/sync_seen.ts --keyword 量化 --limit 10 --write
//   bun run automation/sync_seen.ts --location 上海
//   bun run automation/sync_seen.ts --sources shixiseng,tencent
//   bun run automation/sync_seen.ts --sources company --companies deepseek,zhipu --keyword 实习
//   bun run automation/sync_seen.ts --no-auto-fit      # 关闭标题关键词快速匹配（fit 全部 unknown）
//
// 快速匹配（默认开启）：职位标题含 数据分析/量化/行业研究/数据开发/商业分析/金融工程 等
// 强信号词 → high；含 研究员/研究/策略/风控/金融/咨询/产业/经济/基金/证券 → medium；
// 其余 → unknown。只升不降、绝不虚标：拿不准时是 unknown，改由 /rank 或人工评估。
//
// 说明：与 /scrape 的职责不同。/scrape 输出给人看（含匹配评估、去重、追踪表排除），
// sync_seen 是给自动化的「发现入库」通道：只做 CLI 搜索 + seen 去重 + tracker 排除，
// 匹配度留 unknown（由 /rank 或 quick-fit 后续填），不修改任何已存在条目。
// 条目 schema 与 job-scraper SKILL.md Step 4 完全一致。

import { fetchSearch as fetchShixiseng } from "../.agents/skills/shixiseng-search/cli/src/commands/search.js"
import { fetchSearch as fetchTencent } from "../.agents/skills/tencent-search/cli/src/commands/search.js"
import { fetchSearch as fetchLinkedin } from "../.agents/skills/linkedin-search/cli/src/commands/search.js"
import { fetchSearch as fetchFreehire } from "../.agents/skills/freehire-search/cli/src/commands/search.js"
import { fetchSearch as fetchHotjob } from "../.agents/skills/hotjob-search/cli/src/commands/search.js"
import { fetchSearch as fetchCompany } from "../.agents/skills/company-careers-search/cli/src/commands/search.js"
import { canonicalUrl } from "../.agents/skills/company-careers-search/cli/src/providers.js"
import { randomUUID } from "node:crypto"
import { appendFile, mkdir } from "node:fs/promises"

interface SeenEntry {
  title: string
  company: string
  url: string
  first_seen: string
  deadline: string | null
  location?: string
  fit: string
  status: string
  portal: string
  source: string
}

const DEFAULT_KEYWORDS = ["数据分析", "量化", "行业研究", "商业分析"]
const DEFAULT_LOCATION = "上海"
const DEFAULT_LIMIT = 20
const DEFAULT_PORTALS = ["shixiseng", "tencent", "linkedin", "freehire", "hotjob"] as const
const ACTIVE_PORTALS = [...DEFAULT_PORTALS, "company"] as const
type ActivePortal = (typeof ACTIVE_PORTALS)[number]

function chinaIso(date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date)
  const value = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value ?? ""
  return `${value("year")}-${value("month")}-${value("day")}T${value("hour")}:${value("minute")}:${value("second")}+08:00`
}

const TODAY = chinaIso().slice(0, 10)
const SOURCE_RUN_DIR = new URL("./apply_bot/state/", import.meta.url)
const SOURCE_RUN_LOG = new URL("./apply_bot/state/source_runs.jsonl", import.meta.url)

async function appendSourceRun(event: Record<string, unknown>) {
  await mkdir(SOURCE_RUN_DIR, { recursive: true })
  await appendFile(SOURCE_RUN_LOG, JSON.stringify(event) + "\n", "utf8")
}

// ---------------------------------------------------------------------------
// seen_jobs.json / tracker 读取
// ---------------------------------------------------------------------------

async function readSeen(): Promise<Record<string, SeenEntry>> {
  try {
    const t = Bun.file("job_scraper/seen_jobs.json")
    const j = JSON.parse((await t.text()) || "{}") as { seen?: Record<string, SeenEntry> }
    if (!j.seen || typeof j.seen !== "object" || Array.isArray(j.seen)) throw new Error("seen_jobs.json 缺少有效 seen 对象；停止以免覆盖现库")
    return j.seen
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e
    return {}
  }
}

async function readTrackerKeys(): Promise<Set<string>> {
  const keys = new Set<string>()
  try {
    const t = Bun.file("job_search_tracker.csv")
    const text = await t.text()
    const lines = text.split(/\r?\n/).filter((l) => l.trim())
    if (lines.length < 2) return keys
    const header = lines[0].split(",").map((s) => s.trim())
    const ci = header.indexOf("company")
    const ri = header.indexOf("role")
    if (ci < 0 || ri < 0) return keys
    for (const line of lines.slice(1)) {
      const cols = line.split(",")
      if (cols.length <= Math.max(ci, ri)) continue
      keys.add(`${cols[ci].trim().toLowerCase()}|${cols[ri].trim().toLowerCase()}`)
    }
  } catch {
    /* tracker 不存在时忽略 */
  }
  return keys
}

async function writeSeen(seen: Record<string, SeenEntry>) {
  const out = JSON.stringify({ seen }, null, 2) + "\n"
  await Bun.write("job_scraper/seen_jobs.json", out)
}

// ---------------------------------------------------------------------------
// 确定性快速匹配（--auto-fit，默认开启）
// 与 /scrape Step 3 的「quick fit assessment」同义但更保守：只用岗位标题的
// 强信号词判断，绝不虚标；拿不准的一律 unknown（留给 /rank 或人工评估）。
// ---------------------------------------------------------------------------

const HIGH_TERMS = ["数据分析", "量化", "行业研究", "数据科学", "数据开发", "数据分析师", "商业分析", "行业分析师", "金融工程", "策略研究", "研究助理", "数据挖掘", "机器学习", "计量"]
const MEDIUM_TERMS = ["研究员", "研究", "策略", "风控", "金融", "咨询", "产业", "经济", "投资", "基金", "证券"]

function quickFit(title: string, company: string): "high" | "medium" | "unknown" {
  const t = title + " " + company
  if (HIGH_TERMS.some((k) => t.includes(k))) return "high"
  if (MEDIUM_TERMS.some((k) => t.includes(k))) return "medium"
  return "unknown"
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------

interface Flags {
  write: boolean
  autoFit: boolean
  keywords: string[]
  location: string
  limit: number
  sources: ActivePortal[]
  companies?: string[]
  companyConfig?: string
  companyMaxPages?: number
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = {
    write: false, autoFit: true, keywords: DEFAULT_KEYWORDS, location: DEFAULT_LOCATION,
    limit: DEFAULT_LIMIT, sources: [...DEFAULT_PORTALS],
  }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === "--write") flags.write = true
    else if (a === "--no-auto-fit") flags.autoFit = false
    else if (a === "--keyword") flags.keywords = [argv[++i] ?? ""]
    else if (a === "--location") flags.location = argv[++i] ?? ""
    else if (a === "--limit") flags.limit = parseInt(argv[++i] ?? "0", 10) || DEFAULT_LIMIT
    else if (a === "--companies") {
      flags.companies = (argv[++i] ?? "").split(",").map(s => s.trim()).filter(Boolean)
      if (!flags.companies.length) throw new Error("--companies 不能为空")
    }
    else if (a === "--company-config") {
      flags.companyConfig = argv[++i]
      if (!flags.companyConfig || flags.companyConfig.startsWith("--")) throw new Error("--company-config 缺少路径")
    }
    else if (a === "--company-max-pages") flags.companyMaxPages = Number(argv[++i])
    else if (a === "--sources") {
      const requested = (argv[++i] ?? "").split(",").map((value) => value.trim()).filter(Boolean)
      const unknown = requested.filter((value) => !ACTIVE_PORTALS.includes(value as ActivePortal))
      if (!requested.length || unknown.length) {
        console.error(`--sources 只能包含: ${ACTIVE_PORTALS.join(",")}；收到: ${requested.join(",") || "空"}`)
        process.exit(1)
      }
      flags.sources = requested as ActivePortal[]
    }
    else if (a === "--help" || a === "-h") {
      console.log("sync_seen.ts [--sources shixiseng,tencent,linkedin,freehire,hotjob,company] [--keyword 关键词] [--location 城市] [--limit 20] [--companies deepseek,zhipu] [--company-config JSON路径] [--company-max-pages 3] [--write]；默认保留原五个来源，公司官网显式使用 --sources company")
      process.exit(0)
    } else {
      console.error(`未知参数: ${a}`)
      process.exit(1)
    }
  }
  if (flags.companyMaxPages !== undefined && (!Number.isSafeInteger(flags.companyMaxPages) || flags.companyMaxPages < 1 || flags.companyMaxPages > 10))
    throw new Error("--company-max-pages 必须是 1–10 的整数")
  if ((flags.companies || flags.companyConfig || flags.companyMaxPages !== undefined) && !flags.sources.includes("company"))
    throw new Error("公司配置参数需要同时指定 --sources company（可与原来源逗号组合）")
  return flags
}

interface PortalResult {
  id: string
  title: string
  company?: string | null
  location?: string | null
  date?: string | null
  deadline?: string | null
  url: string
}

function englishCity(location: string): string {
  const aliases: Record<string, string> = {
    "上海": "Shanghai", "深圳": "Shenzhen", "北京": "Beijing", "广州": "Guangzhou",
    "杭州": "Hangzhou", "成都": "Chengdu", "南京": "Nanjing", "武汉": "Wuhan",
  }
  return aliases[location.trim()] ?? location.trim()
}

async function fetchPortal(portal: ActivePortal, keyword: string, flags: Flags): Promise<{ results: PortalResult[]; meta?: { errors?: string[]; warnings?: string[]; runs?: unknown[]; output_truncated?: boolean } }> {
  if (portal === "company") {
    return fetchCompany({ query: keyword, location: flags.location, limit: flags.limit,
      companies: flags.companies, config: flags.companyConfig, maxPages: flags.companyMaxPages })
  }
  if (portal === "shixiseng") {
    return fetchShixiseng({ query: keyword, location: flags.location, page: 1, limit: flags.limit, format: "json" })
  }
  if (portal === "tencent") {
    return fetchTencent({ query: keyword, location: flags.location, page: 1, limit: flags.limit, format: "json" })
  }
  if (portal === "linkedin") {
    const city = englishCity(flags.location)
    return fetchLinkedin({
      query: keyword, location: city ? `${city}, China` : "China", jobage: 30,
      page: 1, limit: Math.min(flags.limit, 10), format: "json",
    })
  }
  if (portal === "hotjob") {
    return fetchHotjob({
      query: keyword, location: flags.location, page: 1, limit: flags.limit,
      format: "json", company: "德勤",
    })
  }
  return fetchFreehire({
    query: keyword, jobage: 30, page: 1, limit: flags.limit, format: "json",
    descriptionFormat: "text", includeDescription: false,
    regions: [], countries: [], cities: englishCity(flags.location) ? [englishCity(flags.location)] : [],
    seniority: [], category: [], skills: [], facets: {},
  })
}

const SOURCE_META: Record<ActivePortal, { mode: string; entryUrl: string }> = {
  company: { mode: "cli-company-api", entryUrl: "" },
  shixiseng: { mode: "cli-ssr", entryUrl: "https://www.shixiseng.com/interns" },
  tencent: { mode: "cli-api", entryUrl: "https://careers.tencent.com/search.html" },
  linkedin: { mode: "cli-public-pages", entryUrl: "https://www.linkedin.com/jobs/" },
  freehire: { mode: "cli-api", entryUrl: "https://freehire.me/jobs" },
  hotjob: { mode: "cli-api", entryUrl: "https://wecruit.hotjob.cn/SU64365a780dcad43c5ae82bab/pb/interns.html" },
}

interface SyncServices {
  readSeen: typeof readSeen
  readTrackerKeys: typeof readTrackerKeys
  fetchPortal: typeof fetchPortal
  writeSeen: typeof writeSeen
  appendSourceRun: typeof appendSourceRun
}

export async function runSync(argv = process.argv.slice(2), overrides: Partial<SyncServices> = {}) {
  const services = { readSeen, readTrackerKeys, fetchPortal, writeSeen, appendSourceRun, ...overrides }
  const flags = parseFlags(argv)
  const batchId = randomUUID()
  const seen = await services.readSeen()
  const originalCount = Object.keys(seen).length
  const trackerKeys = await services.readTrackerKeys()
  const seenUrls = new Set(Object.values(seen).map(e => canonicalUrl(e.url)))
  const seenRoles = new Set(Object.values(seen).map(e => roleKey(e.company, e.title)))
  const newEntries: Array<{ key: string; portal: string; entry: SeenEntry }> = []
  const errors: string[] = []

  for (const portal of flags.sources) {
    const startedAt = chinaIso()
    let portalNewCount = 0
    const portalErrors: string[] = []
    const portalJobs = new Map<string, Record<string, unknown>>()
    let rawDiscoveredCount = 0
    const companyRuns: unknown[] = []
    for (const kw of flags.keywords) {
      try {
        const out = await services.fetchPortal(portal, kw, flags)
        if (portal === "company") {
          companyRuns.push(...(out.meta?.runs ?? []))
          const notices = [...(out.meta?.errors ?? []), ...(out.meta?.warnings ?? [])].map(m => `${kw}: ${m}`)
          if (out.meta?.output_truncated) notices.push(`${kw}: 达到输出条数上限，未导入全部匹配岗位`)
          portalErrors.push(...notices); errors.push(...notices)
        }
        rawDiscoveredCount += out.results.length
        for (const r of out.results) {
          if (!r.id || !r.url) continue
          const key = `${portal}:${r.id}`
          const existed = Boolean(seen[key]) || seenUrls.has(canonicalUrl(r.url)) || seenRoles.has(roleKey(r.company, r.title))
          // tracker 去重：公司+岗位 大小写不敏感
          const tracked = trackerKeys.has(roleKey(r.company, r.title))
          let added = false
          if (!existed && !tracked) {
            seen[key] = {
              title: r.title,
              company: r.company ?? "",
              url: r.url,
              first_seen: TODAY,
              deadline: r.deadline ?? null,
              location: r.location ?? "",
              fit: flags.autoFit && portal !== "company" ? quickFit(r.title, r.company ?? "") : "unknown",
              status: "new",
              portal: portal === "company" ? "company-careers-search" : `${portal}-search`,
              source: "cli",
            }
            newEntries.push({ key, portal, entry: seen[key]! })
            seenUrls.add(canonicalUrl(r.url)); seenRoles.add(roleKey(r.company, r.title))
            portalNewCount += 1
            added = true
          }
          const previous = portalJobs.get(r.url)
          portalJobs.set(r.url, {
            id: r.id,
            title: r.title,
            company: r.company ?? "",
            location: r.location ?? "",
            date: r.date ?? null,
            url: r.url,
            fit: seen[key]?.fit ?? (flags.autoFit && portal !== "company" ? quickFit(r.title, r.company ?? "") : "unknown"),
            is_new: Boolean(previous?.is_new) || added,
            already_tracked: tracked,
          })
        }
      } catch (e) {
        const message = `${portal} "${kw}": ${e instanceof Error ? e.message : String(e)}`
        errors.push(message)
        portalErrors.push(message)
      }
    }
    const discoveredCount = portalJobs.size
    const status = portalErrors.length ? (discoveredCount ? "warning" : "error") : (discoveredCount ? "success" : "warning")
    const message = portalErrors.length
      ? `${portalErrors.length} 项来源异常或覆盖不完整；已读取 ${discoveredCount} 条。`
      : discoveredCount
        ? `成功读取 ${discoveredCount} 条岗位。`
        : "官网返回 0 条岗位，请检查关键词、地点或站点状态。"
    if (flags.write) await services.appendSourceRun({
      id: randomUUID(), portal, status,
      mode: SOURCE_META[portal].mode,
      keyword: flags.keywords.join("、"), location: flags.location,
      discovered_count: discoveredCount, new_count: portalNewCount,
      entry_url: SOURCE_META[portal].entryUrl,
      message, started_at: startedAt, finished_at: chinaIso(),
      details: {
        batch_id: batchId,
        write: flags.write,
        errors: portalErrors,
        raw_count: rawDiscoveredCount,
        jobs: [...portalJobs.values()],
        ...(portal === "company" ? { company_runs: companyRuns } : {}),
      },
    })
  }

  console.log(`扫描完成：扫描前现库 ${originalCount} 条，候选新增 ${newEntries.length} 条`)
  for (const n of newEntries) {
    console.log(`  + [${n.entry.fit}] ${n.portal} | ${n.entry.company} - ${n.entry.title}`)
    console.log(`    ${n.entry.url}`)
  }
  if (errors.length) {
    console.log("\n来源异常或覆盖提醒（受限站点不自动重试）:")
    for (const e of errors) console.log(`  ! ${e}`)
  }

  if (flags.write && newEntries.length > 0) {
    await services.writeSeen(seen)
    console.log(`\n已写入 job_scraper/seen_jobs.json（+${newEntries.length}）`)
  } else if (flags.write) {
    console.log("\n无新增，文件未改动")
  } else {
    console.log("\n预览模式（未写盘）。加 --write 执行写入。")
  }
}

export function roleKey(company: string | null | undefined, title: string): string {
  return `${(company ?? "").trim().toLowerCase()}|${title.trim().toLowerCase()}`
}

if (import.meta.main) runSync().catch((e) => {
  console.error(`sync_seen 失败: ${e instanceof Error ? e.message : String(e)}`)
  process.exit(1)
})
