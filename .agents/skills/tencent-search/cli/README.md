# tencent-search — 腾讯招聘 CLI

Zero-dependency portal CLI for Tencent Group job postings
([careers.tencent.com](https://careers.tencent.com), 腾讯招聘). Search and detail
go through the careers site's **public JSON API** — no login, no API key, only
`bun`. Apply (投递) lives in the `apply_bot` portal adapter.

```bash
bun run src/cli.ts search -q "数据分析" -l 上海 --limit 10 --format table
bun run src/cli.ts search -q "实习" --jobage 14 --format json
bun run src/cli.ts detail 2041847335474065408 --format plain
```

## Endpoints used

- Search: `GET /tencentcareer/api/post/Query` — keyword, pagination; JSON
  `{Code, Data:{Count, Posts[]}}`. `cityId` is **not** functional (answers
  `Code≠200`), so `--location` filters client-side on `LocationName`.
- Detail: `GET /tencentcareer/api/post/ByPostId?postId=…` — adds `Requirement`,
  `Introduction` to the list fields.

## Field mapping (list + detail)

| Contract | API field | Notes |
|---|---|---|
| id | `PostId` | numeric string |
| title | `RecruitPostName` | |
| company | `ComName` \|\| `腾讯` | `ComCode`/`ComName` often empty (腾讯 is the employer) |
| location | `CountryName` + `LocationName` | `"中国 · 上海"` style |
| date | `LastUpdateTime` | `"2026年08月10日"` → `2026-08-10` |
| url | derived | `https://careers.tencent.com/jobdesc.html?postId=<PostId>` |
| extras | `BGName`/`CategoryName`/`ProductName`/`RequireWorkYearsName` | business group is more informative than `ComName` |
| description | `Responsibility` + `Requirement` (+`Introduction`) | detail only |

## Quirks

- The API is undocumented; params mirror the site's own XHR exactly.
- `Resposibility` appears in the *list* too (heavy) — the CLI keeps list
  responses light and defers full text to `detail`.
- No deadline in the API → `deadline: null` always; `LastUpdateTime` is the
  refresh date (`--jobage` uses it).
- `robots.txt` serves a 404 on the API host; keep request volume low.

## Proxy

Reads the proxy from `HTTPS_PROXY`/`HTTP_PROXY` env vars, falling back to the
Windows registry `ProxyServer` (Clash etc.) via `Bun.ProxyAgent` — no config.

⚠️ **Personal use only.** You are responsible for your own use.
