---
name: job-form-filler
description: "Safely fills job application forms with the AI Job Search Playwright pipeline. Use when a user asks to fill, autofill, inspect, or submit a job application form on a supported recruiting portal or an unfamiliar company careers site. Selects a verified dedicated adapter when available and otherwise uses the explicit generic fill-only fallback, learns missing form requirements, and stops for human review."
---

# Job Form Filler

Run from the repository's `automation` directory. Read `automation/README.md` and, when present, `AUTOMATION_HANDOFF.md` before modifying adapters or safety behavior.

## Choose the mode

1. Prefer the URL-recognized dedicated adapter. Current dedicated adapters are ByteDance, Shixiseng, Tencent, Wecruit/Hotjob, Nowcoder, BOSS, Xiaohongshu, Bilibili, and Zhaopin. The Hotjob adapter covers verified `wecruit.hotjob.cn/.../pb/posDetail.html` pages; do not assume older `www.hotjob.cn/wt/...` systems share its structure.
2. Use `generic` only when no dedicated adapter recognizes the URL and the user supplies the direct application-form URL. Never use generic mode on a job list, job detail, login landing page, or unknown one-click-apply button.
3. If the page has changed, use `--probe`, inspect the saved structure snapshot, then update the dedicated adapter. Do not guess selectors that could submit an application.

## Dedicated adapter workflow

Fill, learn, and keep the browser open for review:

```powershell
python -m apply_bot.apply_one "<job-url>" --fill-only --review --expect-company "<company>" --expect-title "<title>"
```

Only when the user explicitly asks to submit, rerun without `--fill-only`. The terminal must display the per-job confirmation summary, and only an entered `y` authorizes that single submission.

## Generic fallback

Have the user log in and navigate to the actual form if necessary, then run:

```powershell
python -m apply_bot.apply_one "<direct-form-url>" --portal generic --fill-only --review
```

Generic mode fills only empty, non-sensitive text/select fields that can be grounded in the structured profile. It does not click Apply, upload an ambiguous file input, or submit. It may upload the selected resume only through a visible control explicitly labelled resume/CV; QQ Docs' narrowly identified resume questionnaire is supported this way. The user reviews the visible page and handles unsupported widgets manually.

## Preserve the review browser

`--review` starts system Chrome as an independent process with a loopback-only CDP port. When filling completes, is blocked, or raises an automation error, Playwright disconnects and the Chrome window stays open until the user closes it. Do not add a terminal `input()` hold or call `browser.close()` for this mode.

Use a separate persistent profile for sites that need independent login state or simultaneous review windows:

```powershell
python -m apply_bot.apply_one "<job-url>" --fill-only --review --profile-dir "apply_bot/.chrome-profile-<site>"
```

If Chrome really crashes or a page closes, inspect `apply_bot/state/browser_events.jsonl`. Diagnostics may contain the portal, workflow stage, exception type, and URL without its query string or fragment; never add form values, cookies, tokens, or uploaded document contents.

## Learn from every form

The pipeline snapshots field labels and static selector metadata without reading input values. It records covered, missing, unmapped, and manual-sensitive requirements in the local dashboard. Never invent an answer. Ask the user to resolve missing facts later in the dashboard; saved answers then become available to future forms.

## Safety invariants

- Never persist an ID-card number or copy it into logs, screenshots, the profile, or the dashboard.
- Never bypass CAPTCHA, QR login, SMS verification, paywalls, or risk controls.
- Never send BOSS messages, emails, or other external communications automatically.
- Never batch-submit. Dedicated submission always requires a fresh per-job `y`; generic mode never submits.
- Stop on already-applied, closed, mismatched-company, or mismatched-title signals and ask the user.
