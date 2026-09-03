// Shared plumbing for the tencent-search CLI.
// Data source: the careers.tencent.com public JSON API (no login for reads).

export const HONEST_UA = "Mozilla/5.0 (compatible; tencent-search-cli/1.0; personal-use)"

export interface TencentPost {
  PostId: string
  RecruitPostId?: number
  RecruitPostName: string
  CountryName?: string
  LocationName?: string
  BGName?: string
  ComCode?: string
  ComName?: string
  ProductName?: string
  CategoryName?: string
  RequireWorkYearsName?: string
  Responsibility?: string
  Requirement?: string
  Introduction?: string
  LastUpdateTime?: string
  PostURL?: string
  SourceID?: number
  IsValid?: boolean
}

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

/** Proxy URL from env vars, or the Windows registry (Clash etc.). */
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
 * GET the tencent careers JSON API: direct connection first, then the system
 * proxy (Clash may be down). Retries transient failures (429/5xx) with backoff;
 * `null` when the API answers with a non-200 Code (invalid params).
 */
export async function apiGet(url: string): Promise<{ Code: number; Data: unknown } | null> {
  let lastErr: Error | null = null
  for (const useProxy of [false, true]) {
    try {
      return await apiGetOnce(url, useProxy ? dispatcher() : undefined)
    } catch (e) {
      lastErr = e instanceof Error ? e : new Error(String(e))
      if (lastErr.message.includes("request failed: 4")) throw lastErr
    }
  }
  throw lastErr ?? new Error("tencent API request failed")
}

async function apiGetOnce(url: string, d: any): Promise<{ Code: number; Data: unknown } | null> {
  const maxRetries = 5
  let delay = 500
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    let res: Response
    try {
      res = await fetch(url, {
        headers: {
          "User-Agent": HONEST_UA,
          Accept: "application/json, text/plain, */*",
          Referer: "https://careers.tencent.com/",
        },
        dispatcher: d,
        redirect: "follow",
        signal: AbortSignal.timeout(20000),
      } as any)
    } catch (e) {
      throw new Error(`could not reach careers.tencent.com (${e instanceof Error ? e.message : String(e)})`)
    }
    if (res.status === 429 || res.status >= 500) {
      if (attempt === maxRetries) throw new Error(`tencent API request failed: ${res.status} ${res.statusText}`)
      await sleep(delay + Math.floor(Math.random() * 500))
      delay = Math.min(delay * 2, 8000)
      continue
    }
    if (!res.ok) throw new Error(`tencent API request failed: ${res.status} ${res.statusText}`)
    const body = (await res.json().catch(() => null)) as { Code?: number; Data?: unknown } | null
    if (!body) throw new Error("tencent API returned an unparseable response body")
    return { Code: body.Code ?? 0, Data: body.Data ?? null }
  }
  throw new Error("tencent API request failed after retries")
}

/** Normalize "2026年08月10日" (and other shapes) into YYYY-MM-DD, or null. */
export function normalizeDate(raw: unknown): string | null {
  if (typeof raw !== "string") return null
  const s = raw.trim()
  if (!s) return null
  const m = s.match(/^(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})/)
  if (m) return `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}`
  const iso = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/)
  if (iso) return `${iso[1]}-${iso[2].padStart(2, "0")}-${iso[3].padStart(2, "0")}`
  return null
}

/** Strip the site's odd HTML escapes (`&semi;` etc.) and tags into prose. */
export function cleanHtml(html: string | null | undefined): string | null {
  if (!html) return null
  const withBreaks = html
    .replace(/<[^>]+>/g, "\n")
    .replace(/&semi;/g, ";")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
  return withBreaks || null
}

export function canonicalUrl(postId: string): string {
  return `https://careers.tencent.com/jobdesc.html?postId=${encodeURIComponent(postId)}`
}

export function normalizeId(input: string): string | null {
  const t = input.trim()
  const m = t.match(/postId=(\d+)/)
  if (m) return m[1]
  if (/^\d{10,20}$/.test(t)) return t
  return null
}
