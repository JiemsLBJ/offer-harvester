import {
  fetchPage,
  extractNuxtState,
  findInternObject,
  normalizeDate,
  decodeEntities,
  cleanHtml,
} from "../helpers.js"

export interface DetailOpts {
  id: string // an inn_... uuid or a full shixiseng URL
  format: "json" | "plain"
}

export interface ShixisengDetail {
  id: string
  title: string
  company: string | null
  location: string | null
  date: string | null
  deadline: string | null
  salary: string | null
  url: string
  degree: string | null
  daysPerWeek: number | null
  months: number | null
  industry: string | null
  address: string | null
  description: string | null
}

export function normalizeId(input: string): string | null {
  const t = input.trim()
  const m = t.match(/shixiseng\.com\/intern\/(inn_[a-z0-9]+)/)
  if (m) return m[1]
  if (/^inn_[a-z0-9]{8,20}$/i.test(t)) return t
  return null
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  const uuid = normalizeId(opts.id)
  if (!uuid) {
    process.stderr.write(JSON.stringify({ error: `could not parse an inn_... id from "${opts.id}"`, code: "BAD_ID" }) + "\n")
    return 1
  }
  try {
    const html = await fetchPage(`https://www.shixiseng.com/intern/${uuid}`)
    const state = extractNuxtState(html)
    if (!state) {
      process.stderr.write(
        JSON.stringify({ error: "detail page carried no state (404 or blocked?)", code: "NO_STATE" }) + "\n",
      )
      return 1
    }
    const o = findInternObject(state)
    if (!o) {
      process.stderr.write(JSON.stringify({ error: "could not locate the internship object on the detail page", code: "PARSE" }) + "\n")
      return 1
    }

    const str = (k: string): string | null => {
      const v = o[k]
      return typeof v === "string" && v.trim() ? decodeEntities(v.trim()) : null
    }
    const num = (k: string): number | null => {
      const v = o[k]
      return typeof v === "number" && !isNaN(v) ? v : null
    }

    const info = str("info")
    const hopeYou = Array.isArray(o.hope_you_v2)
      ? (o.hope_you_v2 as unknown[]).map((x) => (typeof x === "string" ? x : "")).filter(Boolean).join("\n")
      : ""
    const description = cleanHtml([info, hopeYou].filter(Boolean).join("\n\n"))

    const detail: ShixisengDetail = {
      id: uuid,
      title: str("iname") ?? str("name") ?? "(untitled)",
      company: str("cname"),
      location: str("city"),
      date: normalizeDate(str("refresh")),
      deadline: normalizeDate(str("endtime")),
      salary: str("salary_desc") ?? str("chance"),
      url: `https://www.shixiseng.com/intern/${uuid}`,
      degree: str("degree"),
      daysPerWeek: num("day"),
      months: num("month_num") ?? num("month"),
      industry: str("industry"),
      address: str("address"),
      description,
    }

    if (opts.format === "plain") {
      const lines = [
        detail.title,
        `${detail.company ?? "—"} · ${detail.location ?? "—"}`,
        detail.date ? `Posted: ${detail.date}` : "",
        detail.deadline ? `Deadline: ${detail.deadline}` : "",
        detail.salary ? `Salary: ${detail.salary}` : "",
        detail.degree ? `Degree: ${detail.degree}` : "",
        detail.daysPerWeek ? `Days/week: ${detail.daysPerWeek}` : "",
        detail.months ? `Months: ${detail.months}` : "",
        "",
        description ?? "(no description)",
        "",
        `URL: ${detail.url}`,
        `id: ${detail.id}`,
      ].filter((l) => l !== "")
      process.stdout.write(lines.join("\n") + "\n")
    } else {
      process.stdout.write(JSON.stringify(detail, null, 2) + "\n")
    }
    return 0
  } catch (e) {
    process.stderr.write(
      JSON.stringify({ error: e instanceof Error ? e.message : String(e), code: "DETAIL_FAILED" }) + "\n",
    )
    return 1
  }
}
