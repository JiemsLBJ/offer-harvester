import { fetchDetail, fetchSearch, loadCompanies, type SearchOptions } from "./commands/search.js"
import { resolveBoard } from "./providers.js"

export function parseArgs(args: string[]) {
  const [command = "help", ...rest] = args
  const options: SearchOptions = { query: "", format: "json" }
  let target = ""
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i]
    if (a === "--help" || a === "-h") return { command: "help", options, target }
    if (command === "detail" && !a.startsWith("-") && !target) { target = a; continue }
    const allowed = ["--query", "-q", "--location", "-l", "--limit", "--max-pages", "--jobage", "--companies", "--config", "--format"]
    if (!allowed.includes(a)) throw new Error(`未知参数：${a}`)
    const v = rest[++i]
    if (v === undefined || v.startsWith("--")) throw new Error(`${a} 缺少值`)
    if (a === "--query" || a === "-q") options.query = v
    else if (a === "--location" || a === "-l") options.location = v
    else if (a === "--companies") { options.companies = v.split(",").map(s => s.trim()).filter(Boolean); if (!options.companies.length) throw new Error("公司列表不能为空") }
    else if (a === "--config") options.config = v
    else if (a === "--format") { if (!["json", "plain", "table"].includes(v)) throw new Error("format 必须是 json/plain/table"); options.format = v }
    else if (a === "--limit") options.limit = Number(v)
    else if (a === "--max-pages") options.maxPages = Number(v)
    else if (a === "--jobage") options.jobage = Number(v)
  }
  if (command === "search" && !options.query.trim()) throw new Error("search 必须提供 --query 关键词")
  if (command === "detail" && !target) throw new Error("detail 必须提供岗位 URL 或完整 id")
  return { command, options, target }
}

async function main() {
  const { command, options, target } = parseArgs(process.argv.slice(2))
  if (["help", "--help", "-h"].includes(command)) {
    console.log("公司官网搜索：companies | search -q 关键词 [-l 城市] [--companies id,id] [--max-pages 3] [--limit 20] [--jobage 14] [--config 文件] [--format json|table|plain] | detail URL（可附原搜索参数）")
    return
  }
  if (command === "companies") {
    const companies = (await loadCompanies(options.config)).map(c => ({ ...c, provider: resolveBoard(c).provider }))
    console.log(options.format === "json" ? JSON.stringify({ companies }, null, 2) : companies.map(c => `${c.id}\t${c.name}\t${c.provider}\t${c.enabled === false ? "需显式选择" : "默认启用"}\t${c.url}`).join("\n"))
    return
  }
  if (command !== "search" && command !== "detail") throw new Error(`未知命令：${command}`)
  const output = command === "search" ? await fetchSearch(options) : await fetchDetail(target, options)
  if (options.format === "json") console.log(JSON.stringify(output, null, 2))
  else {
    const jobs = "results" in output ? output.results : [output.result]
    for (const j of jobs) console.log(`${j.company}\t${j.title}\t${j.location}\t${j.date ?? "日期未知"}\n${j.url}${command === "detail" ? "\n" + j.description : ""}`)
    console.error(JSON.stringify(output.meta, null, 2))
  }
  // Partial results remain readable; structured per-company status is mandatory.
  if (output.meta.runs.every(r => r.status === "error")) process.exitCode = 2
}

if (import.meta.main) main().catch(e => { console.error(e instanceof Error ? e.message : String(e)); process.exitCode = 1 })
