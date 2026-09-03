# shixiseng-search — 实习僧 CLI

Zero-dependency portal CLI for finding internship postings on
[实习僧](https://www.shixiseng.com) (China's largest internship board). Listings
(搜索/详情) are public and server-side rendered — **no login, no API key**, only
`bun`. Apply (投递) lives in the `apply_bot` portal adapter, not here.

```bash
bun run src/cli.ts search -q "数据分析" -l 上海 --limit 10 --format table
bun run src/cli.ts search -q "量化" --format json
bun run src/cli.ts detail inn_h1mc7vtlxwup --format plain
```

## How it reads the site

The site is a Nuxt SSR app: list and detail pages embed the full page state as
`window.__NUXT__ = (function(...){ return {...} })(...)`. The CLI evaluates that
IIFE inside a locked-down `node:vm` context (no globals, 3s timeout, no code
generation) and walks the resulting JSON tree defensively:

- **Search:** state layout `data[0].interns` → `{data[], total, pageNumber}`.
- **Detail:** first object carrying a `cname` string (a defensive walk, since the
  server builds the detail object with dotted assignments).

## Notes

- List items carry **no usable posting date** (`refresh` is `""`, `day` is an
  icon-glyph code) — search results report `date: null`; `detail` returns the
  real `refresh` (posted) and `endtime` (deadline) dates.
- Salary: list has numeric `minsalary`/`maxsalary` (per-day); detail has
  `salary_desc` with the unit (e.g. `200/天`) or `chance` (`面议`).
- Titles embed private-use icon glyphs (`&#xf765`, `&#xecce`…); they are decoded
  then stripped (`stripPua`).
- The API can 200 with a CAPTCHA/error SPA shell: the CLI detects the missing
  `window.__NUXT__` and exits `1` with `NO_STATE` rather than emitting junk.

## Proxy

Reads the proxy from `HTTPS_PROXY`/`HTTP_PROXY` env vars, falling back to the
Windows registry `ProxyServer` (Clash etc.) via `Bun.ProxyAgent` — no config.

⚠️ **Personal use only.** The portal's `robots.txt` does not answer non-browser
UAs; keep request volume low (a handful per session, never a crawl). You are
responsible for your own use.
