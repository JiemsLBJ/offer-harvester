import { apiGet, cleanHtml, normalizeDate, canonicalUrl, normalizeId, type TencentPost } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

export interface TencentDetail {
  id: string
  title: string
  company: string | null
  location: string | null
  date: string | null
  url: string
  business_group: string | null
  category: string | null
  product: string | null
  introduction: string | null
  description: string | null
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  const postId = normalizeId(opts.id)
  if (!postId) {
    process.stderr.write(
      JSON.stringify({ error: `could not parse a PostId from "${opts.id}" (want a jobdesc.html?postId=... URL or a plain numeric id)`, code: "BAD_ID" }) + "\n",
    )
    return 1
  }
  try {
    const body = await apiGet(
      `https://careers.tencent.com/tencentcareer/api/post/ByPostId?postId=${encodeURIComponent(postId)}`,
    )
    if (!body || body.Code !== 200 || !body.Data) {
      process.stderr.write(
        JSON.stringify({ error: `tencent API answered Code=${body?.Code ?? "none"} (post not found?)`, code: "NOT_FOUND" }) + "\n",
      )
      return 1
    }
    const p = body.Data as TencentPost
    const detail: TencentDetail = {
      id: postId,
      title: p.RecruitPostName || "(untitled)",
      company: p.ComName || "腾讯",
      location: [p.CountryName, p.LocationName].filter(Boolean).join(" · ") || null,
      date: normalizeDate(p.LastUpdateTime),
      url: canonicalUrl(postId),
      business_group: p.BGName || null,
      category: p.CategoryName || null,
      product: p.ProductName || null,
      introduction: cleanHtml(p.Introduction),
      description: cleanHtml([p.Responsibility, p.Requirement].filter(Boolean).join("\n\n")),
    }

    if (opts.format === "plain") {
      const lines = [
        detail.title,
        `${detail.company ?? "—"} · ${detail.location ?? "—"}`,
        detail.date ? `Updated: ${detail.date}` : "",
        detail.business_group ? `BG: ${detail.business_group}` : "",
        detail.category ? `Category: ${detail.category}` : "",
        detail.product ? `Product: ${detail.product}` : "",
        "",
        detail.description ?? "(no description)",
        detail.introduction ? `\n岗位介绍:\n${detail.introduction}` : "",
        "",
        `URL: ${detail.url}`,
        `postId: ${detail.id}`,
      ].filter((l) => l !== "")
      process.stdout.write(lines.join("\n") + "\n")
    } else {
      process.stdout.write(JSON.stringify(detail, null, 2) + "\n")
    }
    return 0
  } catch (e) {
    process.stderr.write(
      JSON.stringify({ error: e instanceof Error ? e.message : String(e), code: "DETAIL_FAILED" }) + "\n",
    )
    return 1
  }
}
