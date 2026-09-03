#!/usr/bin/env bun
import { runDetail, type DetailOpts } from "./commands/detail.js"
import { runSearch, type SearchOpts } from "./commands/search.js"
import { DEFAULT_COMPANY, normalizeTenant } from "./helpers.js"

interface Flags {
  _: string[]
  [key: string]: string | boolean | string[]
}

const ALIAS: Record<string, string> = { q: "query", l: "location", n: "limit" }

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index]
    if (!arg.startsWith("-")) {
      ;(flags._ as string[]).push(arg)
      continue
    }
    const raw = arg.replace(/^-+/, "")
    const key = ALIAS[raw] ?? raw
    const next = argv[index + 1]
    if (next !== undefined && !next.startsWith("-")) {
      flags[key] = next
      index++
    } else {
      flags[key] = true
    }
  }
  return flags
}

function stringFlag(value: string | boolean | string[] | undefined): string | undefined {
  return typeof value === "string" ? value : undefined
}

function numberFlag(name: string, value: string | boolean | string[] | undefined, fallback: number): number | null {
  if (value === undefined) return fallback
  const parsed = Number.parseInt(String(value), 10)
  if (!Number.isFinite(parsed)) {
    process.stderr.write(JSON.stringify({ error: `--${name} must be a number`, code: "BAD_ARG" }) + "\n")
    return null
  }
  return parsed
}

const HELP = `hotjob-search — search Wecruit/Hotjob internships (defaults to Deloitte China)

USAGE
  bun run src/cli.ts search -q <keyword> [-l <city>] [--jobage <days>]
                            [--page <n>] [--limit <n>] [--format json|table|plain]
                            [--tenant <SU...|url>] [--company <name>]
  bun run src/cli.ts detail <postId|url> [--format json|plain]
                            [--tenant <SU...|url>] [--company <name>]

EXAMPLES
  bun run src/cli.ts search -q "数据分析" -l 上海 --limit 3 --format plain
  bun run src/cli.ts detail 66875e421c240e3d86dafec5 --format plain
`

const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set(["query", "location", "jobage", "page", "limit", "format", "tenant", "company", "help", "h"]),
  detail: new Set(["format", "tenant", "company", "help", "h"]),
}

async function main(): Promise<number> {
  const flags = parseFlags(process.argv.slice(2))
  const command = (flags._ as string[])[0]
  if (!command || flags.help || flags.h) {
    process.stdout.write(HELP)
    return command ? 0 : 1
  }
  const allowed = KNOWN_FLAGS[command]
  if (!allowed) {
    process.stderr.write(JSON.stringify({ error: `unknown command "${command}"`, code: "BAD_CMD" }) + "\n")
    return 1
  }
  for (const key of Object.keys(flags)) {
    if (key !== "_" && !allowed.has(key)) {
      process.stderr.write(JSON.stringify({ error: `unknown flag --${key} for '${command}'`, code: "UNKNOWN_FLAG" }) + "\n")
      return 1
    }
  }
  const tenant = normalizeTenant(stringFlag(flags.tenant))
  if (!tenant) {
    process.stderr.write(JSON.stringify({ error: "--tenant must contain a Wecruit SU... tenant id", code: "BAD_TENANT" }) + "\n")
    return 1
  }
  const company = stringFlag(flags.company) || DEFAULT_COMPANY
  const format = stringFlag(flags.format) || "json"
  if (command === "search") {
    const query = stringFlag(flags.query)
    if (!query) {
      process.stderr.write(JSON.stringify({ error: "search requires --query/-q", code: "NO_QUERY" }) + "\n")
      return 1
    }
    const page = numberFlag("page", flags.page, 1)
    const limit = numberFlag("limit", flags.limit, 20)
    const jobage = flags.jobage === undefined ? undefined : numberFlag("jobage", flags.jobage, 0)
    if (page === null || limit === null || jobage === null) return 1
    const opts: SearchOpts = {
      query,
      location: stringFlag(flags.location),
      jobage: jobage === undefined ? undefined : Math.max(0, jobage),
      page: Math.max(1, page),
      limit: Math.max(1, limit),
      format: (["json", "table", "plain"].includes(format) ? format : "json") as SearchOpts["format"],
      tenant,
      company,
    }
    return runSearch(opts)
  }
  const id = (flags._ as string[])[1]
  if (!id) {
    process.stderr.write(JSON.stringify({ error: "detail requires a <postId|url>", code: "NO_ID" }) + "\n")
    return 1
  }
  const opts: DetailOpts = { id, format: format === "plain" ? "plain" : "json", tenant, company }
  return runDetail(opts)
}

main().then((code) => process.exit(code)).catch((error) => {
  process.stderr.write(JSON.stringify({ error: error instanceof Error ? error.message : String(error), code: "INTERNAL_ERROR" }) + "\n")
  process.exit(1)
})
