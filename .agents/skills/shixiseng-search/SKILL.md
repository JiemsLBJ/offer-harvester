---
name: shixiseng-search
version: 1.0.0
description: >
  Searches 实习僧 (www.shixiseng.com), China's largest internship board, for
  internship postings by keyword and city. Zero-dependency CLI reading the
  server-side-rendered pages (Nuxt SSR) - no login needed to read listings.
  Triggers on: 实习僧, shixiseng, 实习岗位, internship search, find an internship,
  找实习, /scrape 实习.
context: fork
allowed-tools: Bash(bun run .agents/skills/shixiseng-search/cli/src/cli.ts *)
---

# 实习僧 Search (shixiseng.com)

Searches internship postings on China's biggest internship board (实习僧).
Listings are public and server-side rendered, so reads need **no login and no
API key** - just `bun`. Applying, however, requires login/Verification and goes
through the `apply_bot` portal adapter, not this CLI.

⚠️ **Personal use only.** Keep volume low (a handful of queries per session,
never a crawl). The portal's `/robots.txt` does not answer non-browser UAs
(403), so respect the site by staying at discovery volume. Own responsibility.

## Commands

| Command | What it does |
|---|---|
| `search` | Search internships by keyword (+ optional city) |
| `detail <id\|url>` | Full posting: description, requirements, salary, deadline |

## Search flags

| Flag | Meaning |
|---|---|
| `--query, -q <kw>` | Keyword (job title / skill / company), required |
| `--location, -l <city>` | City filter (e.g. `上海`, `北京`, `全国`); client-side filter on `city` field |
| `--jobage <days>` | Postings refreshed within N days (client-side filter on the date field) |
| `--page <n>` | 1-indexed page (default 1) |
| `--limit <n>` | Max results returned (default 20) |
| `--format <fmt>` | `json` (default) / `table` / `plain` |

## Examples

```bash
bun run .agents/skills/shixiseng-search/cli/src/cli.ts search -q "数据分析" -l 上海 --limit 10 --format table
bun run .agents/skills/shixiseng-search/cli/src/cli.ts search -q "量化" --jobage 14 --format json
bun run .agents/skills/shixiseng-search/cli/src/cli.ts detail inn_h1mc7vtlxwup --format plain
```

## Output format

`search --format json` prints `{ "meta": {"count", "page"}, "results": [...] }`;
each result carries `id` (the `inn_...` uuid), `title`, `company`, `location`,
`date`, `url`, plus best-effort `salary`. Missing values are `null`, never omitted.

`detail --format json` adds `description` (职位描述 + 任职要求 as readable text),
`salary` (`chance` field, e.g. "面议" or "300-400/天"), `deadline` (when stated).

## Notes for maintainers

- The site is Nuxt SSR; the parser evaluates `window.__NUXT__`'s IIFE in a
  sandboxed `vm` context to recover structured JSON. Anchors: state layout
  `data[0].interns.data[]` (list) and a recursive find on the object holding
  `cname` + `description` (detail). See `url-reference.md`.
- `date` comes from the list item's `refresh` field (fallbacks: `day`).
- Salary is icon-glyph coded in list items (`maxsal`/`minsal` are non-ASCII
  private-use chars) - the CLI uplevels `chance` from the detail page instead.
- Site quirks change; when results come back empty or garbled, run
  `/scrape health shixiseng-search` and re-check `url-reference.md`.
