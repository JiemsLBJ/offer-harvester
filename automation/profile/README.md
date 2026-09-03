# Candidate Profile (structured)

`profile.json` is the **base structured source of truth** for form filling by
`apply_bot`. It mirrors the canonical candidate profile
(`.claude/skills/job-application-assistant/01-candidate-profile.md` + `CLAUDE.md`),
which remain authoritative for CV/cover-letter drafting.

## Grounding rule

Every value in `profile.json` must trace to one of:

- `.claude/skills/job-application-assistant/01-candidate-profile.md`
- `CLAUDE.md` (Candidate Profile section)
- The master CV `cv/main_example.tex`

A value that appears in profile.json but in none of the three is a fabrication —
remove it.

Facts explicitly supplied by the candidate through the local job dashboard are stored in
the gitignored `supplemental_profile.json`. `model.load_profile()` overlays those
path-based values at runtime. This is the only exception to the source-first rule: it is
allowed because the candidate is the direct source, and the audit log records only the
field path and timestamp, never a duplicate value.

## Sensitive fields (read this before editing)

| Field | Policy |
|---|---|
| `identity.id_card.value` | **Never fill in.** Leave `null`. Raw ID numbers must not be written to any file, log, or tracker. If a form requires one, enter it manually at the confirmation gate for that one submission only (`authorized: true` means the user authorized manual entry for this session, not that a value exists). |
| `identity.phone` / `email` | Real values (as in the profile source) — filling these is part of a normal application. The confirmation gate still lists them before any submit. |
| `identity.gender` / `birthday` / `wechat` | `null` until the user states them. Never guess. |

The dashboard refuses any supplemental path beginning with `identity.id_card`, and the
model loader forces `identity.id_card.value` back to `null` even if the local supplement
file is tampered with.

## Fields map (form → profile key)

| Form field | profile key |
|---|---|
| 姓名 | `identity.name` |
| 手机号 / 电话 | `identity.phone` |
| 邮箱 | `identity.email` |
| 学校 | `education[].school` |
| 专业 | `education[].major` |
| 学历/学位 | `education[].level` / `degree` |
| 在读/毕业时间 | `education[].start` / `end` |
| GPA/排名 | `education[].gpa` / `ranking` |
| 实习经历 | `experience[]` (company/role/start/end/bullets) |
| 项目经历 | `projects[]` (name/role/description/short_60) |
| 自我评价 | `self_intro.zh_200` (over-limit fields: count characters first) |
| 可到岗时间 | `availability.start_date` |
| 实习时长 | `availability.min_months` + `days_per_week` |
| 期望城市 | `availability.cities` |

## Maintenance

- Add a fact to the sources first, then mirror it here (the `/apply` workflow
  already writes confirmed facts back to `01-candidate-profile.md`).
- After any edit, re-verify against the three sources and re-read
  `self_intro` for character limits.
- For a new form-only field, open the dashboard's “资料缺口” view, confirm its profile
  path and supply the value once. Do not add guessed values merely to clear the queue.
