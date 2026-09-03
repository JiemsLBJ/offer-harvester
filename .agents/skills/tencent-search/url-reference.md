# tencent-search — Endpoint Reference

Portal: https://careers.tencent.com (腾讯招聘) — public JSON API, no login for reads.

## Endpoints

| Purpose | URL | Notes |
|---|---|---|
| Search | `GET https://careers.tencent.com/tencentcareer/api/post/Query` | Params (mirror the site XHR): `timestamp` (ms, any value), `countryId` `cityId` `bgIds` `productId` `categoryId` `parentCategoryId` `attrId` (all empty strings), `keyword`, `pageIndex` (1-based), `pageSize` (site default 10; CLI uses 100), `language=zh-cn`, `area=cn`. |
| Detail | `GET https://careers.tencent.com/tencentcareer/api/post/ByPostId?postId=<PostId>` | PostId from the search result. |
| robots.txt | Not applicable (404 on API host) | No disallow info; keep volume low. |

## Response shapes

### Query

```json
{"Code":200,"Data":{"Count":767,"Posts":[{"Id":0,"PostId":"2041847335474065408",
  "RecruitPostId":119151,"RecruitPostName":"元宝数据平台-数据工程",
  "CountryName":"中国","LocationName":"西安","BGName":"CSIG","ComCode":"","ComName":"",
  "ProductName":"元宝","CategoryName":"产品","RequireWorkYearsName":"...",
  "Responsibility":"...","LastUpdateTime":"2026年08月10日",
  "PostURL":"http://careers.tencent.com/jobdesc.html?postId=...","SourceID":1,
  "IsCollect":false,"IsValid":true}]}}
```

- `Responsibility` (job duties) is included in list payloads — CLI defers it to `detail`.
- `ComName`/`ComCode` are often empty strings; `BGName` (business group) always present.
- Invalid params (e.g. bad `cityId`) answer `Code≠200` with `Data:null` — never
  send unvalidated ids.

### ByPostId

Adds `Requirement` (任职要求), `Introduction` (岗位介绍), `PostLightItem`,
`ImportantItem`, `LocationId`, `BGId`, `OuterPostTypeID`.

## Known quirks

- `cityId=1000` (and similar guesses) fail — city filtering must be client-side
  on `LocationName` (`包含` match; overseas posts carry `CountryName` "日本" etc.).
- `timestamp` param appears unvalidated — any integer works.
- `LastUpdateTime` format `YYYY年MM月DD日`; no deadline field.
- `PostURL` in the payload uses `http://` — the CLI canonicalizes to
  `https://careers.tencent.com/jobdesc.html?postId=<PostId>`.

## Update checklist when results break

1. `Code≠200` — params changed; diff against the site's own XHR (DevTools).
2. All titles empty or Chinese mojibake — response encoding/field rename.
3. Zero results with `Count>0` on old copies — the CLI's client-side filters
   (`--location`/`--jobage`) are too strict; loosen or drop.
