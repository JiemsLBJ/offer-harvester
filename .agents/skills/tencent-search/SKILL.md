---
name: tencent-search
version: 1.0.0
description: >
  Searches Tencent jobs on careers.tencent.com (腾讯招聘, mainland China) via the
  public careers API - no login needed for search/detail. Covers 社招/校招/实习
  postings across Tencent business groups (IEG, CSIG, WXG...). Triggers on: 腾讯
  招聘, tencent careers, 腾讯实习, 腾讯校招, Tencent job, /scrape 腾讯.
context: fork
allowed-tools: Bash(bun run .agents/skills/tencent-search/cli/src/cli.ts *)
---

# Tencent Search (careers.tencent.com)

Searches Tencent Group job postings (社招/校招/实习) through the careers site's
public JSON API. **No login and no API key** — the Query/ByPostId endpoints are
served to anonymous requests. Applying (投递) requires a Tencent-ID login and goes
through the `apply_bot` portal adapter, not this CLI.

⚠️ **Personal use only.** The API is an undocumented internal endpoint; the site
serves no robots.txt on the API path. Keep volume low and own your use.

## Commands

| Command | What it does |
|---|---|
| `search` | Search postings by keyword (title/role), optional city filter |
| `detail <postId\|url>` | Full posting: 岗位职责, 任职要求, business group, product |

## Search flags

| Flag | Meaning |
|---|---|
| `--query, -q <kw>` | Keyword (e.g. `数据分析`, `量化`, `实习`), required |
| `--location, -l <city>` | City filter (e.g. `上海`, `深圳`, `北京`) — client-side on `LocationName` |
| `--jobage <days>` | Keep postings updated within N days (client-side on `LastUpdateTime`) |
| `--page <n>` | 1-indexed page (default 1) |
| `--limit <n>` | Max results returned (default 20) |
| `--format <fmt>` | `json` (default) / `table` / `plain` |

## Examples

```bash
bun run .agents/skills/tencent-search/cli/src/cli.ts search -q "数据分析" -l 上海 --limit 10 --format table
bun run .agents/skills/tencent-search/cli/src/cli.ts search -q "实习" --jobage 14 --format json
bun run .agents/skills/tencent-search/cli/src/cli.ts detail 2041847335474065408 --format plain
```

## Output format

`search --format json` prints `{ "meta": {"count", "page"}, "results": [...] }`;
each result carries `id` (PostId), `title` (RecruitPostName), `company`
(`ComName`, falls back to `腾讯`), `location` (`CountryName + LocationName`),
`date` (`LastUpdateTime`), `url` (`jobdesc.html?postId=…`), plus extras
`business_group` (BGName), `category`, `product`, `require_years`. Missing
values are `null`, never omitted.

`detail --format json` adds `description` (岗位职责 + 任职要求 + 岗位介绍 as readable
text).

## Notes for maintainers

- Endpoints are versionless and undocumented; the Query params mirror the site's
  own XHR (verified against live requests). See `url-reference.md`.
- `cityId` on Query is **not** a valid filter (tested: returns `Code≠200` with
  `Data:null`) — city filtering is client-side on `LocationName`.
- `ComName` (company subsidiary, e.g. 腾讯音乐) is often empty; `BGName`
  business group is always present and more informative.
- `--jobage` uses `LastUpdateTime` (posts are refreshed when re-opened).
