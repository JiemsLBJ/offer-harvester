import { apiGet, normalizeDate, canonicalUrl, type TencentPost } from "../helpers.js"

export interface SearchOpts {
  query: string
  location?: string
  page: number
  limit: number
  jobage?: number
  format: "json" | "table" | "plain"
}

export interface TencentResult {
  id: string
  title: string
  company: string | null
  location: string | null
  date: string | null
  url: string
  business_group: string | null
  category: string | null
  product: string | null
  require_years: string | null
}

interface QueryResponse {
  Code: number
  Data: { Count: number; Posts: TencentPost[] } | null
}

export function toResult(p: TencentPost): TencentResult | null {
  if (!p.PostId || !p.RecruitPostName) return null
  const location = [p.CountryName, p.LocationName].filter(Boolean).join(" · ") || null
  return {
    id: p.PostId,
    title: p.RecruitPostName,
    company: p.ComName || "腾讯",
    location,
    date: normalizeDate(p.LastUpdateTime),
    url: canonicalUrl(p.PostId),
    business_group: p.BGName || null,
    category: p.CategoryName || null,
    product: p.ProductName || null,
    require_years: p.RequireWorkYearsName || null,
  }
}

/** Fetch + normalize one search page. Errors throw; the CLI wrapper reports them. */
export async function fetchSearch(opts: SearchOpts): Promise<{ meta: { count: number; page: number }; results: TencentResult[] }> {
  const params = new URLSearchParams({
    timestamp: String(Date.now()),
    countryId: "",
    cityId: "",
    bgIds: "",
    productId: "",
    categoryId: "",
    parentCategoryId: "",
    attrId: "",
    keyword: opts.query,
    pageIndex: String(opts.page),
    pageSize: "100",
    language: "zh-cn",
    area: "cn",
  })
  const url = `https://careers.tencent.com/tencentcareer/api/post/Query?${params.toString()}`

  const body = await apiGet(url)
  if (!body || body.Code !== 200) {
    throw new Error(`tencent API answered Code=${body?.Code ?? "none"}`)
  }
  const data = (body.Data as QueryResponse["Data"]) ?? { Count: 0, Posts: [] }
  const now = Date.now()
  const results: TencentResult[] = []
  for (const p of data.Posts ?? []) {
    const r = toResult(p)
    if (!r) continue
    if (opts.location && r.location && !r.location.includes(opts.location)) continue
    if (opts.jobage && r.date) {
      const dt = Date.parse(r.date)
      if (isNaN(dt) || now - dt > opts.jobage * 86400_000) continue
    }
    results.push(r)
    if (results.length >= opts.limit) break
  }
  return { meta: { count: data.Count ?? results.length, page: opts.page }, results }
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    const out = await fetchSearch(opts)
    printOutput(out, opts.format)
    return 0
  } catch (e) {
    process.stderr.write(
      JSON.stringify({
        error: e instanceof Error ? e.message : String(e),
        code: e instanceof Error && e.message.startsWith("tencent API answered") ? "API_CODE" : "SEARCH_FAILED",
      }) + "\n",
    )
    return 1
  }
}

function pad(s: string, w: number): string {
  const visible = [...s].reduce((acc, ch) => acc + (ch.charCodeAt(0) > 0xff ? 2 : 1), 0)
  return s + " ".repeat(Math.max(0, w - visible))
}

function printOutput(
  out: { meta: { count: number; page: number }; results: TencentResult[] },
  format: "json" | "table" | "plain",
): void {
  if (format === "json") {
    process.stdout.write(JSON.stringify(out, null, 2) + "\n")
    return
  }
  if (format === "plain") {
    for (const r of out.results) {
      process.stdout.write(
        `${r.title} — ${r.company ?? "—"} · ${r.location ?? "—"}${r.date ? ` · ${r.date}` : ""}${r.business_group ? ` · ${r.business_group}` : ""}\n  ${r.url}\n`,
      )
    }
    process.stdout.write(`\n${out.results.length} results (total ${out.meta.count}, page ${out.meta.page})\n`)
    return
  }
  process.stdout.write(`${pad("#", 4)}${pad("Title", 36)}${pad("Company", 12)}${pad("Location", 16)}${pad("BG", 8)}${pad("Date", 12)}URL\n`)
  out.results.forEach((r, i) => {
    process.stdout.write(
      `${pad(String(i + 1), 4)}${pad(r.title, 36)}${pad(r.company ?? "—", 12)}${pad(r.location ?? "—", 16)}${pad(r.business_group ?? "—", 8)}${pad(r.date ?? "—", 12)}${r.url}\n`,
    )
  })
  process.stdout.write(`\n${out.results.length} results (total ${out.meta.count}, page ${out.meta.page})\n`)
}
