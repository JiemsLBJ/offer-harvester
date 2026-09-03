# Wecruit / Hotjob URL and API anchors

Verified on 2026-09-01 against Deloitte China's public internship site.

## Tenant and public routes

- Deloitte tenant: `SU64365a780dcad43c5ae82bab`
- Internship list: `https://wecruit.hotjob.cn/<tenant>/pb/interns.html`
- Exact posting: `https://wecruit.hotjob.cn/<tenant>/pb/posDetail.html?postId=<id>&postType=intern`
- A `postId` is a 24-character hexadecimal identifier.

Never store the list URL with a fragment or invented query as a posting URL.

## Public endpoints

Both endpoints are anonymous `POST` requests with
`Content-Type: application/x-www-form-urlencoded`.

### Search

`https://wecruit.hotjob.cn/wecruit/positionInfo/listPosition/<tenant>?iSaJAx=isAjax&request_locale=zh_CN&t=<milliseconds>`

Body fields used by the public page:

- `isFrompb=true`
- `recruitType=12` (internships)
- `pageSize`, `currentPage`
- `postName` (title keyword)

The response contract is `state="200"` and
`data.pageForm.{dataCount,totalPage,pageData}`. Useful fields include `postId`,
`postName`, `company` (business unit, not employer), `department`,
`workPlaceStr`, `publishDate`, `endDate`, `postTypeName`, `projectName`, and
`postCode`.

### Detail

`https://wecruit.hotjob.cn/wecruit/positionInfo/listPositionDetail/<tenant>`

Body:

- `postId=<id>`
- `recruitType=12`

The response contract is `state="200"` and `data`. Duties are in `workContent`,
requirements in `serviceCondition`, and exact identity/deadline fields repeat
the list data. `canDelivery` is meaningful on this detail endpoint; the list
endpoint may report `false` for anonymous visitors and must not be used as the
closed-job signal.

## Application behavior

The exact posting page renders a `.deliver` entry button. Anonymous users are
sent to the site's normal login flow. Authenticated users are shown a resume or
application preview. Clicking that entry is not the final submit; final delivery
must remain behind `apply_bot`'s per-job confirmation gate. OTP, QR login, and
CAPTCHA are always manual.
