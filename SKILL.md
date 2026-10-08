---
name: trip-tonic
description: Use when the user asks to plan, compare, or research a trip, itinerary, destination, food, lodging, attractions, or travel pitfalls. TripTonic researches Xiaohongshu user experiences through OpenCLI, tailors choices to the travel party, validates a structured itinerary, and can generate an offline HTML guide plus Markdown, calendar, and map exports. Use only for travel planning, not booking or purchasing.
allowed-tools: Bash(opencli:*), Bash(python:*), Read, Write
---

# TripTonic

TripTonic turns travel research into a practical, personalized and source-traceable trip package. Its workflow combines three ideas:

- **Research from real experiences:** search multiple Xiaohongshu topics, deduplicate results, inspect selected notes and comments, and preserve source URLs.
- **Plan for this travel party:** use travelers' ages, mobility, budget, pace, interests and constraints to choose or reject places rather than ranking by popularity alone.
- **Deliver a checked artifact:** create structured `guide.json`, validate it, then build a self-contained HTML guide and Markdown, ICS and GeoJSON exports with the local scripts in this skill.

The research agent is the curator; OpenCLI is the browser/data access layer; the Python scripts are deterministic validators and renderers. Do not ask the renderer to invent travel facts.

## Trigger and Scope

Use this skill for explicit travel planning, destination comparisons, family/group itineraries, Xiaohongshu-based travel research, and requests for a shareable or downloadable guide. It supports domestic and international destinations and usually works best for trips of 1-14 days.

Do not use it to book or pay for transport, hotels, tickets, tours or meals; provide visa/legal determinations; or perform Xiaohongshu write actions such as likes, saves, follows, posts or messages. If the user only wants a quick general suggestion and declines research, answer briefly without claiming that research was performed.

## End-to-End Workflow

Follow these gates in order. Never proceed to Xiaohongshu search until the OpenCLI installation, bridge and account gates pass.

### 1. Understand the trip and party

Create a concise internal trip brief. Use `references/user-profile.md` for the complete profile fields. Capture the highest-impact details first:

- Destination or route, origin, date/season, duration and occasion (ordinary weekday, weekend, holiday, school break).
- Party size and relevant member roles/ages, especially young children and older adults.
- Budget and whether it includes intercity transport; economy, balanced or comfort preference.
- Pace, interests, must-see and avoid lists, food restrictions/allergies, mobility/accessibility needs.
- Intercity and local transport preference, accommodation preference and day start/end limits.

Ask concise follow-up questions only when an answer changes route feasibility or safety. Do not ask a long questionnaire. Make optional assumptions explicit and editable. Never infer a child's age, a disability, a date, a budget, or consent to use Xiaohongshu.

Save a per-trip profile and research artifacts in a dedicated user-approved output directory, e.g. `./trip-tonic-output/<destination>-<date>/`. Do not write personal profiles into the installed skill directory by default.

### 2. Check OpenCLI installation

Run:

```bash
opencli --version
```

If the command is missing, stop before running any other OpenCLI or Xiaohongshu command. Explain the supported options and wait for the user to install it and confirm it works:

```text
Desktop (recommended): install OpenCLIApp from https://opencli.info/download,
then open System and install or repair the managed opencli command.

CLI only (Node.js >= 20.18.1): npm install -g @jackwener/opencli
```

Do not install software or alter PATH on the user's behalf unless asked.

### 3. Check Browser Bridge and guide sign-in

After installation, run:

```bash
opencli doctor
opencli list -f json
```

Discover the actual command surface with `opencli <site> --help` and each command's `--help`; adapter lists and flags change. If the daemon or extension is unavailable, explain the specific `doctor` result and stop. Guide the user to start Chrome and install/enable OpenCLI Browser Bridge from <https://chromewebstore.google.com/detail/opencli/ildkmabpimmkaediidaifkhjpohdnifk>.

Once the extension connects, tell the user that OpenCLI will open a foreground sign-in page and they must sign into Xiaohongshu themselves. Never ask for or handle passwords, verification codes, cookies or tokens. Use the discovered supported login command (currently `opencli xiaohongshu login --timeout 300 -f json`) and wait for `login_complete` or `already_logged_in`; then run `opencli xiaohongshu whoami -f json`. Search only after identity is confirmed. If the user is on the international Rednote site, inspect `rednote` help and verify that account/session host instead; do not assume XHS and Rednote cookies are interchangeable.

If login is unconfirmed, stop. Offer a separately labeled general-knowledge draft, but never describe it as Xiaohongshu research.

### 4. Research with a bounded search plan

Read `references/opencli-research.md` and record research progress as JSON following `references/research-record-schema.json` (see `references/research-record-template.json` for the structure and `examples/research-record.example.json` for a passing example) in the user-approved trip output directory to preserve search coverage, inspected-note status, evidence limitations, disagreements and decisions. Check the record with `python scripts/trip_tonic.py lint-research <record.json> --strict` before planning; it enforces tiered coverage (by `meta.trip_days`: 1-3 days -> 4 searches/6 notes/3 threads/4 topic axes; 4-7 days -> 6/8/4/5; 8+ days -> 8/10/5/6), topic-axis coverage, recency-filter recording, and gap registration. The worked examples in the research guide are fabricated workflow examples, never real sources.

Generate searches from a topic matrix instead of a fixed count: tag each query with one axis (`itinerary`, `attractions`, `food`, `lodging`, `transport`, `conditions`, `pitfalls`) and keep adding axes-targeted queries (including negative-intent words like 避坑/踩雷/劝退) until the trip-length tier is met or duplicates/risk control stop the search. Adapt queries to season and party constraints, for example `拉萨 亲子 轻松路线`, `林芝 高原反应 老人`, or `西藏 7天 拉萨往返 避坑`; for international destinations add 2-3 queries in the local language or English. Prefer the adapter's date/sort recency filter for time-sensitive subjects and record the filter used.

Run searches sequentially with a pause between queries and tiered limits (first broad query `--limit 15-20`, targeted follow-ups `--limit 10`); cap a session at roughly 15 search requests plus reads. Do not parallel-flood one account; if a risk-control signal appears, stop, record it in `gaps`, and resume later. First use installed adapters discovered from help; preserve the exact signed note URL. If adapter coverage is insufficient, use documented `opencli browser` primitives as a controlled fallback. Do not paste brittle private API/signature recipes into scripts or bypass site controls.

Deduplicate by note ID/URL. Keep a balanced sample, not just the highest-like posts. Score relevance, specificity, recency, first-hand detail, useful disagreement and commercial risk. Likes/collects are discovery signals, not truth scores. Inspect only the strongest notes for the trip's tier (1-3 days: 6-8; 4-7 days: 8-12; 8-14 days: 10-16) and the matching comment-thread count (3-5 / 4-6 / 5-8). If access is blocked, rate-limited, empty or timed out, stop retries and record the research gap.

### 5. Build evidence and personalize decisions

Before planning, create evidence cards with topic, claim, evidence summary, source IDs/URLs, checked date, freshness, confidence (`high`/`medium`/`low`) and caveat. Mark each claim as observed, inferred or requiring confirmation. Keep disagreements visible.

For every candidate attraction, classify `must`, `recommended`, `optional` or `skip` for this party, with a short reason tied to actual constraints. Explicitly screen for altitude, acclimatization, driving time, weather/road dependence, walking/stairs, toilets/rest opportunities, child routines, food restrictions and fatigue. For high-altitude, remote or otherwise safety-sensitive trips, avoid medical assurances; point out uncertainty and advise checking current official guidance and consulting a clinician for personal health concerns.

Treat Xiaohongshu as experience evidence. For opening status, tickets, permits, transport schedules, weather, road conditions, altitude/safety rules and legal requirements, seek authoritative current sources when available. Do not invent prices, exact travel times, coordinates, dates or availability. Label user-reported prices and all estimates.

### 5a. Produce a usable route, timed itinerary, stays and merchants

The guide must include both a **whole-trip route overview** and a **day-by-day timed itinerary**. Do not treat a list of attractions as a route.

- Add `route.overview`, ordered `route.stops`, and `route.legs` to `guide.json`. Each leg should include origin, destination, mode, source-backed distance/duration where available, and `estimated: true` when derived from a planner or a rough estimate. Use `duration_text` for honest ranges such as "about 3-4 hours"; use numeric `duration_min` only when a useful single value is justified. If no reliable route service is available, state that the time/distance is unverified instead of manufacturing precise numbers.
- In each day, include time windows for transit, visits, meals, rest and check-in. Account for transfer time between items with `route_from_previous`; use buffers for parking, queues, altitude, weather and airport/rail transfers. The validator must pass without overlaps or impossible transfers.
- Recommend lodging by **specific property when evidence supports it**, otherwise give a clearly labeled area shortlist. Include why it fits this party, location/address or map link when verified, parking/transport, cancellation/accessibility details when known, price/date checked, source IDs and confidence. Do not present a search result or sponsored post as an endorsement without noting its commercial risk.
- Recommend restaurants and relevant merchants (for example rental providers, guides or scenic-area services) only when they materially help the trip. Capture exact name, category, location, operating hours/contact/price only when verified, fit rationale, checked date, evidence source and caveat. Never imply a booking or current availability.
- Unless the user declines, include at least two researched lodging candidates and three food/shop recommendations for trips of 2+ days when research access yields candidates. If unavailable or verification fails, say so in `assumptions` and leave a visible `warning`; never invent merchant names.
- Keep scenic and editorial choices separate from logistics. Each stop should connect to evidence or be labeled as a general-knowledge suggestion; add backup options for weather/closure/fatigue via the `backup` field (day-level and item-level, each entry an object with `condition` and `plan`).

### 5b. Add a truthful visual layer

- Search for images only when useful and use images supplied by the user or from a source/license that permits embedding. Preserve attribution/license and source IDs in `images`; store approved local files under the trip output directory and use relative paths.
- The builder embeds supported local images into the HTML for offline use. It must not silently fetch remote images, scrape protected images, or claim image-rich output when no images were supplied.
- Always provide a route overview graphic (the builder may render a clearly labeled **not-to-scale** route schematic from ordered stop names). Do not draw a geographic map from unverified coordinates. GeoJSON only contains verified coordinates.
- The visual layer is: user-supplied `images` and research-captured `sources[].media` (rendered as a grouped album with captions and source links). When neither exists the guide stays text-first — do not pad it with decorative illustrations, and never claim that real images were embedded.
- Include useful alt text and captions; if there are no usable images, render an explicit text-first guide rather than broken image boxes.
- Capture the image/video URLs the research adapter actually returned (from note details or search covers): copy them from the research record's `notes[].media` into `guide.json` `sources[].media` as `{type: "image"|"video", url, description}`. The guide renders a clickable "Travel Photos & Videos" album (旅行影像) so readers can view attraction visuals in the source notes. If the adapter's note output contains no media fields, do not report "no media available": apply the browser-fallback extraction recipe in `references/opencli-research.md` (open the note page, read `__INITIAL_STATE__.note.noteDetailMap`, take at most the first 4 images per note). Default to link-only: signed links expire, so keep the source note link beside them and re-check within 14 days. When `sources[].media` has entries, ask the user once whether to embed media offline; if yes (or when the user requested media up front), run `fetch-media` and build with `--media-cache` (see step 7): downloads are content-verified, stay local, keep the source attribution, and are for the user's personal reference only — never re-host or redistribute them.

### 6. Create structured `guide.json`

Use `references/guide-schema.json` and `examples/guide-template.json` as the data contract and starter structure. `examples/tibet-7-days.json` is an explicitly unverified structural example, not a researched itinerary. Replace template dates, party details and placeholders. Include:

- Trip metadata and the assumptions/profile that materially influenced the plan.
- Sources with stable IDs, title, URL when available, type and checked date; optionally `media` entries (image/video links exactly as returned during research) for the rendered media-links section.
- Day-by-day items with date, start/end, description, price label, coordinates only if verified, and source IDs.
- Transport, lodging areas, foods, avoid/pitfall list, budget ranges, weather/backup notes and party-specific tips.
- Evidence confidence/freshness and recommendation class where relevant. These may be preserved as additional fields; the local renderer ignores fields it does not display.
- Overall route (`route.overview`, ordered stops and leg-by-leg time/distance/mode with estimate flags), complete daily timelines and explicit transfer buffers.
- Lodging and merchant recommendations with exact business identity, suitability rationale, address/contact/price only when checked, checked date, confidence and source IDs.
- Optional local visual assets with attribution/license, alt text and captions; never use unverified coordinates to place map markers.
- `backup` entries (object with `condition` and `plan`) for weather/closure/fatigue alternatives, at day or item level.
- `checklist` pre-trip verification entries (title, detail, optional date); entries with a date become all-day calendar events in the ICS export.
- `evidence` cards (topic, claim/summary, confidence, checked_at, caveat, source IDs) that keep disagreements visible in the rendered guide.

For missing dates, ask if dates matter (seasonality, closures, holidays); otherwise use an explicit planning date assumption. The builder requires concrete ISO dates to produce calendar output. Never imply a guessed date is confirmed.

### 7. Validate and build artifacts

Use Python 3.8+; the local build pipeline uses only the standard library:

```bash
python scripts/trip_tonic.py validate <output-dir>/guide.json
python scripts/trip_tonic.py build <output-dir>/guide.json --output-dir <output-dir>
# 可选：用户要求离线媒体时，先下载缓存再构建相册
python scripts/trip_tonic.py fetch-media <output-dir>/guide.json            # 缓存写入 guide 同级 media-cache/
python scripts/trip_tonic.py build <output-dir>/guide.json --output-dir <output-dir> --media-cache <output-dir>/media-cache
```

With `--media-cache`, cached entries render as a clickable album (images embedded as data URIs, videos copied into `<output-dir>/media/` with a lightbox for paging and playback); uncached entries stay link cards. `fetch-media` is idempotent, verifies file magic numbers (a fake image that is really an HTML error page is rejected), enforces size caps (images 10 MB, videos 200 MB), and treats download failures of signed links (HTTP 403/expired) as expected: the guide falls back to link cards, never a build failure. Keep the `media/` folder next to `guide.html` when archiving, and mention in the guide that cached media is for personal reference only.

Additional tooling: `init <dir> [--start-date --days --title --destination --origin --travelers --pace --force]` scaffolds a guide.json from the blank template with profile fields; `compare a.json b.json` prints a structural diff plus a day-by-day semantic diff (added/removed items, time changes) and tradeoff notes; `migrate guide.json [--target 1.0]` upgrades a missing/0.x schema version with an explicit target; `lint-research record.json [--strict]` checks a JSON research record against `references/research-record-schema.json` (tiered coverage by `meta.trip_days`: 1-3 days 4/6/3, 4-7 days 6/8/4, 8+ days 8/10/5 searches/notes/threads, plus topic-axis and recency-filter checks); `serve guide.json --output-dir <dir> [--port]` serves the built artifacts over local HTTP and rebuilds when the guide JSON changes. `validate`/`build` accept `--today` (override the staleness reference date) and `--strict` (fail when warnings remain); `build` also accepts `--media-root` for the image directory (default: the guide JSON's folder), `--online-map` to embed a Leaflet online map (CDN, requires network when opened; default off to keep the guide offline self-contained) and `--media-cache` for the fetch-media cache directory; `serve` accepts `--media-cache` as well; `fetch-media guide.json [--cache-dir --timeout]` downloads registered media links into a local cache.

The validator reports structural errors, source references, time overlaps, too-short transfer gaps, missing recommendations/visuals, missing self-drive distance or duration, source-age warnings, pace overload versus `preferences.pace`, day-start transfer gaps, lodging continuity for multi-day trips, driving-fatigue limits, budget total mismatches, stale hotel/food records, and pitfall entries that would render empty (`avoid` items need `wrong`+`right` or `name`+`reason`; both styles render). Fix errors and material conflicts before building. Warnings must either be resolved or surfaced in the final guide. Never use a force/allow-invalid option to hide a material conflict. For self-driving trips, include road distance and realistic driving-time range per leg, or explicitly state each is unverified and why.

Expected outputs are a self-contained responsive `.html`, `.md`, `.ics`, `.geojson`, `.kml`, normalized `.json`, and validation report. HTML is offline-readable and printable; approved local images are embedded for offline use. HTML/Markdown include a trip statistics section (days, items, meals, drive totals, longest leg, pace verdict) with SVG Gantt timeline and budget-category pie charts. When media caching was requested, the HTML also includes the media album (lightbox paging/playback, images inline, videos under `media/`) and the Markdown links the local video files. Full body text switches to English when `meta.language` starts with `en`. A text-first complete guide is preferable to a broken image/download flow. The HTML and Markdown should show route overview and legs, timed daily plan, stays, merchant/food suggestions, sources and unresolved checks.

### 8. Respond with artifacts and a concise summary

Lead with output paths, then summarize route logic, party-specific decisions, key caveats, source coverage and unresolved checks. Include the Markdown content or a readable itinerary preview in the chat. Link to source note titles and URLs; remind readers that signed Xiaohongshu URLs may require a logged-in browser and expire. Do not claim ticket/hotel booking or real-time confirmation.

## Evidence and Freshness Rules

- `high`: multiple independent, recent, specific sources agree, or an authoritative current source directly confirms the claim.
- `medium`: a detailed first-hand source or several partial sources support it; current authoritative confirmation is absent.
- `low`: one sparse, old, promotional or ambiguous source. Treat it as a lead, not a planning fact.
- `estimated`: route duration, budget or distance is a model estimate, not a live measurement.
- `user_reported`: price, queue or service detail comes from a user's post/comment and may have changed.

Every important recommendation must connect to at least one real source or be clearly marked as general knowledge/estimate. A source list alone is insufficient if the itinerary makes unsupported claims.

## Failure and Privacy

- OpenCLI missing: stop and provide install options.
- Bridge unavailable: stop and guide extension setup.
- User not logged in: ask them to complete sign-in; never collect credentials.
- Search blocked or partial: preserve obtained evidence, report coverage, and ask whether to continue with a clearly labeled non-XHS draft.
- Optional route service/key missing: use an explicitly labeled estimate or leave the leg unquantified. Never request an API key in chat; read only a user-configured environment variable if a future route provider is intentionally added.
- Script/build error: show the actionable error, preserve source files, fix the input or report inability. Do not silently emit a claimed-complete artifact.
- Store personal travel-party profiles only in the user's chosen output folder. Do not commit them or place them in shared skill assets.

## Completion Checklist

- OpenCLI installation, bridge and user login were checked in sequence before Xiaohongshu search.
- The profile covers relevant ages, pace, mobility, budget, interests and exclusions, or labels assumptions.
- A whole-trip ordered route and time-windowed daily itinerary are present; transfer times are sourced or explicitly estimated and buffered.
- Accommodation and merchant recommendations have a party-fit reason, checked date and traceable sources, or are clearly identified as areas/categories to research rather than endorsements.
- The output contains named, sourced hotel and food/shop candidates when research supports them; missing recommendations and self-drive distance/time are visibly called out rather than silently omitted.
- Visuals are licensed/user-supplied, attributed, locally embedded and have alt text; media album items come from research with the source note linked beside them; route schematic is labeled not-to-scale (or coordinate-proportional when all stops have verified coordinates) and map coordinates are verified.
- If no real image or research media is embedded, the guide is explicitly text-first; no decorative illustration is generated and no visual richness is claimed.
- Weather/closure/fatigue backup options are recorded via `backup` where relevant; pre-trip verification items appear in `checklist`; claims trace through `evidence` cards.
- Search spans multiple topics; candidates are deduplicated and a balanced selection was read.
- Key itinerary choices are party-specific, source-linked and confidence/freshness labeled.
- High-risk or time-sensitive information has an authoritative verification note or a clear unresolved warning.
- `guide.json` validates; overlaps and impossible transfers are fixed or explicitly disclosed.
- Generated output files exist and are linked; no unsupported booking, live-data or research claim is made.
