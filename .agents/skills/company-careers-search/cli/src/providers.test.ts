import { describe, expect, test } from "bun:test"
import { createCipheriv } from "node:crypto"
import { parseArgs } from "./cli.js"
import { PublicClient, robotsAllows } from "./http.js"
import { canonicalUrl, decryptMoka, fetchPage, isoDate, plainText, resolveBoard, type Company, type Job } from "./providers.js"
import { fetchSearch, integer, loadCompanies, matches, selectCompanies } from "./commands/search.js"
import { roleKey, runSync } from "../../../../../automation/sync_seen.ts"

const company = (id: string, url: string): Company => ({ id, name: id, url })
const moka = company("moka", "https://app.mokahr.com/social-recruitment/demo/123")
const feishu = company("feishu", "https://demo.jobs.feishu.cn")
const mt = company("meituan", "https://zhaopin.meituan.com/web/social")
const gh = company("gh", "https://job-boards.greenhouse.io/demo")
const lever = company("lever", "https://jobs.lever.co/demo")
const ashby = company("ashby", "https://jobs.ashbyhq.com/demo")
const noCheck = async () => {}
function envelope(data: any) {
  const key = "0123456789abcdef", cipher = createCipheriv("aes-128-cbc", Buffer.from(key), Buffer.from("de7c21ed8d6f50fe"))
  return { necromancer: key, data: Buffer.concat([cipher.update(JSON.stringify(data)), cipher.final()]).toString("base64") }
}
const posting = (id: string) => ({ id, title: "数据分析实习", city_list: [{ name: "上海" }], description: "SQL research", requirement: "Python", publish_time: 1788480000 })

describe("provider contracts", () => {
  test("detect six engines and EU Lever; reject spoofing, private URLs and unknown sites", () => {
    expect([mt, feishu, moka, gh, lever, ashby].map(c => resolveBoard(c).provider)).toEqual(["meituan", "feishu", "moka", "greenhouse", "lever", "ashby"])
    expect(resolveBoard(company("eu", "https://jobs.eu.lever.co/demo")).api).toContain("api.eu.lever.co")
    for (const url of ["http://jobs.lever.co/demo", "https://127.0.0.1/", "https://jobs.lever.co.evil.test/demo", "https://user:secret@jobs.lever.co/demo", "https://jobs.lever.co:8443/demo", "https://example.com/jobs", "https://app.mokahr.com/apply/a/0"])
      expect(() => resolveBoard(company("bad", url))).toThrow()
  })
  test("Meituan uses nested pagination and retains social-board scope", async () => {
    const out = await fetchPage(mt, resolveBoard(mt), "数据", 2, async (_, body: any) => {
      expect(body.page).toEqual({ pageNo: 2, pageSize: 100 }); expect(body.jobType[0].code).toBe("3")
      return { data: { list: [{ name: "数据实习", jobUnionId: "42", cityList: [{ name: "上海" }], jobDuty: "分析", jobRequirement: "SQL", refreshTime: 1788480000000 }], page: { totalCount: 101 } } }
    })
    expect(out.jobs[0].url).toEndWith("jobUnionId=42"); expect(out.jobs[0].date_kind).toBe("refreshed"); expect(out.more).toBe(false)
  })
  test("Feishu offsets, timestamp units, job detail route and full JD", async () => {
    const out = await fetchPage(feishu, resolveBoard(feishu), "数据", 2, async (_, body: any) => {
      expect(body.offset).toBe(100); return { code: 0, data: { job_post_list: [posting("42")], count: 101 } }
    })
    expect(out.jobs[0].url).toBe("https://demo.jobs.feishu.cn/index/position/42/detail")
    expect(out.jobs[0].description).toContain("Python"); expect(out.jobs[0].date).toStartWith("2026-")
  })
  test("Moka decodes public envelope, preserves hash ID and province/district; unknown date remains null", async () => {
    const out = await fetchPage(moka, resolveBoard(moka), "数据", 2, async (_, body: any) => {
      expect(body.offset).toBe(50); expect(body.limit).toBe(50); expect(body.orgId).toBe("demo")
      return envelope({ success: true, data: { jobs: [{ id: "job-1", title: "数据实习", locations: [{ provinceName: "北京市", cityName: "海淀区" }], jobDescription: "<p>SQL &amp; Python</p>", createdAt: "2026-09-01 09:00:00" }] } })
    })
    expect(out.jobs[0].url).toEndWith("#/job/job-1"); expect(out.jobs[0].location).toBe("北京市 海淀区")
    expect(out.jobs[0].description).toBe("SQL & Python"); expect(out.jobs[0].date).toBeNull(); expect(out.more).toBe(false)
    expect(() => decryptMoka({ data: "bad", necromancer: "short" })).toThrow()
  })
  test("Greenhouse keeps publication date, not updated_at; double HTML decoded", async () => {
    const out = await fetchPage(gh, resolveBoard(gh), "SQL", 1, async url => {
      expect(url).toContain("content=true")
      return { jobs: [{ id: 1, title: "Analyst", absolute_url: "https://job-boards.greenhouse.io/demo/jobs/1", location: { name: "Shanghai" }, content: "&lt;p&gt;SQL &amp;amp; Python&lt;/p&gt;", updated_at: "2026-09-01T00:00:00Z" }] }
    })
    expect(out.jobs[0].description).toBe("SQL & Python"); expect(out.jobs[0].date).toBeNull()
  })
  test("Lever multi-location and requirements lists are retained", async () => {
    const out = await fetchPage(lever, resolveBoard(lever), "SQL", 1, async () => [{ id: "1", text: "Analyst", hostedUrl: "https://jobs.lever.co/demo/1", categories: { location: "Beijing", allLocations: ["Shanghai"] }, descriptionPlain: "Analysis", lists: [{ text: "Required", content: "<li>SQL</li>" }], createdAt: 1788480000000 }])
    expect(out.jobs[0].location).toContain("Shanghai"); expect(out.jobs[0].description).toContain("SQL")
  })
  test("Ashby secondary location, private listing exclusion, Hybrid beats isRemote", async () => {
    const out = await fetchPage(ashby, resolveBoard(ashby), "SQL", 1, async () => ({ jobs: [
      { id: "1", title: "Analyst", jobUrl: "https://jobs.ashbyhq.com/demo/1", location: "Beijing", secondaryLocations: [{ location: "Shanghai" }], workplaceType: "Hybrid", isRemote: true, descriptionPlain: "SQL", publishedAt: "2026-09-01T00:00:00Z" },
      { id: "2", title: "Hidden", jobUrl: "https://jobs.ashbyhq.com/demo/2", isListed: false },
    ] }))
    expect(out.jobs).toHaveLength(1); expect(out.jobs[0].location).toContain("Shanghai"); expect(out.jobs[0].location).not.toContain("Remote"); expect(out.malformed).toBe(0)
  })
  test("API errors and wrong shape never become valid empty boards", async () => {
    for (const c of [mt, feishu, gh, lever, ashby]) await expect(fetchPage(c, resolveBoard(c), "x", 1, async () => ({ success: false }))).rejects.toThrow()
    await expect(fetchPage(moka, resolveBoard(moka), "x", 1, async () => envelope({ success: false, data: { jobs: [] } }))).rejects.toThrow()
  })
  test("raw page, not normalized page count drives pagination", async () => {
    const out = await fetchPage(feishu, resolveBoard(feishu), "x", 1, async () => ({ code: 0, data: { job_post_list: [...Array.from({ length: 99 }, (_, i) => posting(String(i))), { id: "missing-title" }], count: 102 } }))
    expect(out.jobs).toHaveLength(99); expect(out.malformed).toBe(1); expect(out.more).toBe(true)
  })
})

describe("search orchestration", () => {
  test("pagination, filtering, output bound and diagnostics", async () => {
    let calls = 0
    const out = await fetchSearch({ query: "数据", location: "Shanghai", limit: 1, maxPages: 2 }, { companies: [feishu], check: noCheck, read: async () => ({ code: 0, data: { job_post_list: [posting(String(++calls))], count: 101 } }) })
    expect(calls).toBe(2); expect(out.results).toHaveLength(1); expect(out.meta.matched).toBe(2); expect(out.meta.output_truncated).toBe(true)
    expect(out.meta.runs[0].pages).toBe(2)
  })
  test("page cap is partial; repeated page stops", async () => {
    const read = async () => ({ code: 0, data: { job_post_list: Array.from({ length: 100 }, (_, i) => posting(String(i))), count: 1000 } })
    const one = await fetchSearch({ query: "数据", maxPages: 1 }, { companies: [feishu], check: noCheck, read })
    expect(one.meta.runs[0].status).toBe("partial"); expect(one.meta.warnings[0]).toContain("上限")
    const repeated = await fetchSearch({ query: "数据", maxPages: 5 }, { companies: [feishu], check: noCheck, read })
    expect(repeated.meta.runs[0].pages).toBe(2); expect(repeated.meta.warnings[0]).toContain("重复")
  })
  test("partial network failure keeps earlier jobs; next company still runs", async () => {
    let calls = 0
    const out = await fetchSearch({ query: "数据" }, { companies: [feishu, gh], check: noCheck, read: async url => {
      if (url.includes("greenhouse")) return { jobs: [] }
      if (++calls === 2) throw new Error("HTTP 429")
      return { code: 0, data: { job_post_list: [posting("1")], count: 201 } }
    } })
    expect(out.results).toHaveLength(1); expect(out.meta.runs.map(r => r.status)).toEqual(["partial", "ok"])
  })
  test("first-request failure distinct from true zero; no automatic fit", async () => {
    const out = await fetchSearch({ query: "x" }, { companies: [gh], check: noCheck, read: async () => { throw new Error("403") } })
    expect(out.meta.errors).toHaveLength(1); expect(out.meta.complete).toBe(false)
    const empty = await fetchSearch({ query: "x" }, { companies: [gh], check: noCheck, read: async () => ({ jobs: [] }) })
    expect(empty.meta.complete).toBe(true); expect(empty.meta.errors).toHaveLength(0)
  })
  test("config discovery and invalid selectors", async () => {
    const all = await loadCompanies(); expect(all.length).toBeGreaterThanOrEqual(8)
    expect(selectCompanies(all).every(c => c.enabled !== false)).toBe(true)
    expect(selectCompanies(all, ["anthropic"])[0].enabled).toBe(false)
    expect(() => selectCompanies(all, ["missing"])).toThrow()
    expect(() => integer(0, 3, 10)).toThrow(); expect(() => integer(NaN, 3, 10)).toThrow()
    expect(() => integer(11, 3, 10)).toThrow()
  })
  test("recency never invents date; title/JD and city filters", () => {
    const j = { title: "Intern", description: "SQL", location: "Shanghai", date: null } as Job
    expect(matches(j, { query: "SQL", location: "上海" })).toBe(true)
    expect(matches(j, { query: "SQL", jobage: 14 })).toBe(false)
    expect(matches({ ...j, location: "" }, { query: "SQL", location: "上海" })).toBe(false)
    expect(isoDate("2026-09-01 09:00:00")).toBeNull()
    expect(isoDate("2026-09-01T09:00:00+08:00")).toBe("2026-09-01T01:00:00.000Z")
  })
  test("URL and role dedupe retain genuine Moka routes", () => {
    expect(canonicalUrl("https://jobs.bytedance.com/experienced/position/123/detail?utm_source=x")).toBe("https://jobs.bytedance.com/experienced/position/123/detail")
    expect(canonicalUrl(moka.url + "#/job/1")).not.toBe(canonicalUrl(moka.url + "#/job/2"))
    expect(roleKey(" Example ", " DATA Intern ")).toBe("example|data intern")
  })
  test("CLI rejects unknown and missing flags; no accidental broad search", () => {
    expect(() => parseArgs(["search"])).toThrow()
    expect(() => parseArgs(["search", "-q", "SQL", "--page", "2"])).toThrow()
    expect(() => parseArgs(["search", "-q", "SQL", "--companies"])).toThrow()
    expect(parseArgs(["search", "-q", "SQL", "-l", "上海", "--companies", "deepseek,zhipu"]).options.companies).toEqual(["deepseek", "zhipu"])
  })
})

describe("seen_jobs integration without personal files or network", () => {
  const old = { title: "Data Intern", company: "Example", url: "https://jobs.lever.co/demo/old", first_seen: "2026-08-01", deadline: null, fit: "high", status: "applied", portal: "websearch", source: "websearch", score: 91, flags: ["preserve"] }
  const args = ["--sources", "company", "--keyword", "data", "--location", ""]
  test("write dedupes URL and company/title, excludes tracker, preserves ranking and uses unknown", async () => {
    let written: any, events: any[] = []
    await runSync([...args, "--write"], {
      readSeen: async () => ({ legacy: structuredClone(old) }),
      readTrackerKeys: async () => new Set([roleKey("Tracked", "Analyst")]),
      fetchPortal: async () => ({ meta: { warnings: ["example partial"], runs: [{ company: "Example", status: "partial" }] }, results: [
        { id: "dup-url", company: "Another spelling", title: "Another title", url: old.url + "?utm_source=new" },
        { id: "dup-role", company: " example ", title: " DATA Intern ", url: "https://jobs.lever.co/demo/alternate" },
        { id: "tracked", company: "Tracked", title: "Analyst", url: "https://jobs.lever.co/demo/tracked" },
        { id: "fresh", company: "Example", title: "数据分析实习", url: "https://jobs.lever.co/demo/fresh" },
      ] }),
      writeSeen: async value => { written = structuredClone(value) },
      appendSourceRun: async event => { events.push(event) },
    })
    expect(Object.keys(written)).toEqual(["legacy", "company:fresh"])
    expect(written.legacy).toEqual(old)
    expect(written["company:fresh"].fit).toBe("unknown")
    expect(written["company:fresh"].portal).toBe("company-careers-search")
    expect(events[0].status).toBe("warning")
    expect(events[0].details.company_runs).toHaveLength(1)
  })
  test("preview writes neither seen nor source logs", async () => {
    let writes = 0
    await runSync(args, {
      readSeen: async () => ({}), readTrackerKeys: async () => new Set(),
      fetchPortal: async () => ({ results: [{ id: "fresh", company: "Example", title: "Data", url: "https://jobs.lever.co/demo/fresh" }] }),
      writeSeen: async () => { writes++ }, appendSourceRun: async () => { writes++ },
    })
    expect(writes).toBe(0)
  })
  test("state read failure stops before scan/write, and company-only flags cannot be silently ignored", async () => {
    let touched = false
    await expect(runSync([...args, "--write"], {
      readSeen: async () => { throw new Error("corrupt state") },
      writeSeen: async () => { touched = true },
    })).rejects.toThrow("corrupt state")
    expect(touched).toBe(false)
    await expect(runSync(["--companies", "deepseek"])).rejects.toThrow("--sources company")
    await expect(runSync([...args, "--company-max-pages", "0"])).rejects.toThrow("1–10")
  })
})

describe("public transport boundaries", () => {
  test("robots specific groups and Allow specificity, wildcard paths", () => {
    const target = new URL("https://example.com/api/jobs")
    expect(robotsAllows("User-agent: *\nDisallow: /api", target)).toBe(false)
    expect(robotsAllows("User-agent: *\nDisallow: /\nAllow: /api/jobs$", target)).toBe(true)
    expect(robotsAllows("User-agent: *\nDisallow: /\nUser-agent: OfferHarvester\nAllow: /api/", target)).toBe(true)
    expect(robotsAllows("User-agent: *\nDisallow: /*jobs$", target)).toBe(false)
  })
  test("robots disallow means no API fetch", async () => {
    const calls: string[] = []
    const c = new PublicClient(async url => { calls.push(url); return new Response("User-agent: *\nDisallow: /api") }, noCheck)
    await expect(c.json("https://example.com/api/jobs")).rejects.toThrow("robots")
    expect(calls).toHaveLength(1)
  })
  test("cached robots, honest UA, redirect refusal, no retries on 429", async () => {
    const calls: string[] = []
    const c = new PublicClient(async (url, init) => {
      calls.push(url); expect(init?.redirect).toBe(url.endsWith("robots.txt") ? "manual" : "error"); expect((init?.headers as any)["user-agent"]).toStartWith("OfferHarvester")
      return url.endsWith("robots.txt") ? new Response("", { status: 404 }) : new Response("limited", { status: 429 })
    }, noCheck)
    await expect(c.json("https://example.com/api/jobs")).rejects.toThrow("429")
    expect(calls).toHaveLength(2)
    await c.check("https://example.com/jobs"); expect(calls).toHaveLength(2)
  })
  test("non-JSON challenge page is not an empty success", async () => {
    const c = new PublicClient(async url => url.endsWith("robots.txt") ? new Response("", { status: 404 }) : new Response("<html>verify</html>"), noCheck)
    await expect(c.json("https://example.com/jobs")).rejects.toThrow("JSON")
  })
  test("robots may redirect to same-origin homepage, never to private/foreign host", async () => {
    const client = new PublicClient(async url => {
      if (url.endsWith("robots.txt")) return new Response("", { status: 302, headers: { location: "/web/social" } })
      if (url.endsWith("social")) return new Response("<html><title>Company Careers</title></html>")
      return Response.json({ jobs: [] })
    }, noCheck)
    expect(await client.json("https://example.com/api/jobs")).toEqual({ jobs: [] })
    const bad = new PublicClient(async () => new Response("", { status: 302, headers: { location: "https://127.0.0.1/" } }), noCheck)
    await expect(bad.json("https://example.com/api/jobs")).rejects.toThrow("其他主机")
  })
  test("HTML text stays inert", () => {
    expect(plainText("&lt;script&gt;evil()&lt;/script&gt;&lt;p&gt;SQL&lt;/p&gt;")).toBe("SQL")
  })
})
