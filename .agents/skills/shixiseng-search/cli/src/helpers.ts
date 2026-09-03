// Shared plumbing for the shixiseng-search CLI.
// Data source: www.shixiseng.com Nuxt SSR pages (public, no login for reads).
// The site's list/detail pages embed the page state as a `window.__NUXT__`
// IIFE; we evaluate that IIFE inside a sandboxed `node:vm` context and
// JSON-serialize the resulting state tree, then walk it defensively (site
// layout changes get caught by the finders, not by a hard-coded path).

import vm from "node:vm"

export const HONEST_UA = "Mozilla/5.0 (compatible; shixiseng-search-cli/1.0; personal-use)"

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

/** Proxy URL from env vars, or from the Windows registry (Clash etc. set it there). */
export function systemProxy(): string | undefined {
  const env =
    process.env.HTTPS_PROXY || process.env.https_proxy || process.env.HTTP_PROXY || process.env.http_proxy
  if (env) return env
  if (process.platform !== "win32") return undefined
  try {
    const r = Bun.spawnSync(
      ["reg", "query", "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings", "/v", "ProxyEnable"],
      { stdout: "pipe", stderr: "pipe" },
    )
    const enable = r.stdout.toString("utf-8").match(/ProxyEnable\s+REG_DWORD\s+0x([0-9a-f]+)/i)
    if (!enable || parseInt(enable[1], 16) === 0) return undefined
    const r2 = Bun.spawnSync(
      ["reg", "query", "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings", "/v", "ProxyServer"],
      { stdout: "pipe", stderr: "pipe" },
    )
    const server = r2.stdout.toString("utf-8").match(/ProxyServer\s+REG_SZ\s+(\S+)/i)
    if (!server || !server[1]) return undefined
    const raw = server[1]
    return /^https?:\/\//.test(raw) ? raw : `http://${raw}`
  } catch {
    return undefined
  }
}

let dispatcherCache: unknown | null | undefined

function dispatcher(): any {
  if (dispatcherCache !== undefined) return dispatcherCache
  const proxy = systemProxy()
  dispatcherCache = proxy && typeof (Bun as any).ProxyAgent === "function" ? new (Bun as any).ProxyAgent(proxy) : null
  return dispatcherCache ?? undefined
}

/**
 * GET a page: direct connection first, then the system proxy (Clash may be
 * down; Chinese-market sites are reachable directly). Retries transient
 * failures (429/5xx) with exponential backoff + jitter.
 */
export async function fetchPage(url: string, extraHeaders: Record<string, string> = {}): Promise<string> {
  let lastErr: Error | null = null
  for (const useProxy of [false, true]) {
    try {
      return await fetchPageOnce(url, extraHeaders, useProxy ? dispatcher() : undefined)
    } catch (e) {
      lastErr = e instanceof Error ? e : new Error(String(e))
      if (lastErr.message.includes("request failed: 4")) throw lastErr
    }
  }
  throw lastErr ?? new Error("shixiseng.com request failed")
}

async function fetchPageOnce(url: string, extraHeaders: Record<string, string>, d: any): Promise<string> {
  const maxRetries = 6
  let delay = 500
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    let res: Response
    try {
      res = await fetch(url, {
        headers: { "User-Agent": HONEST_UA, Accept: "text/html,application/xhtml+xml", ...extraHeaders },
        dispatcher: d,
        redirect: "follow",
        signal: AbortSignal.timeout(20000),
      } as any)
    } catch (e) {
      throw new Error(`could not reach shixiseng.com (${e instanceof Error ? e.message : String(e)})`)
    }
    if (res.status === 429 || res.status >= 500) {
      if (attempt === maxRetries) throw new Error(`shixiseng.com request failed: ${res.status} ${res.statusText}`)
      await sleep(delay + Math.floor(Math.random() * 500))
      delay = Math.min(delay * 2, 8000)
      continue
    }
    if (!res.ok) throw new Error(`shixiseng.com request failed: ${res.status} ${res.statusText}`)
    return await res.text()
  }
  throw new Error("shixiseng.com request failed after retries")
}

/**
 * Evaluate the `window.__NUXT__ = (...)()` IIFE in a locked-down vm context and
 * return the deserialized state tree. `null` when the page carries no state
 * (e.g. an error page or a CAPTCHA interstitial that still returns 200).
 */
export function extractNuxtState(html: string): unknown {
  const m = html.match(/window\.__NUXT__\s*=\s*([\s\S]*?)\s*<\/script>/)
  if (!m) return null
  const expr = m[1]
  const ctx: any = { window: {} }
  vm.createContext(ctx)
  try {
    const out = vm.runInContext(
      `window.__NUXT__ = ${expr}; JSON.stringify(window.__NUXT__);`,
      ctx,
      { timeout: 3000, codeGeneration: { strings: false, wasm: false } } as any,
    ) as string
    return JSON.parse(out)
  } catch {
    return null
  }
}

/** Depth-first walk of a JSON tree, invoking `visit` on every object/array node. */
export function walkTree(node: unknown, visit: (n: unknown) => void): void {
  if (Array.isArray(node)) {
    visit(node)
    for (const item of node) walkTree(item, visit)
  } else if (node && typeof node === "object") {
    visit(node)
    for (const key of Object.keys(node as Record<string, unknown>)) {
      walkTree((node as Record<string, unknown>)[key], visit)
    }
  }
}

/** Find the first object in the state tree with a non-empty `cname`. */
export function findInternObject(state: unknown): Record<string, unknown> | null {
  let found: Record<string, unknown> | null = null
  walkTree(state, (n) => {
    if (found) return
    if (n && typeof n === "object" && !Array.isArray(n)) {
      const o = n as Record<string, unknown>
      if (typeof o.cname === "string" && o.cname.length > 0) found = o
    }
  })
  return found
}

/** Find the list array: an array whose first element has a `uuid` string starting with `inn_`. */
export function findInternList(state: unknown): unknown[] | null {
  let found: unknown[] | null = null
  walkTree(state, (n) => {
    if (found) return
    if (Array.isArray(n) && n.length > 0) {
      const first = n[0] as Record<string, unknown>
      if (first && typeof first.uuid === "string" && first.uuid.startsWith("inn_")) found = n
    }
  })
  return found
}

/** Normalize the various date shapes the site emits into YYYY-MM-DD, or null. */
export function normalizeDate(raw: unknown): string | null {
  if (typeof raw !== "string" && typeof raw !== "number") return null
  const s = String(raw).trim()
  if (!s) return null
  let m = s.match(/^(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})/)
  if (m) return `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}`
  m = s.match(/^(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})/)
  if (m) return `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}`
  m = s.match(/^(\d{1,2})-(\d{1,2})$/)
  if (m) return null // month-day only: no year, unusable for jobage
  if (/^\d{9,13}$/.test(s)) {
    const d = new Date(Number(s) > 1e12 ? Number(s) : Number(s) * 1000)
    if (!isNaN(d.getTime())) return d.toISOString().slice(0, 10)
  }
  return null
}

const TEXT_NODES = new Set(["name", "cname", "city", "degree", "industry", "chance"])

export function decodeEntities(text: string): string {
  return text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&semi;/g, ";")
    .replace(/&#(\d+);?/g, (_, dec) => String.fromCodePoint(parseInt(dec, 10)))
    .replace(/&#[xX]([0-9a-fA-F]+);?/g, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&nbsp;/g, " ")
}

/** Strip private-use-area icon glyphs the site embeds in titles/salary codes. */
export function stripPua(text: string): string {
  return [...text]
    .filter((ch) => {
      const c = ch.codePointAt(0) ?? 0
      return !((c >= 0xe000 && c <= 0xf8ff) || (c >= 0xf0000 && c <= 0xffffd))
    })
    .join("")
    .replace(/\s+/g, " ")
    .trim()
}

/** Strip HTML tags/entities into readable prose (block tags become newlines). */
export function cleanHtml(html: string | null | undefined): string | null {
  if (!html) return null
  const withBreaks = html
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(/<\/(p|li|ul|ol|div|h\d|tr)>/gi, "\n")
  const text = decodeEntities(withBreaks.replace(/<[^>]+>/g, " "))
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
  return text || null
}

/** A job list item normalized to the portal-skill contract shape. */
export interface ShixisengResult {
  id: string
  title: string
  company: string | null
  location: string | null
  date: string | null
  url: string
  salary: string | null
}

/** Map one raw intern object into the contract result shape. */
export function toResult(raw: Record<string, unknown>): ShixisengResult | null {
  const uuid = typeof raw.uuid === "string" ? raw.uuid : null
  const title = typeof raw.name === "string" ? stripPua(decodeEntities(raw.name)) : ""
  if (!uuid || !title) return null
  const min = typeof raw.minsalary === "number" ? raw.minsalary : null
  const max = typeof raw.maxsalary === "number" ? raw.maxsalary : null
  return {
    id: uuid,
    title,
    company: typeof raw.cname === "string" ? decodeEntities(raw.cname) : null,
    location: typeof raw.city === "string" ? decodeEntities(raw.city) : null,
    date: normalizeDate(raw.refresh ?? raw.day),
    url: `https://www.shixiseng.com/intern/${uuid}`,
    salary: min != null && max != null ? `${min}-${max}` : min != null ? String(min) : null,
  }
}

/** Extract text from a detail object's description/requirement-ish fields. */
export function detailText(obj: Record<string, unknown>): string | null {
  const parts: string[] = []
  for (const key of ["description", "job_desc", "jobDescription", "position_desc", "require", "requirement", "tip"]) {
    const v = obj[key]
    if (typeof v === "string" && v.trim()) parts.push(cleanHtml(v) ?? "")
  }
  const joined = parts.join("\n\n").trim()
  return joined || null
}

const _unusedTextNodes = TEXT_NODES
void _unusedTextNodes
