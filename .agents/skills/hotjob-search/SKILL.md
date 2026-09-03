---
name: hotjob-search
description: >
  Searches internships on Wecruit/Hotjob employer career sites through their
  public job-list and job-detail endpoints. Defaults to Deloitte China and can
  target another verified Wecruit tenant. Triggers on: 德勤招聘, 德勤实习,
  Hotjob, Wecruit, 大易招聘, /scrape 德勤.
allowed-tools: Bash(bun run .agents/skills/hotjob-search/cli/src/cli.ts *)
---

# Hotjob / Wecruit Search

Search public postings on the Wecruit generation of Hotjob career sites. The
default tenant is Deloitte China's internship site; reads need no login or API
key. Applying is deliberately separate and uses `apply_bot` so login, uploads,
form learning, review, and final confirmation retain their safety gates.

## Commands

| Command | Purpose |
|---|---|
| `search` | Search open internship titles, with optional city/recency filters |
| `detail <postId\|url>` | Read the full duties, qualifications, deadline, and identifiers |

## Search flags

| Flag | Meaning |
|---|---|
| `--query, -q <kw>` | Title keyword, required |
| `--location, -l <city>` | Client-side city filter, such as `上海` |
| `--jobage <days>` | Keep postings published within N days |
| `--page <n>` | 1-indexed API page, default 1 |
| `--limit <n>` | Maximum results, default 20 |
| `--format <fmt>` | `json` (default), `table`, or `plain` |
| `--tenant <SU...\|url>` | Verified Wecruit tenant; defaults to Deloitte |
| `--company <name>` | Employer name stored in results; defaults to `德勤` |

## Examples

```bash
bun run .agents/skills/hotjob-search/cli/src/cli.ts search -q "数据分析" -l 上海 --limit 10 --format table
bun run .agents/skills/hotjob-search/cli/src/cli.ts search -q "人工智能" --jobage 30 --format json
bun run .agents/skills/hotjob-search/cli/src/cli.ts detail 66875e421c240e3d86dafec5 --format plain
```

JSON search output is `{ "meta": {...}, "results": [...] }`. Each result has
`id`, `title`, `company`, `location`, `date`, `deadline`, `url`, `business_unit`,
`department`, `category`, `project_name`, and `post_code`. Expired postings are
discarded. A result URL always opens that exact posting rather than a list page.

## Boundaries

- Personal, low-volume use only. These are undocumented endpoints used by the
  employer's public page; stop on rate limiting or a changed response contract.
- `--jobage` uses the site's `publishDate`. An older posting with a future
  deadline remains open but is intentionally omitted when this filter is set.
- A different tenant is accepted only when supplied explicitly. Set the correct
  employer with `--company`; never infer it from a business-unit field.
- See [url-reference.md](url-reference.md) when the site changes.
