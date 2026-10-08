# Trip Profile

Collect only details that can change the itinerary. Ask a few high-impact questions at a time; do not present the whole schema as a questionnaire.

## High-impact questions

1. Destination/route, origin, dates or season, and number of days.
2. Who is traveling? Ask ages only where relevant to pace, tickets, child routines, or accessibility.
3. Approximate budget and whether it includes intercity transport.
4. Preferred pace, interests, must-see places, and things to avoid.
5. Mobility, dietary restrictions/allergies, and transport preference if relevant.

If the user wants to proceed without answering optional questions, state assumptions in the guide and keep them easy to revise. Never infer medical status or exact ages.

## Profile shape

```json
{
  "trip": {
    "destination": "西藏",
    "destinations": ["拉萨", "林芝"],
    "origin": "未提供",
    "start_date": "2026-09-23",
    "duration_days": 7,
    "occasion": "未提供",
    "intercity_transport": "拉萨往返",
    "local_transport": ["包车", "公共交通"]
  },
  "party": {
    "total": 3,
    "members": [
      {"role": "adult", "age": null, "notes": ""},
      {"role": "adult", "age": null, "notes": ""},
      {"role": "older_adult", "age": 65, "notes": "年龄约数；体力与健康状况未确认"}
    ],
    "mobility": "unknown",
    "needs": []
  },
  "budget": {
    "per_person": null,
    "includes_intercity_transport": false,
    "tier": "balanced",
    "sensitivity": "unknown"
  },
  "preferences": {
    "pace": "balanced",
    "interests": [],
    "must_see": [],
    "avoid": [],
    "dietary": [],
    "accommodation": "unknown"
  },
  "assumptions": ["出发日期尚未确认", "同行者健康情况尚未确认"]
}
```

Allowed planning values:

- `mobility`: `able`, `mixed`, `limited`, `unknown`.
- `tier`: `economy`, `balanced`, `comfort`, `premium`, `unknown`.
- `pace`: `relaxed`, `balanced`, `intensive`.

For older adults or users with limited mobility, reduce walking/transfer load, schedule recovery time, identify stairs and altitude exposure as questions to verify, and offer lower-effort alternatives. This is itinerary accommodation, not medical advice.

## Persistence and privacy

Save the profile under the user's per-trip output directory, not in the installed skill. Include only information necessary to plan the trip. Do not commit, upload, or share it without explicit user approval.
