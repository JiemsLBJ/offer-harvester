import {
  apiPost, canonicalUrl, chinaToday, DEFAULT_COMPANY, DEFAULT_TENANT, isExpired, normalizeDate,
  type HotjobPost,
} from "../helpers.js"

export interface SearchOpts {
  query: string
  location?: string
  jobage?: number
  page: number
  limit: number
  format: "json" | "table" | "plain"
  tenant?: string
  company?: string
}

export interface HotjobResult {
  id: string
  title: string
  company: string
  location: string | null
  date: string | null
  deadline: string | null
  url: string
  business_unit: string | null
  department: string | null
  category: string | null
  project_name: string | null
  post_code: string | null
}

interface SearchResponse {
  state?: string
  msg?: string
  data?: {
    pageForm?: {
      dataCount?: number
      totalPage?: number
      currentPage?: number
      pageData?: HotjobPost[]
    }
  }
}

export function toResult(post: HotjobPost, tenant = DEFAULT_TENANT, employer = DEFAULT_COMPANY): HotjobResult | null {
  if (!post.postId || !post.postName) return null
  const deadline = normalizeDate(post.endDate)
  if (isExpired(deadline)) return null
  return {
    id: post.postId,
    title: post.postName.trim(),
    company: employer,
    location: post.workPlaceStr?.trim() || null,
    date: normalizeDate(post.publishDate),
    deadline,
    url: canonicalUrl(post.postId, tenant),
    business_unit: post.company?.trim() || null,
    department: post.department?.trim() || null,
    category: post.postTypeName?.trim() || null,
    project_name: post.projectName?.trim() || null,
    post_code: post.postCode?.trim() || null,
  }
}

export async function fetchSearch(opts: SearchOpts): Promise<{ meta: { count: number; page: number; tenant: string }; results: HotjobResult[] }> {
  const tenant = opts.tenant || DEFAULT_TENANT
  const employer = opts.company || DEFAULT_COMPANY
  const pageSize = Math.min(100, Math.max(20, opts.limit))
  const body = await apiPost<SearchResponse>("/positionInfo/listPosition", tenant, {
    isFrompb: "true",
    recruitType: "12",
    pageSize: String(pageSize),
    currentPage: String(opts.page),
    postName: opts.query,
  })
  if (body.state !== "200") throw new Error(`Hotjob search answered state=${body.state ?? "none"}${body.msg ? `: ${body.msg}` : ""}`)
  const pageForm = body.data?.pageForm
  const now = Date.now()
  const results: HotjobResult[] = []
  for (const post of pageForm?.pageData ?? []) {
    const result = toResult(post, tenant, employer)
    if (!result) continue
    if (opts.location && !result.location?.includes(opts.location)) continue
    if (opts.jobage !== undefined) {
      if (!result.date) continue
      const published = Date.parse(`${result.date}T00:00:00+08:00`)
      if (Number.isNaN(published) || now - published > opts.jobage * 86_400_000) continue
    }
    results.push(result)
    if (results.length >= opts.limit) break
  }
  return { meta: { count: pageForm?.dataCount ?? results.length, page: pageForm?.currentPage ?? opts.page, tenant }, results }
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    const output = await fetchSearch(opts)
    printOutput(output, opts.format)
    return 0
  } catch (error) {
    process.stderr.write(JSON.stringify({
      error: error instanceof Error ? error.message : String(error), code: "SEARCH_FAILED",
    }) + "\n")
    return 1
  }
}

function pad(value: string, width: number): string {
  const visible = [...value].reduce((total, char) => total + (char.charCodeAt(0) > 0xff ? 2 : 1), 0)
  return value + " ".repeat(Math.max(0, width - visible))
}

function printOutput(
  output: { meta: { count: number; page: number; tenant: string }; results: HotjobResult[] },
  format: SearchOpts["format"],
): void {
  if (format === "json") {
    process.stdout.write(JSON.stringify(output, null, 2) + "\n")
    return
  }
  if (format === "plain") {
    for (const result of output.results) {
      process.stdout.write(`${result.title} — ${result.company} · ${result.location ?? "—"}${result.deadline ? ` · 截止 ${result.deadline}` : ""}\n  ${result.url}\n`)
    }
    process.stdout.write(`\n${output.results.length} results (total ${output.meta.count}, page ${output.meta.page})\n`)
    return
  }
  process.stdout.write(`${pad("#", 4)}${pad("Title", 44)}${pad("Location", 24)}${pad("Deadline", 12)}URL\n`)
  output.results.forEach((result, index) => {
    process.stdout.write(`${pad(String(index + 1), 4)}${pad(result.title, 44)}${pad(result.location ?? "—", 24)}${pad(result.deadline ?? "—", 12)}${result.url}\n`)
  })
  process.stdout.write(`\n${output.results.length} results (total ${output.meta.count}, page ${output.meta.page})\n`)
}
