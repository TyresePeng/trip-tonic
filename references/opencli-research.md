# OpenCLI Xiaohongshu Research

This is a research workflow, not a scraping implementation. OpenCLI owns browser transport and the user-authenticated session. Discover the installed commands at runtime; never rely on an adapter list copied into this document.

## Gate order

```bash
opencli --version
opencli doctor
opencli list -f json
opencli xiaohongshu --help
opencli xiaohongshu search --help
opencli xiaohongshu note --help
opencli xiaohongshu comments --help
opencli xiaohongshu login --help
```

If `opencli --version` cannot run, stop and guide installation. If `doctor` reports the extension disconnected, fix Chrome/extension first. Once the bridge works, let the user complete the supported foreground login flow, then verify with `opencli xiaohongshu whoami -f json`. Never request credentials or copy cookies. Only then search.

If using Rednote, discover its own help and verify its own authenticated session. Do not assume the Xiaohongshu and Rednote domains share cookies or signed links.

## Search matrix

Coverage requirements scale with trip length (record `meta.trip_days` in the research record; `lint-research` uses it to pick the tier):

| Trip length | Searches | Notes fully read | Comment threads | Topic axes required |
| --- | ---: | ---: | ---: | ---: |
| 1-3 days | 4-6 | 6-8 | 3-5 | >=4 of 7 |
| 4-7 days | 6-10 | 8-12 | 4-6 | >=5 of 7 |
| 8-14 days | 8-14 | 10-16 | 5-8 | >=6 of 7 |

Tag every search with one `topic` axis: `itinerary`, `attractions`, `food`, `lodging`, `transport`, `conditions`, `pitfalls`. Fill the matrix topic by topic instead of firing near-duplicate queries; add follow-up searches for uncovered axes rather than more queries on covered ones. Stop adding searches when every axis has enough support or a duplicate/risk-control stop condition triggers.

Adjust queries for destination, season, party, duration and constraints. Combine positive and negative intent (negative words retrieve failure reports that likes-sorted feeds hide):

```text
<destination> <days>天 攻略 / 行程 / 路线 顺序
<destination> <season/month> 旅行体验 / 近期
<destination> 适合老人/亲子/轻松路线
<destination> 美食 本地人 / 具体店名
<destination> 住宿 酒店 停车 评价 / 具体区域
<destination> 租车 商家 保险
<destination> 交通 排队 避坑
<destination> 踩雷 / 后悔 / 劝退 / 不建议
<attraction/candidate exact name> 避雷 / 近期
```

For international destinations add 2-3 queries in the destination's local language or English (overseas-Chinese and student residents post local knowledge that Chinese-only queries miss). For time-sensitive subjects (tickets, closures, road status, seasonal access), prefer the adapter's date/sort filter to recent results when supported, and record the filter used in the search entry's `filters` field; record `published_at` when the adapter returns it.

Run sequentially with a pause between queries, JSON output, and tiered limits: the first broad itinerary query may use `--limit 15-20`, targeted follow-ups stay at `--limit 10`:

```bash
opencli xiaohongshu search "拉萨 7天 攻略" --limit 15 -f json
opencli xiaohongshu search "拉萨 适合老人 轻松路线" --limit 10 -f json
opencli xiaohongshu search "西藏 高原反应 老人 注意事项" --limit 10 -f json
```

Check actual flag choices with `--help` before using sort/date filters. Cap a single session at roughly 15 search requests plus note/comment reads. Do not issue queries concurrently against one logged-in profile. If a risk-control signal appears (empty results, captchas, errors), stop, record the signal in `gaps`, and resume later or with fewer requests. Stop when new queries mostly return duplicates.

## Candidate selection

Deduplicate by stable note ID or URL. Keep title, author, URL exactly as returned, engagement fields, publication date if actually present, and which queries found the note. Balance broad itineraries, specific places, transport/lodging/food and negative/recent reports.

Engagement is a discovery signal only. Prefer specific first-hand reports, clear dates/context, concrete route and cost details, corroborating comments, and useful limitations. Lower confidence for promotional language, vague listicles, recycled content, and old notes on seasonal or policy-dependent subjects.

For hotels and merchants, search both category/area and exact candidate names. Separate first-hand visits from ads, affiliate posts, group-buying promotions and merchant-owned accounts. A note can surface a candidate, but current address, operating hours, price, booking/contact and service availability require a current authoritative listing or direct public merchant source. Record checked date, exact name, evidence, caveats and source IDs. Never invent a business or turn an unverified note into an endorsement.

For imagery, do not treat Xiaohongshu images as reusable assets. Ask for user-supplied images or use sources whose license permits the intended embedding; retain attribution and license. If no such image is available, produce the designed text guide and route schematic without claiming photo coverage.

## Deep reading

Inspect the exact `xiaohongshu note --help` and `comments --help` output. Pass through the exact signed URL returned by the search result; do not strip tokens or substitute a bare ID unless current command help explicitly supports it.

Read the tier-appropriate number of notes and comment threads (table above; for a normal 4-7 day trip: 8-12 notes and 4-6 comment threads). Read comments selectively to resolve queues, current conditions, accessibility, group suitability, and source disagreements. Limit each comment request. Record the title, exact URL, what claim it supports, and check date. Prefer notes with a recent `published_at` for time-sensitive claims; a popular old note is not evidence of current conditions.

Capture media links: when the note detail or search result returns image/video URLs (cover images, note images, video streams), record them in the note's `media` array as `{type: "image"|"video", url, description}` using the exact returned URL. Media links are evidence pointers, not reusable assets: keep them link-only in the research record and later in `guide.json` `sources[].media`; do not download or re-host them during research. Signed media URLs expire quickly — pair each with the note URL so readers can fall back to the source note, and expect the validator to warn when the checked date is older than 14 days. The only sanctioned download path is the user-requested, explicit `fetch-media` build step (personal offline reference with attribution kept; see SKILL.md step 7); never treat media as redistribution-ready assets.

Media capture fallback when the adapter omits URLs (verified 2026-10, adapter 1.8.6): `xiaohongshu note` returns only title/author/content/likes/collects/comments/tags — no media fields — and `search` results carry no cover URLs. Do not conclude "no media available" from empty adapter output. Instead use the browser fallback for inspected notes: open the exact signed note URL in a browser session, wait ~8-10 s for the SPA to render, then eval JS reading `window.__INITIAL_STATE__.note.noteDetailMap` — each entry's `note.imageList[].urlDefault` (fallback `.url`) holds the note's own images (ignore `sns-avatar` URLs and page-ambient thumbnails), `note.video.media.stream.h264[0].masterUrl` holds the video stream, and `note.displayTitle` confirms the match. Take at most the first 4 images per note. Practical notes: `note` under an ephemeral adapter session may return SECURITY_BLOCK (risk control) while the same page still renders in a real browser session (`--site-session persistent`); pause a few seconds between notes and stop if a browser page is blocked too. On Windows, URLs containing `&` are mangled by the `.cmd` launcher — invoke the underlying `opencli-app.exe __opencli_shim ...` directly from a subprocess list to keep args intact. Record captured URLs into `notes[].media` and copy them into `guide.json` `sources[].media` during structuring; run `fetch-media` only at the user's request.

Use structured adapter commands first. If a field is unavailable and a browser fallback is necessary, consult `opencli-browser` and follow its inspect-before-act rules. Prefer API/network data where available to page scraping. Do not use undocumented signature replay, copied cookies, stealth/bypass techniques, or high-volume crawling.

## Evidence card

```json
{
  "id": "xhs-note-01",
  "topic": "route",
  "subject": "拉萨往返七日环线",
  "claim": "行程中安排适应和休息时间",
  "kind": "observed",
  "confidence": "medium",
  "freshness": "recent_user_report",
  "checked_at": "2026-09-23",
  "source_ids": ["xhs-01", "xhs-02"],
  "caveat": "不构成高原医学建议；交通和天气需另行确认"
}
```

Confidence:

- `high`: independent recent sources agree and the claim is specific; authoritative current confirmation is better for operational facts.
- `medium`: one detailed first-hand source or several partial sources support it.
- `low`: one vague, old, promotional, or ambiguous source; use as a lead only.

## Worked example (fictional data)

The records below are **fabricated examples for demonstrating the workflow**. They are not real Xiaohongshu posts, search results, business recommendations, or travel facts. Never copy them into a user's guide as research. A real research record must come from output actually returned by OpenCLI and content actually inspected by the agent.

### 1. Record the search and preserve candidates

For each query, retain the exact query, check date, result count, and candidate IDs/URLs as returned. Deduplicate candidates by note ID or exact URL; do not turn search-card text into a claim from a note you have not opened.

```text
Query: <destination> 周末 轻松路线
Checked: 2026-09-23 (fictional example date)
Returned: 10 results
Candidates:
- demo-note-01 | [fictional title about a morning visit] | URL: not supplied (demo)
- demo-note-02 | [fictional title about transport and parking] | URL: not supplied (demo)
Search-card-only; neither note has been read yet.
```

### 2. Turn opened notes into source records

After opening a candidate, distinguish the author's first-hand observation from opinion, promotion, and facts that need independent/current confirmation. Preserve the exact returned title and URL in real work; summarize only what was actually visible.

| Demo ID | What was inspected | Illustrative observation (not a fact) | Limits to record |
| --- | --- | --- | --- |
| `demo-note-01` | Fictional full note | Author says arriving early made their visit feel less crowded | No visit date or measured wait; one person's experience |
| `demo-note-02` | Fictional full note | Author describes using public transit, then walking to the entrance | Route, service, and walking distance need current/official checks |
| `demo-note-03` | Fictional full note; promotional relationship disclosed | Author praises a named lodging area | Commercial content; does not establish property quality or availability |

In real guide data, create one `sources` entry per inspected note, using its actual stable ID, exact title/URL when available, type `user`, and actual `checked_at`. Do not invent note IDs, dates, authors, URLs, or engagement counts when the adapter did not return them.

### 3. Use comments to qualify, not overwrite, the note

Example of a fictional comment review:

```text
demo-note-01 comments (fictional):
- One commenter says a later arrival was crowded on a holiday.
- Another asks whether the early-entry time applies every day; no verified answer.
Takeaway: keep the author's experience as a single observation; label holiday
variation and opening/entry rules as unresolved, then check an authoritative source.
```

Comments are separate evidence, not confirmation by default. Capture the comment thread's source context and check date when relevant. Do not infer current operating rules from an unanswered question or an isolated reply.

### 4. Build evidence cards and preserve disagreement

```json
[
  {
    "id": "demo-evidence-01",
    "topic": "crowds",
    "subject": "visit timing",
    "claim": "One fictional author reports a quieter experience early in the day",
    "kind": "observed",
    "confidence": "low",
    "freshness": "unknown",
    "checked_at": "2026-09-23",
    "source_ids": ["demo-note-01"],
    "caveat": "Fabricated workflow example; not travel advice. No measured wait or date."
  },
  {
    "id": "demo-evidence-02",
    "topic": "crowds",
    "subject": "holiday variation",
    "claim": "A fictional commenter reports crowding later on a holiday",
    "kind": "observed",
    "confidence": "low",
    "freshness": "unknown",
    "checked_at": "2026-09-23",
    "source_ids": ["demo-note-01"],
    "caveat": "Single unverified comment; holiday/date context is incomplete."
  }
]
```

The two cards are compatible but limited: they do not establish a guaranteed quiet time. If real sources conflict, keep both claims, note differences in date/season/route/party or commercial context, reduce confidence as appropriate, and plan a flexible alternative rather than selecting whichever claim is more convenient.

### 5. Connect evidence to decisions

For each itinerary choice, make the reasoning traceable: candidate → evidence → party-fit decision → unresolved check. For example, a fictional note about walking should prompt checking actual distance/accessibility and the party's mobility needs; it does not justify claiming a route is accessible. If no reliable evidence supports a candidate, mark it as a general suggestion or omit it. Keep operational facts (hours, tickets, schedules, current access) separate and seek current authoritative confirmation.

This example is intentionally not a source pack: it contains no real note links, usable destination facts, or endorsements.

Source types in guide data: `user`, `search`, `official`, `estimate`, and `general`. For source URLs, retain only links actually seen. Signed URLs can be session-bound or expire; include the original title so readers can search it in the Xiaohongshu app if the link stops working.

## Do not claim

- A note was read when only its search card was seen.
- A fact is current because its post has many likes.
- A ticket price, schedule, opening status, weather, road condition or safety rule is official based on UGC alone.
- The browser was searched when the bridge/login gate failed.
