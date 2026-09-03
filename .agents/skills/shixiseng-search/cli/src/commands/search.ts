import {
  fetchPage,
  extractNuxtState,
  findInternList,
  toResult,
  normalizeDate,
  type ShixisengResult,
} from "../helpers.js"

export interface SearchOpts {
  query: string
  location?: string
  page: number
  limit: number
  jobage?: number
  format: "json" | "table" | "plain"
}

export interface SearchOutput {
  meta: { count: number; page: number }
  results: ShixisengResult[]
}

/**
 * Fetch + normalize one search page. `optsWithoutFormat` treats the format as
 * irrelevant (used by sync_seen.ts which wants data, not rendering). Errors are
 * surfaced as throws; the CLI wrapper maps them to the stderr JSON contract.
 */
export async function fetchSearch(opts: SearchOpts): Promise<SearchOutput> {
  const params = new URLSearchParams({ keyword: opts.query })
  if (opts.location) params.set("city", opts.location)
  params.set("page", String(opts.page))
  const url = `https://www.shixiseng.com/interns?${params.toString()}`

  const html = await fetchPage(url)
  const state = extractNuxtState(html)
  if (!state) {
    throw new Error(
      "shixiseng.com returned a page without search state (CAPTCHA? error page? try again later or check url-reference.md)",
    )
  }
  const interns = (state as { data?: Array<{ interns?: { data?: unknown[]; total?: number } }> }).data?.[0]?.interns
  const rawList = Array.isArray(interns?.data) ? interns.data : findInternList(state)
  if (!rawList || rawList.length === 0) {
    return { meta: { count: 0, page: opts.page }, results: [] }
  }

  const now = Date.now()
  const results: ShixisengResult[] = []
  for (const raw of rawList) {
    const r = toResult(raw as Record<string, unknown>)
    if (!r) continue
    // The site's city param is loose (mixes 全国/remote rows in): filter
    // client-side to the requested city when one was given.
    if (opts.location && r.location && !r.location.includes(opts.location)) continue
    if (opts.jobage && r.date) {
      const dt = Date.parse(r.date)
      if (isNaN(dt) || now - dt > opts.jobage * 86400_000) continue
    }
    results.push(r)
    if (results.length >= opts.limit) break
  }

  return { meta: { count: interns?.total ?? results.length, page: opts.page }, results }
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
        code: e instanceof Error && e.message.includes("without search state") ? "NO_STATE" : "SEARCH_FAILED",
      }) + "\n",
    )
    return 1
  }
}

function pad(s: string, w: number): string {
  const visible = [...s].reduce((acc, ch) => acc + (ch.charCodeAt(0) > 0xff ? 2 : 1), 0)
  return s + " ".repeat(Math.max(0, w - visible))
}

function printOutput(out: SearchOutput, format: "json" | "table" | "plain"): void {
  if (format === "json") {
    process.stdout.write(JSON.stringify(out, null, 2) + "\n")
    return
  }
  if (format === "plain") {
    for (const r of out.results) {
      process.stdout.write(
        `${r.title} — ${r.company ?? "—"} · ${r.location ?? "—"}${r.salary ? ` · ${r.salary}/天` : ""}${r.date ? ` · ${r.date}` : ""}\n  ${r.url}\n`,
      )
    }
    process.stdout.write(`\n${out.results.length} results (total ${out.meta.count}, page ${out.meta.page})\n`)
    return
  }
  process.stdout.write(`${pad("#", 4)}${pad("Title", 34)}${pad("Company", 22)}${pad("City", 12)}${pad("Salary/天", 12)}URL\n`)
  out.results.forEach((r, i) => {
    process.stdout.write(
      `${pad(String(i + 1), 4)}${pad(r.title, 34)}${pad(r.company ?? "—", 22)}${pad(r.location ?? "—", 12)}${pad(r.salary ?? "—", 12)}${r.url}\n`,
    )
  })
  process.stdout.write(`\n${out.results.length} results (total ${out.meta.count}, page ${out.meta.page})\n`)
}

export const _normalizeDateForTests = normalizeDate
