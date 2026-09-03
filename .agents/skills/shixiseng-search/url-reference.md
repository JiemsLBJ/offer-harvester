# shixiseng-search — Endpoint Reference

Portal: https://www.shixiseng.com (实习僧) — Nuxt SSR (Nuxt 2), public listing reads.

## Endpoints

| Purpose | URL | Notes |
|---|---|---|
| Search (list) | `GET https://www.shixiseng.com/interns?keyword=<kw>&city=<city>&page=<n>` | SSR HTML; `city` optional literal name (e.g. `上海`, `北京`, `全国`). `page` 1-indexed. |
| Detail | `GET https://www.shixiseng.com/intern/<uuid>` | SSR HTML; `uuid` = `inn_...` (e.g. `inn_h1mc7vtlxwup`). |
| robots.txt | 403 for non-browser UAs | No usable disallow info; keep volume low. |

## Response parsing anchors

### List page

- `window.__NUXT__ = (function(a,b,c,…){ return {...} })(…)` — evaluate in a
  sandboxed vm context; `JSON.stringify(window.__NUXT__)` yields the state tree.
- State path: `data[0].interns` = `{ data: Job[], total: number, pageNumber: number }`.
- Job object keys (v1.0.0): `ad_type, maxsal, skill, minsal, is_view, city,
  scale, uuid, month_num, ftype, maxsalary, type, job_label, is_hr, invite,
  degree, c_uuid, deliver, hope_you, talkFace, day, c_tags, i_tags, name, url,
  industry, minsalary, refresh, cname`.
- Field map: `uuid`→id, `name`→title (PUA glyphs stripped), `cname`→company,
  `city`→location, `minsalary`/`maxsalary`→salary `${min}-${max}`/天,
  `refresh`→date (**always `""` on current layout** → `date: null`), `day`→
  icon-glyph (**not** a date; detail's `day` is 每周天数, a number).
- Parsing is defensive: `findInternList` walks the tree for the first array
  whose first element has a `uuid` matching `inn_…`, so a layout shift in the
  path above degrades to the walk rather than empty results.

### Detail page

- Same NUXT extraction; the detail object is located by a walk for the first
  object with a non-empty `cname` (the server assembles it via dotted
  assignments, so its position inside the tree is not stable).
- Field map: `iname`→title, `cname`→company, `city`→location, `address`,
  `industry`, `degree`, `day`→days/week (number), `month_num`→months,
  `refresh`→posted date (`"2026-06-17 10:39:31"`), `endtime`→deadline
  (`"2027-01-17"`), `salary_desc`→salary with unit or `chance`→`面议`,
  `info`→full description (职责描述+任职要求, may contain `&semi;` entity),
  `hope_you_v2`→要求list（可能为空）, `deliver`→已投递 0/1, `apply_link`→
  portal apply URL（常为空；投递在站内完成）。
- Entity quirks: `&semi;` → `;`; titles contain private-use icon glyphs.

## Update checklist when results break

1. `--format json` returns `NO_STATE` → page layout/captcha change; check for
   `window.__NUXT__` in raw HTML.
2. All titles look like plain company names / empty → NUXT field renamed; diff
   new Job keys against the map above.
3. Zero results despite healthy queries → could be a CAPTCHA wall (200 + SPA
   shell without NUXT). Do not throttle harder; back off.
