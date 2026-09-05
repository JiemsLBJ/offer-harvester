import { readFile } from "node:fs/promises"
import { resolve } from "node:path"
import { PublicClient } from "../http.js"
import { canonicalUrl, fetchPage, resolveBoard, type Company, type Job, type JsonReader } from "../providers.js"

export interface SearchOptions {
  query: string; location?: string; limit?: number; maxPages?: number; companies?: string[];
  config?: string; jobage?: number; format?: string;
}
export interface SourceRun {
  company_id: string; company: string; provider: string; url: string;
  status: "ok" | "partial" | "error"; pages: number; fetched: number; matched: number; message: string;
}
interface Dependencies { read: JsonReader; check: (url: string) => Promise<void>; companies: Company[]; now: number }

export function integer(value: number | undefined, fallback: number, max: number): number {
  const n = value ?? fallback
  if (!Number.isSafeInteger(n) || n <= 0 || n > max) throw new Error(`数量参数必须是 1–${max} 的整数`)
  return n
}

export async function loadCompanies(config?: string): Promise<Company[]> {
  let text: string
  if (config) text = await readFile(resolve(config), "utf8")
  else {
    try { text = await readFile(new URL("../../../../../../automation/profile/company_sources.json", import.meta.url), "utf8") }
    catch (e) {
      if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e
      text = await readFile(new URL("../../../companies.example.json", import.meta.url), "utf8")
    }
  }
  const data = JSON.parse(text)
  if (!Array.isArray(data) || !data.length || data.length > 100) throw new Error("公司配置必须是含 1–100 家公司的 JSON 数组")
  const ids = new Set<string>()
  for (const c of data) {
    if (!c || typeof c.id !== "string" || !/^[a-z0-9_-]+$/.test(c.id) || ids.has(c.id) ||
        typeof c.name !== "string" || !c.name.trim() || typeof c.url !== "string" || (c.enabled !== undefined && typeof c.enabled !== "boolean"))
      throw new Error("公司配置字段错误或 id 重复：需要 id/name/url，可选 enabled 布尔值")
    resolveBoard(c); ids.add(c.id)
  }
  return data
}

export function selectCompanies(all: Company[], ids?: string[]): Company[] {
  if (!ids?.length) return all.filter(c => c.enabled !== false)
  const selected = [...new Set(ids)].map(id => {
    const c = all.find(c => c.id === id || c.name === id)
    if (!c) throw new Error(`未登记公司：${id}；先运行 companies 或提供 --config`)
    return c
  })
  return selected
}

export function matches(job: Job, options: SearchOptions, now = Date.now()): boolean {
  if (options.query && !`${job.title} ${job.description}`.toLowerCase().includes(options.query.toLowerCase())) return false
  if (options.location) {
    const aliases: Record<string, string> = { 上海: "Shanghai", 北京: "Beijing", 深圳: "Shenzhen", 杭州: "Hangzhou", 广州: "Guangzhou", 成都: "Chengdu", 远程: "Remote" }
    const city = options.location.toLowerCase(), location = job.location.toLowerCase()
    const alternative = (aliases[options.location] ?? Object.keys(aliases).find(k => aliases[k].toLowerCase() === city) ?? city).toLowerCase()
    if (!location.includes(city) && !location.includes(alternative)) return false
  }
  if (options.jobage && (!job.date || Date.parse(job.date) < now - options.jobage * 86_400_000)) return false
  return true
}

export async function fetchSearch(options: SearchOptions, dependencies: Partial<Dependencies> = {}) {
  const limit = integer(options.limit, 20, 500), maxPages = integer(options.maxPages, 3, 10)
  if (options.jobage !== undefined) integer(options.jobage, 14, 3650)
  const companies = selectCompanies(dependencies.companies ?? await loadCompanies(options.config), options.companies)
  if (!companies.length) throw new Error("没有启用的公司；检查 enabled 或指定 --companies")
  const client = new PublicClient()
  const read = dependencies.read ?? client.json.bind(client), check = dependencies.check ?? client.check.bind(client)
  const unique = new Map<string, Job>(), runs: SourceRun[] = []
  let unknownDates = 0
  for (const c of companies) {
    const run: SourceRun = { company_id: c.id, company: c.name, url: c.url, provider: "", status: "ok", pages: 0, fetched: 0, matched: 0, message: "" }
    const seen = new Set<string>()
    try {
      const board = resolveBoard(c); run.provider = board.provider
      await check(c.url)
      for (let page = 1; page <= maxPages; page++) {
        const batch = await fetchPage(c, board, options.query, page, read)
        run.pages++; run.fetched += batch.rawCount
        let added = 0
        for (const job of batch.jobs) {
          const key = canonicalUrl(job.url)
          if (seen.has(key)) continue
          seen.add(key); added++
          if (!job.date) unknownDates++
          if (!matches(job, options, dependencies.now)) continue
          run.matched++
          if (!unique.has(key)) unique.set(key, job)
        }
        if (batch.malformed) {
          run.status = "partial"; run.message = "跳过了缺少必要字段或未公开的条目；不能保证完整覆盖"
        }
        if (!batch.more) break
        if (batch.jobs.length && !added) {
          run.status = "partial"; run.message = "分页重复、没有新岗位，已停止；未声明全量完成"; break
        }
        if (page === maxPages) { run.status = "partial"; run.message = `达到 ${maxPages} 页上限；仍有未扫描岗位` }
      }
    } catch (e) {
      run.status = run.pages ? "partial" : "error"
      run.message = e instanceof Error ? e.message : String(e)
    }
    runs.push(run)
  }
  return {
    meta: { query: options.query, location: options.location ?? "", max_pages: maxPages,
      matched: unique.size, output_truncated: unique.size > limit, unknown_dates: unknownDates,
      complete: runs.every(r => r.status === "ok") && unique.size <= limit, runs,
      errors: runs.filter(r => r.status === "error").map(r => `${r.company}: ${r.message}`),
      warnings: runs.filter(r => r.status === "partial").map(r => `${r.company}: ${r.message}`) },
    results: [...unique.values()].slice(0, limit),
  }
}

export async function fetchDetail(target: string, options: Omit<SearchOptions, "query"> & { query?: string } = {}) {
  const all = await loadCompanies(options.config)
  const owner = all.find(c => {
    const b = resolveBoard(c)
    return target.startsWith(`${b.provider}:${c.id}:`) || (target.startsWith("https:") && new URL(target).origin === b.origin &&
      (["meituan", "feishu"].includes(b.provider) || target.startsWith(b.base + (b.provider === "moka" ? "#/job/" : "/"))))
  })
  const selected = options.companies ?? (owner ? [owner.id] : [])
  if (!selected.length) throw new Error("无法定位公司；请指定 --companies 与原搜索的 --config")
  const out = await fetchSearch({ ...options, query: options.query ?? "", companies: selected, limit: 500 })
  const result = out.results.find(j => j.id === target || canonicalUrl(j.url) === canonicalUrl(target))
  if (!result) throw new Error(`有限页扫描中未找到该岗位（不代表已下架）。请附原 --query 或增加 --max-pages。${[...out.meta.errors, ...out.meta.warnings].join("；")}`)
  return { meta: out.meta, result }
}
