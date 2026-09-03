export const DEFAULT_TENANT = "SU64365a780dcad43c5ae82bab"
export const DEFAULT_COMPANY = "德勤"
export const HONEST_UA = "Mozilla/5.0 (compatible; hotjob-search-cli/1.0; personal-use)"

export interface HotjobPost {
  postId?: string
  postName?: string
  company?: string
  department?: string
  workPlaceStr?: string
  publishDate?: string
  endDate?: string
  postTypeName?: string
  projectName?: string
  postCode?: string
  workContent?: string
  serviceCondition?: string
  education?: string
  gender?: string
  canDelivery?: boolean
  showDeliverButton?: number
  applyPositionButtonStatus?: number | string
}

function systemProxy(): string | undefined {
  const env = process.env.HTTPS_PROXY || process.env.https_proxy || process.env.HTTP_PROXY || process.env.http_proxy
  if (env) return env
  if (process.platform !== "win32") return undefined
  try {
    const enabled = Bun.spawnSync(
      ["reg", "query", "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings", "/v", "ProxyEnable"],
      { stdout: "pipe", stderr: "pipe" },
    ).stdout.toString("utf-8").match(/ProxyEnable\s+REG_DWORD\s+0x([0-9a-f]+)/i)
    if (!enabled || parseInt(enabled[1], 16) === 0) return undefined
    const server = Bun.spawnSync(
      ["reg", "query", "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings", "/v", "ProxyServer"],
      { stdout: "pipe", stderr: "pipe" },
    ).stdout.toString("utf-8").match(/ProxyServer\s+REG_SZ\s+(\S+)/i)
    if (!server?.[1]) return undefined
    return /^https?:\/\//.test(server[1]) ? server[1] : `http://${server[1]}`
  } catch {
    return undefined
  }
}

let dispatcherCache: unknown | null | undefined

function proxyDispatcher(): any {
  if (dispatcherCache !== undefined) return dispatcherCache ?? undefined
  const proxy = systemProxy()
  dispatcherCache = proxy && typeof (Bun as any).ProxyAgent === "function" ? new (Bun as any).ProxyAgent(proxy) : null
  return dispatcherCache ?? undefined
}

export async function apiPost<T>(path: string, tenant: string, data: Record<string, string>): Promise<T> {
  const url = `https://wecruit.hotjob.cn/wecruit${path}/${encodeURIComponent(tenant)}`
  let lastError: Error | null = null
  for (const dispatcher of [undefined, proxyDispatcher()]) {
    if (dispatcher === undefined && lastError && !proxyDispatcher()) break
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "User-Agent": HONEST_UA,
          Accept: "application/json, text/plain, */*",
          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
          Referer: `https://wecruit.hotjob.cn/${tenant}/pb/interns.html`,
        },
        body: new URLSearchParams(data),
        dispatcher,
        redirect: "follow",
        signal: AbortSignal.timeout(20_000),
      } as any)
      if (response.status === 429) throw new Error("Hotjob API rate limited this request (HTTP 429)")
      if (!response.ok) throw new Error(`Hotjob API request failed: ${response.status} ${response.statusText}`)
      const body = await response.json().catch(() => null)
      if (!body || typeof body !== "object") throw new Error("Hotjob API returned an unparseable response")
      return body as T
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error))
      if (lastError.message.includes("429") || /request failed: 4\d\d/.test(lastError.message)) throw lastError
    }
  }
  throw lastError ?? new Error("Hotjob API request failed")
}

export function normalizeTenant(input: string | undefined): string | null {
  if (!input) return DEFAULT_TENANT
  const match = input.trim().match(/(?:^|\/)(SU[a-zA-Z0-9]+)(?:\/|$)/) || input.trim().match(/^(SU[a-zA-Z0-9]+)$/)
  return match?.[1] ?? null
}

export function normalizePostId(input: string): string | null {
  const text = input.trim()
  const match = text.match(/[?&]postId=([a-f0-9]{24})(?:&|$)/i)
  if (match) return match[1].toLowerCase()
  return /^[a-f0-9]{24}$/i.test(text) ? text.toLowerCase() : null
}

export function canonicalUrl(postId: string, tenant = DEFAULT_TENANT): string {
  return `https://wecruit.hotjob.cn/${tenant}/pb/posDetail.html?postId=${encodeURIComponent(postId)}&postType=intern`
}

export function normalizeDate(raw: unknown): string | null {
  if (typeof raw !== "string") return null
  const match = raw.trim().match(/^(\d{4})-(\d{1,2})-(\d{1,2})/)
  return match ? `${match[1]}-${match[2].padStart(2, "0")}-${match[3].padStart(2, "0")}` : null
}

export function chinaToday(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date())
}

export function isExpired(deadline: string | null, today = chinaToday()): boolean {
  return Boolean(deadline && deadline < today)
}

export function cleanText(value: unknown): string | null {
  if (typeof value !== "string") return null
  const clean = value.replace(/\r\n/g, "\n").replace(/\r/g, "\n").replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim()
  return clean || null
}
