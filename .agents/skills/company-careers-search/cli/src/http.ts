// Public, low-volume requests only. No browser impersonation, cookie solving,
// proxy rotation or retries on protection/rate-limit responses. API redirects
// are refused; only robots.txt may follow bounded same-origin redirects.
export type Transport = (url: string, init?: RequestInit) => Promise<Response>
const UA = "OfferHarvester/1.0 (personal public job search)"
const wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

export function publicUrl(value: string): URL {
  const u = new URL(value)
  if (u.protocol !== "https:" || u.username || u.password || u.port)
    throw new Error("仅支持无凭据、默认端口的 HTTPS 官网 URL")
  return u
}

// RFC-style group selection, longest matching path, Allow wins equal lengths.
export function robotsAllows(text: string, target: URL): boolean {
  const groups: Array<{ agents: string[]; rules: Array<{ allow: boolean; path: string }> }> = []
  let group: typeof groups[number] | undefined
  let hasRules = false
  for (const line of text.split(/\r?\n/)) {
    const match = /^\s*([\w-]+)\s*:\s*(.*?)\s*$/.exec(line.split("#")[0])
    if (!match) continue
    const [, key, value] = match
    if (key.toLowerCase() === "user-agent") {
      if (!group || hasRules) { group = { agents: [], rules: [] }; groups.push(group); hasRules = false }
      group.agents.push(value.toLowerCase())
    } else if (group) {
      hasRules = true
      if (/^(allow|disallow)$/i.test(key) && value) group.rules.push({ allow: /^allow$/i.test(key), path: value })
    }
  }
  const score = (g: typeof groups[number]) => Math.max(-1, ...g.agents.map(a => a === "*" ? 0 : "offerharvester".includes(a) ? a.length : -1))
  const best = Math.max(-1, ...groups.map(score))
  let length = -1, allowed = true
  for (const g of groups.filter(g => score(g) === best && best >= 0)) {
    for (const rule of g.rules) {
      const end = rule.path.endsWith("$")
      const path = end ? rule.path.slice(0, -1) : rule.path
      const pattern = path.split("*").map(p => p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join(".*")
      if (new RegExp("^" + pattern + (end ? "$" : "")).test(target.pathname + target.search)) {
        const n = path.replaceAll("*", "").length
        if (n > length || (n === length && rule.allow)) { length = n; allowed = rule.allow }
      }
    }
  }
  return allowed
}

export class PublicClient {
  private robots = new Map<string, Promise<string>>()
  private last = new Map<string, number>()
  constructor(private transport: Transport = fetch, private pause = wait) {}
  private async request(url: string, init: RequestInit = {}, cap = 32_000_000, robotsRedirects = 0): Promise<{ status: number; text: string }> {
    const u = publicUrl(url)
    const delay = 400 - (Date.now() - (this.last.get(u.origin) ?? 0))
    if (delay > 0) await this.pause(delay)
    this.last.set(u.origin, Date.now())
    const response = await this.transport(url, { ...init, redirect: robotsRedirects ? "manual" : "error", signal: AbortSignal.timeout(30_000),
      headers: { "user-agent": UA, "accept": "application/json,text/plain", ...init.headers } })
    if (robotsRedirects && response.status >= 300 && response.status < 400) {
      const location = response.headers.get("location")
      await response.body?.cancel()
      if (!location || robotsRedirects === 1) throw new Error("robots.txt 重定向过多或缺少 Location")
      const target = publicUrl(new URL(location, u).href)
      if (target.origin !== u.origin) throw new Error("robots.txt 跳转到其他主机，停止并交人工核验")
      return this.request(target.href, {}, cap, robotsRedirects - 1)
    }
    if (response.status !== 404 && !response.ok) { await response.body?.cancel(); throw new Error(`HTTP ${response.status}：停止该来源，不重试或绕过验证`) }
    if (Number(response.headers.get("content-length")) > cap) { await response.body?.cancel(); throw new Error("响应超过安全大小限制") }
    const reader = response.body?.getReader()
    if (!reader) return { status: response.status, text: "" }
    const chunks: Uint8Array[] = []; let size = 0
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        size += value.byteLength
        if (size > cap) throw new Error("响应超过安全大小限制")
        chunks.push(value)
      }
    } finally { await reader.cancel() }
    return { status: response.status, text: Buffer.concat(chunks).toString("utf8") }
  }
  async check(url: string): Promise<void> {
    const u = publicUrl(url)
    if (!this.robots.has(u.origin)) this.robots.set(u.origin, this.request(`${u.origin}/robots.txt`, {}, 500_000, 4).then(r => {
      if (r.status === 404) return ""
      if (/verify you are human|access denied|人机验证|cf-chl|acw_sc__v2/i.test(r.text)) throw new Error("robots.txt 返回验证页，停止该来源")
      // Some SPAs (e.g. Meituan) redirect absent robots.txt to the normal
      // homepage. HTML is not robots directives; it does not grant API access.
      if (/<!doctype html|<html/i.test(r.text)) return ""
      return r.text
    }))
    if (!robotsAllows(await this.robots.get(u.origin)!, u)) throw new Error("robots.txt 不允许抓取该路径")
  }
  async json(url: string, body?: unknown): Promise<any> {
    await this.check(url)
    const r = await this.request(url, body === undefined ? {} : {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    })
    if (r.status === 404) throw new Error("HTTP 404：招聘接口不存在")
    try { return JSON.parse(r.text) } catch { throw new Error("接口没有返回 JSON（可能需要登录或验证），停止该来源") }
  }
}
