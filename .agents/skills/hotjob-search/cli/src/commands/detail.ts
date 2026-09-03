import {
  apiPost, canonicalUrl, cleanText, DEFAULT_COMPANY, DEFAULT_TENANT, normalizeDate, normalizePostId,
  type HotjobPost,
} from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
  tenant?: string
  company?: string
}

interface DetailResponse {
  state?: string
  msg?: string
  data?: HotjobPost
}

export interface HotjobDetail {
  id: string
  title: string
  company: string
  location: string | null
  date: string | null
  deadline: string | null
  url: string
  business_unit: string | null
  department: string | null
  category: string | null
  project_name: string | null
  post_code: string | null
  education: string | null
  gender: string | null
  duties: string | null
  requirements: string | null
  description: string | null
  can_delivery: boolean | null
}

export async function fetchDetail(opts: DetailOpts): Promise<HotjobDetail> {
  const postId = normalizePostId(opts.id)
  if (!postId) throw new Error(`could not parse a Hotjob postId from "${opts.id}"`)
  const tenant = opts.tenant || DEFAULT_TENANT
  const body = await apiPost<DetailResponse>("/positionInfo/listPositionDetail", tenant, {
    postId, recruitType: "12",
  })
  if (body.state !== "200" || !body.data?.postName) {
    throw new Error(`Hotjob detail answered state=${body.state ?? "none"}${body.msg ? `: ${body.msg}` : ""}`)
  }
  const post = body.data
  const duties = cleanText(post.workContent)
  const requirements = cleanText(post.serviceCondition)
  return {
    id: postId,
    title: String(post.postName).trim(),
    company: opts.company || DEFAULT_COMPANY,
    location: post.workPlaceStr?.trim() || null,
    date: normalizeDate(post.publishDate),
    deadline: normalizeDate(post.endDate),
    url: canonicalUrl(postId, tenant),
    business_unit: post.company?.trim() || null,
    department: post.department?.trim() || null,
    category: post.postTypeName?.trim() || null,
    project_name: post.projectName?.trim() || null,
    post_code: post.postCode?.trim() || null,
    education: post.education?.trim() || null,
    gender: post.gender?.trim() || null,
    duties,
    requirements,
    description: [duties, requirements].filter(Boolean).join("\n\n") || null,
    can_delivery: typeof post.canDelivery === "boolean" ? post.canDelivery : null,
  }
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  try {
    const detail = await fetchDetail(opts)
    if (opts.format === "json") {
      process.stdout.write(JSON.stringify(detail, null, 2) + "\n")
    } else {
      const lines = [
        detail.title,
        `${detail.company} · ${detail.location ?? "—"}`,
        detail.deadline ? `截止: ${detail.deadline}` : "",
        detail.department ? `部门: ${detail.department}` : "",
        detail.category ? `类别: ${detail.category}` : "",
        "",
        detail.description ?? "(no description)",
        "",
        `URL: ${detail.url}`,
        `postId: ${detail.id}`,
      ].filter((line) => line !== "")
      process.stdout.write(lines.join("\n") + "\n")
    }
    return 0
  } catch (error) {
    process.stderr.write(JSON.stringify({
      error: error instanceof Error ? error.message : String(error),
      code: error instanceof Error && error.message.startsWith("could not parse") ? "BAD_ID" : "DETAIL_FAILED",
    }) + "\n")
    return 1
  }
}
