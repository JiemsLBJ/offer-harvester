// Adapted from career-ops v1.32.0 providers. See ../../LICENSE.career-ops.
// Only public discovery is ported; no profiles, scoring, tracker or application code.
import { createDecipheriv } from "node:crypto"
import { publicUrl } from "./http.js"

export interface Company { id: string; name: string; url: string; enabled?: boolean }
export interface Job {
  id: string; title: string; company: string; location: string; date: string | null;
  date_kind: "published" | "refreshed" | "created" | "unknown";
  deadline: null; url: string; description: string; provider: string; company_id: string;
}
export interface Board { provider: string; api: string; origin: string; base: string; slug?: string; siteId?: number; pageSize: number; paged: boolean }
export interface Page { jobs: Job[]; rawCount: number; malformed: number; more: boolean }
export type JsonReader = (url: string, body?: unknown) => Promise<any>

export function resolveBoard(company: Company): Board {
  const u = publicUrl(company.url), slug = u.pathname.split("/").filter(Boolean)[0]
  const common = { origin: u.origin, base: u.origin + u.pathname.replace(/\/$/, ""), pageSize: 100, paged: true }
  if (u.hostname === "zhaopin.meituan.com") return { ...common, provider: "meituan", api: `${u.origin}/api/official/job/getJobList` }
  if (u.hostname === "jobs.bytedance.com" || /^[a-z0-9-]+\.jobs\.feishu\.cn$/.test(u.hostname))
    return { ...common, provider: "feishu", api: `${u.origin}/api/v1/search/job/posts` }
  if (u.hostname === "app.mokahr.com") {
    const m = /^\/(?:social-recruitment|campus-recruitment|apply)\/([a-zA-Z0-9_-]+)\/(\d+)\/?$/.exec(u.pathname)
    if (m && Number.isSafeInteger(Number(m[2])) && Number(m[2]) > 0)
      return { ...common, provider: "moka", api: `${u.origin}/api/outer/ats-apply/website/jobs/v2`, slug: m[1], siteId: Number(m[2]), pageSize: 50 }
  }
  if (slug && /^[a-zA-Z0-9_-]+$/.test(slug)) {
    if (["boards.greenhouse.io", "job-boards.greenhouse.io"].includes(u.hostname))
      return { ...common, provider: "greenhouse", api: `https://boards-api.greenhouse.io/v1/boards/${slug}/jobs?content=true`, paged: false }
    if (["jobs.lever.co", "jobs.eu.lever.co"].includes(u.hostname))
      return { ...common, provider: "lever", api: `https://api.${u.hostname.slice(5)}/v0/postings/${slug}?mode=json`, paged: false }
    if (u.hostname === "jobs.ashbyhq.com")
      return { ...common, provider: "ashby", api: `https://api.ashbyhq.com/posting-api/job-board/${slug}`, paged: false }
  }
  throw new Error("尚无该官网的原生适配器；请使用已支持的官方招聘系统 URL，不能仅登记即视作已接通")
}

const string = (v: unknown): string => typeof v === "string" ? v : ""
const names = (a: any): string => Array.isArray(a) ? a.map(v => typeof v === "string" ? v : v?.name).filter(Boolean).join("/") : ""
const rows = (list: any[]): any[] => list.map(p => p && typeof p === "object" ? p : {})
export function plainText(v: unknown): string {
  let s = string(v)
  const decode = (text: string) => text.replace(/&(lt|gt|amp|quot|apos|nbsp|#\d+|#x[\da-f]+);/gi, (entity, code: string) => {
    if (code.startsWith("#")) {
      const n = code[1].toLowerCase() === "x" ? parseInt(code.slice(2), 16) : Number(code.slice(1))
      return n > 0 && n <= 0x10ffff && !(n >= 0xd800 && n <= 0xdfff) ? String.fromCodePoint(n) : ""
    }
    return ({ lt: "<", gt: ">", amp: "&", quot: '"', apos: "'", nbsp: " " } as Record<string, string>)[code.toLowerCase()] ?? entity
  })
  const strip = (text: string) => text.replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, " ").replace(/<(?:[^>"']|"[^"]*"|'[^']*')+>/g, " ")
  for (let i = 0; i < 2; i++) s = decode(strip(s))
  return strip(s).replace(/<(?=\/?[a-z!?])/gi, "").replace(/\s+/g, " ").trim()
}

export function isoDate(v: unknown): string | null {
  // Timestamp without a timezone must not acquire the machine's timezone.
  if (typeof v === "string" && !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(v)) return null
  const ms = typeof v === "number" ? (v > 1e12 ? v : v * 1000) : Date.parse(string(v))
  return Number.isFinite(ms) && ms > 0 && ms < 8.64e15 ? new Date(ms).toISOString() : null
}

export function canonicalUrl(value: string): string {
  try {
    const u = publicUrl(value)
    for (const key of [...u.searchParams.keys()]) if (/^(utm_|track|source$|from$|ref$)/i.test(key)) u.searchParams.delete(key)
    u.searchParams.sort()
    // Moka's hash identifies the actual job; never collapse the whole tenant.
    if (!(u.hostname === "app.mokahr.com" && /^#\/job\/[^/]+\/?$/.test(u.hash))) u.hash = ""
    return u.href.replace(/\/$/, "")
  } catch { return value }
}

export function decryptMoka(envelope: any): any {
  if (typeof envelope?.data !== "string" || typeof envelope?.necromancer !== "string" || Buffer.byteLength(envelope.necromancer) !== 16)
    throw new Error("Moka 公共列表响应格式改变：缺少有效 data/necromancer")
  // Public site's own response supplies this key; no credentials or session.
  const decipher = createDecipheriv("aes-128-cbc", Buffer.from(envelope.necromancer), Buffer.from("de7c21ed8d6f50fe"))
  return JSON.parse(Buffer.concat([decipher.update(Buffer.from(envelope.data, "base64")), decipher.final()]).toString("utf8"))
}

function makeJob(c: Company, b: Board, id: unknown, title: unknown, url: unknown, location: string, description: unknown, date: unknown, kind: Job["date_kind"]): Job | null {
  if ((typeof id !== "string" && typeof id !== "number") || !String(id) || !string(title).trim() || !string(url)) return null
  try { publicUrl(string(url)) } catch { return null }
  const published = isoDate(date)
  return {
    id: `${b.provider}:${c.id}:${id}`,
    title: string(title).trim(),
    company: c.name,
    url: canonicalUrl(string(url)),
    location: location,
    description: plainText(description),
    date: published,
    date_kind: published ? kind : "unknown",
    deadline: null,
    provider: b.provider,
    company_id: c.id,
  }
}

export async function fetchPage(c: Company, b: Board, query: string, page: number, read: JsonReader): Promise<Page> {
  const offset = (page - 1) * b.pageSize
  let data: any, list: any[], total: number | undefined
  const job = (id: any, title: any, url: any, loc: string, desc: any, date: any, kind: Job["date_kind"] = "published") => makeJob(c, b, id, title, url, loc, desc, date, kind)
  let normalized: Array<Job | null>
  if (b.provider === "meituan") {
    data = await read(b.api, { page: { pageNo: page, pageSize: b.pageSize }, keywords: query,
      jobShareType: "1", jobType: [{ code: "3", subCode: [] }], cityList: [], department: [], jfJgList: [], typeCode: [], specialCode: [] })
    list = data?.data?.list; total = Number(data?.data?.page?.totalCount)
    if (data?.success === false || !Array.isArray(list)) throw new Error("美团列表格式改变或接口报错")
    normalized = rows(list).map(p => job(p.jobUnionId, p.name, `${b.origin}/web/position/detail?jobUnionId=${encodeURIComponent(p.jobUnionId)}`,
      names(p.cityList), [p.jobDuty, p.jobRequirement].filter(Boolean).join("\n"), p.refreshTime ?? p.firstPostTime, p.refreshTime ? "refreshed" : "published"))
  } else if (b.provider === "feishu") {
    data = await read(b.api, { limit: b.pageSize, offset, keyword: query })
    list = data?.data?.job_post_list; total = Number(data?.data?.count)
    if (data?.code !== 0 || !Array.isArray(list)) throw new Error(`飞书招聘接口错误或格式改变：code=${data?.code}`)
    normalized = rows(list).map(p => job(p.id, p.title, `${b.origin}/${b.origin === "https://jobs.bytedance.com" ? "experienced" : "index"}/position/${encodeURIComponent(p.id)}/detail`,
      names(p.city_list), [p.recruit_type?.name, p.description, p.requirement].filter(Boolean).join("\n"), p.publish_time))
  } else if (b.provider === "moka") {
    data = decryptMoka(await read(b.api, { siteId: b.siteId, orgId: b.slug, locale: "zh-CN", limit: b.pageSize, offset, ...(query ? { keyword: query } : {}) }))
    list = data?.data?.jobs
    if (data?.success === false || !Array.isArray(list)) throw new Error("Moka 列表格式改变或接口报错")
    normalized = rows(list).map(p => job(p.id, p.title, `${b.base}#/job/${encodeURIComponent(p.id)}`,
      Array.isArray(p.locations) ? p.locations.map((l: any) => [l?.provinceName, l?.cityName].filter(Boolean).join(" ")).join("/") : "",
      [p.commitment, p.jobDescription].filter(Boolean).join("\n"), p.createdAt, "created"))
  } else {
    data = await read(b.api)
    list = b.provider === "lever" ? data : data?.jobs
    if (!Array.isArray(list)) throw new Error(`${b.provider} 列表格式改变或接口报错`)
    if (b.provider === "greenhouse") normalized = rows(list).map(p => job(p.id, p.title, p.absolute_url, p.location?.name ?? "", p.content, p.first_published))
    else if (b.provider === "lever") normalized = rows(list).map(p => job(p.id, p.text, p.hostedUrl,
      [...new Set([p.categories?.location, ...(p.categories?.allLocations ?? [])].filter(Boolean))].join("/"),
      [p.descriptionPlain, ...(p.lists ?? []).map((l: any) => `${l.text ?? ""} ${l.content ?? ""}`), p.additionalPlain].filter(Boolean).join("\n"), p.createdAt, "created"))
    else normalized = rows(list).filter(p => p.isListed !== false).map(p => job(p.id, p.title, p.jobUrl,
      [...new Set([p.location, ...(p.secondaryLocations ?? []).flatMap((l: any) => [l.location, l.address?.postalAddress?.addressLocality, l.address?.postalAddress?.addressCountry]),
        (p.workplaceType ? p.workplaceType.toLowerCase() === "remote" : p.isRemote) ? "Remote" : null].filter(Boolean))].join("/"), p.descriptionPlain, p.publishedAt))
  }
  // A full raw page containing a malformed row must not stop pagination early.
  const more = b.paged && (Number.isFinite(total) && total! > 0 ? offset + list.length < total! : list.length >= b.pageSize)
  if (!list.length && Number.isFinite(total) && total! > offset) throw new Error("接口报告还有岗位却返回空页；结果不完整")
  return { jobs: normalized.filter((j): j is Job => j !== null), rawCount: list.length, malformed: normalized.filter(j => j === null).length, more }
}
