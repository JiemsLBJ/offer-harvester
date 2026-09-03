import { describe, expect, test } from "bun:test"
import { canonicalUrl, isExpired, normalizePostId, normalizeTenant } from "../src/helpers.ts"
import { parseJSON, runCli } from "./helpers.ts"

describe("hotjob helpers", () => {
  test("normalizes tenant, post id, canonical URL, and deadlines", () => {
    expect(normalizeTenant("https://wecruit.hotjob.cn/SU64365a780dcad43c5ae82bab/pb/interns.html")).toBe("SU64365a780dcad43c5ae82bab")
    expect(normalizePostId("https://x.test/p?postId=66875e421c240e3d86dafec5&postType=intern")).toBe("66875e421c240e3d86dafec5")
    expect(canonicalUrl("66875e421c240e3d86dafec5")).toContain("/pb/posDetail.html?postId=66875e421c240e3d86dafec5&postType=intern")
    expect(isExpired("2026-08-31", "2026-09-01")).toBe(true)
    expect(isExpired("2026-09-01", "2026-09-01")).toBe(false)
  })
})

describe("hotjob live contract", () => {
  test("search returns exact open posting URLs", () => {
    const result = runCli(["search", "-q", "数据分析", "-l", "上海", "--limit", "3", "--format", "json"])
    expect(result.code).toBe(0)
    const output = parseJSON(result.stdout)
    expect(output.results.length).toBeGreaterThanOrEqual(1)
    expect(output.results[0].company).toBe("德勤")
    expect(output.results[0].url).toContain("/pb/posDetail.html?postId=")
    expect(output.results[0].deadline >= "2026-09-01").toBe(true)
  })

  test("detail returns duties and requirements", () => {
    const result = runCli(["detail", "66875e421c240e3d86dafec5", "--format", "json"])
    expect(result.code).toBe(0)
    const detail = parseJSON(result.stdout)
    expect(detail.title).toContain("数据分析")
    expect(detail.duties.length).toBeGreaterThan(50)
    expect(detail.requirements.length).toBeGreaterThan(50)
  })

  test("rejects unknown flags", () => {
    const result = runCli(["search", "-q", "数据分析", "--bogus"])
    expect(result.code).toBe(1)
    expect(parseJSON(result.stderr).code).toBe("UNKNOWN_FLAG")
  })
})
