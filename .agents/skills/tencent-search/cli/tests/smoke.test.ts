import { describe, expect, test } from "bun:test"
import { runCli, parseJSON } from "./helpers.ts"

// Live smoke tests against careers.tencent.com (proxy auto-detected from env or
// the Windows registry). One search, one detail, negative cases — low volume.

describe("tencent-cli contract", () => {
  test("search returns real results with contract fields", () => {
    const r = runCli(["search", "-q", "数据分析", "-l", "上海", "--limit", "3", "--format", "json"])
    expect(r.code).toBe(0)
    const out = parseJSON(r.stdout)
    expect(Array.isArray(out.results)).toBe(true)
    expect(out.results.length).toBeGreaterThanOrEqual(1)
    const first = out.results[0]
    expect(typeof first.id).toBe("string")
    expect(typeof first.title).toBe("string")
    expect(first.title.length).toBeGreaterThan(0)
    expect(first.url).toContain("careers.tencent.com/jobdesc.html?postId=")
  })

  test("detail returns readable description", () => {
    const s = runCli(["search", "-q", "实习", "--limit", "1", "--format", "json"])
    const id = parseJSON(s.stdout).results[0].id
    const r = runCli(["detail", id, "--format", "plain"])
    expect(r.code).toBe(0)
    expect(r.stdout).toContain("URL: https://careers.tencent.com/jobdesc.html?postId=")
  })

  test("unknown flag exits 1 with a JSON error on stderr", () => {
    const r = runCli(["search", "-q", "x", "--bogus"])
    expect(r.code).toBe(1)
    expect(parseJSON(r.stderr).code).toBe("UNKNOWN_FLAG")
  })

  test("missing query exits 1", () => {
    const r = runCli(["search", "--format", "json"])
    expect(r.code).toBe(1)
    expect(parseJSON(r.stderr).code).toBe("NO_QUERY")
  })
})
