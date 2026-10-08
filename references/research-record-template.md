# Research record template

Copy this file into the user-approved trip output directory. Replace every placeholder only with information actually returned by OpenCLI or directly inspected in the source. Keep the exact signed note URL privately in the trip artifact if needed; do not publish credentials, cookies, or tokens. A search card is not an inspected note.

A machine-checkable JSON alternative is available: follow `references/research-record-schema.json` (structure shown in `references/research-record-template.json`, passing example in `examples/research-record.example.json`) and validate with `python scripts/trip_tonic.py lint-research <record.json> --strict`. The JSON record is required when coverage thresholds need to be enforced before planning.

## Search log

| Query | Checked at | Result count | Candidate IDs/URLs | Notes |
| --- | --- | ---: | --- | --- |
| `<exact query>` | `YYYY-MM-DD` | `<count or unknown>` | `<exact returned IDs/URLs>` | `<coverage, errors, duplicates>` |

## Note record (copy per note)

```yaml
source_id: "<stable local ID>"
returned_note_id: "<exact ID or unknown>"
title: "<exact returned title>"
author: "<returned name or unknown>"
url: "<exact returned URL or omit>"
published_at: "<observed date or unknown>"
checked_at: "YYYY-MM-DD"
inspection: "search_card_only | full_note_opened | comments_opened"
queries_found_by: ["<search query IDs or exact query>" ]
commercial_context: "unknown | disclosed | suspected | none_observed"
first_hand_context: "<what author says they personally did, or unknown>"
observations:
  - claim: "<narrow claim actually supported by inspected content>"
    kind: "observed | opinion | inference | requires_confirmation"
    confidence: "high | medium | low"
    caveat: "<date, season, party, missing detail, or other limitation>"
comments:
  inspected: false
  useful_points: []
  disagreement: []
  unresolved_questions: []
follow_up_checks:
  - "<authoritative or current verification needed>"
```

## Evidence-to-decision record (copy per planning choice)

```yaml
decision_id: "<local ID>"
candidate: "<attraction, route leg, lodging area, meal, or service>"
party_fit: "must | recommended | optional | skip"
reason: "<tie the choice to actual party constraints>"
supporting_evidence_ids: ["<evidence ID>"]
contrary_or_qualifying_evidence_ids: []
source_ids: ["<source ID>"]
confidence: "high | medium | low"
unresolved_checks:
  - "<opening, ticket, schedule, access, price, or other current detail>"
backup: "<weather, closure, fatigue, or access alternative>"
```

## Evidence card (copy per claim)

```json
{
  "id": "<evidence ID>",
  "topic": "<topic>",
  "subject": "<specific subject>",
  "claim": "<one narrow claim>",
  "kind": "observed",
  "confidence": "low",
  "freshness": "unknown",
  "checked_at": "YYYY-MM-DD",
  "source_ids": ["<source ID>"],
  "caveat": "<scope and limitations>"
}
```

## Disagreement log

| Topic/claim | Supporting source(s) | Contrary source(s) | Differences in date/context | Planning treatment | Remaining check |
| --- | --- | --- | --- | --- | --- |
| `<claim>` | `<IDs>` | `<IDs>` | `<season, route, party, promotion, etc.>` | `<keep both / lower confidence / flexible plan>` | `<verification>` |

Do not raise confidence merely because sources repeat the same unsourced claim. Search coverage, note inspection, comments, official checks, and itinerary decisions should remain distinguishable.
