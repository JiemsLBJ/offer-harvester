#!/usr/bin/env bun
// Self-contained CLI for searching 实习僧 (www.shixiseng.com) internship postings.
// Zero runtime dependencies: reads the site's Nuxt SSR pages with bun's fetch.
// Reads are public and need no login; applying (投递) is handled by apply_bot.

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

const ALIAS: Record<string, string> = { q: "query", l: "location", n: "limit" }

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (!a.startsWith("-")) {
      ;(flags._ as string[]).push(a)
      continue
    }
    const name = a.replace(/^-+/, "")
    const key = ALIAS[name] ?? name
    const next = argv[i + 1]
    let value: string | boolean = true
    if (next !== undefined && !next.startsWith("-")) {
      value = next
      i++
    }
    flags[key] = value
  }
  return flags
}

function stringFlag(raw: string | boolean | string[] | undefined, whenBare?: string): string | undefined {
  if (typeof raw === "string") return raw
  if (raw === true) return whenBare
  return undefined
}

const HELP = `shixiseng-cli — search 实习僧 (shixiseng.com) internship postings (China, public listings)

USAGE
  bun run src/cli.ts search -q "<keyword>" [-l <city>] [--jobage <days>]
                            [--page <n>] [--limit <n>] [--format json|table|plain]
  bun run src/cli.ts detail <inn_...|url> [--format json|plain]

SEARCH FLAGS
  --query, -q <kw>        Keyword (title/skill/company), required.
  --location, -l <city>   City (e.g. 上海, 北京, 全国). Server-side param.
  --jobage <days>         Keep only postings refreshed within N days. NOTE: the
                          search list carries no usable date; this filter is a
                          no-op until a field exists (detail carries real dates).
  --page <n>              1-indexed page. Default 1.
  --limit, -n <n>         Max results returned. Default 20.
  --format <fmt>          json (default) | table | plain.

DETAIL
  <id|url>                An inn_... uuid or a /intern/<uuid> URL.

EXAMPLES
  bun run src/cli.ts search -q "数据分析" -l 上海 --limit 10 --format table
  bun run src/cli.ts search -q "量化研究" --limit 5 --format json
  bun run src/cli.ts detail inn_h1mc7vtlxwup --format plain

Reads are public. Personal use only — keep volume low, never crawl.
`

function parseIntFlag(name: string, raw: string | boolean | string[]): number | null {
  const val = parseInt(raw as string, 10)
  if (isNaN(val)) {
    process.stderr.write(JSON.stringify({ error: `--${name} must be a number, got "${raw}"`, code: "BAD_ARG" }) + "\n")
    return null
  }
  return val
}

const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set(["query", "location", "jobage", "page", "limit", "format", "help", "h"]),
  detail: new Set(["format", "help", "h"]),
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const flags = parseFlags(argv)
  const cmd = (flags._ as string[])[0]

  if (!cmd || flags.help || flags.h) {
    process.stdout.write(HELP)
    return cmd ? 0 : 1
  }

  const knownFlags = KNOWN_FLAGS[cmd]
  if (knownFlags) {
    for (const key of Object.keys(flags)) {
      if (key === "_" || knownFlags.has(key)) continue
      process.stderr.write(
        JSON.stringify({ error: `unknown flag --${key} for '${cmd}'`, code: "UNKNOWN_FLAG" }) + "\n",
      )
      return 1
    }
  }

  if (cmd === "search") {
    const query = stringFlag(flags.query)
    if (!query) {
      process.stderr.write(JSON.stringify({ error: "search requires --query/-q", code: "NO_QUERY" }) + "\n")
      return 1
    }
    for (const name of ["jobage", "page", "limit"] as const) {
      if (flags[name] !== undefined) {
        const v = parseIntFlag(name, flags[name])
        if (v === null) return 1
        flags[name] = String(v)
      }
    }
    const fmt = (flags.format as string) || "json"
    const opts: SearchOpts = {
      query,
      location: stringFlag(flags.location),
      page: flags.page ? Math.max(1, parseInt(flags.page as string, 10)) : 1,
      limit: flags.limit ? Math.max(1, parseInt(flags.limit as string, 10)) : 20,
      jobage: flags.jobage ? Math.max(0, parseInt(flags.jobage as string, 10)) : undefined,
      format: (["json", "table", "plain"].includes(fmt) ? fmt : "json") as SearchOpts["format"],
    }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) {
      process.stderr.write(JSON.stringify({ error: "detail requires a <id|url>", code: "NO_ID" }) + "\n")
      return 1
    }
    const fmt = (flags.format as string) || "json"
    const opts: DetailOpts = { id, format: fmt === "plain" ? "plain" : "json" }
    return runDetail(opts)
  }

  process.stderr.write(JSON.stringify({ error: `Unknown command "${cmd}"`, code: "BAD_CMD" }) + "\n")
  return 1
}

main()
  .then((code) => process.exit(code))
  .catch((e) => {
    process.stderr.write(
      JSON.stringify({ error: e instanceof Error ? e.message : String(e), code: "INTERNAL_ERROR" }) + "\n",
    )
    process.exit(1)
  })
