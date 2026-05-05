# Poanta Feed Automation

Approval mode: OpenClaw cron drafts candidates every two hours and sends them to Telegram for approval. GitHub Actions publishing is manual-only for now.
Approval cron schedule: every two hours during daytime only, 07:00-21:00 Asia/Jerusalem (`0 7-22/2 * * *`), with no scans or Telegram updates between 23:00 and 07:00.

What it does:
- scans approved sources
- scores homepage/RSS items by signal, public prominence, and clickbait-style wording
- selects up to two items per source
- skips URLs, canonical article IDs, source-title keys, and headline keys that already appeared in previous approval batches or published feeds, using `.poanta-seen.json`
- if the main/homepage sources repeat themselves, expand search into additional sections such as רכב, פוליטיקה, ספורט, תחבורה and צרכנות rather than recycling old items
- rewrites into Poanta card structure in `candidates.json` for approval
- keeps `originalTitle` as the source site headline; the card footer link displays this original headline instead of generic “לכתבה המקורית”
- `originalTitle` must be an exact source quote for the footer link: do not rewrite, shorten, add words, remove words, or use the Poanta headline there
- publishes to `feed.json` only after approval

Current caveats:
- public views/comments are not consistently exposed by the source sites, so v1 uses prominence + headline signal as proxy
- Channel 14 currently returns 403/WAF to automated fetches, so the script logs a warning and continues
- push notifications still require a backend subscription store + VAPID push sender

Safety direction:
- v1 is approval-first: generate candidates, send Telegram summary, publish only approved items

## Editorial Agent Spec

The Poanta editor-agent rules live in:
- `agents/poanta-editor-agent.md` — full Hebrew operating manual
- `agents/poanta-editor-agent-prompt.md` — compact prompt for automation/subagents

The approval automation should read/follow this spec before sending candidates for approval.

Important cron behavior: after `python3 scripts/update_feed.py --draft`, do not re-filter candidates against `.poanta-seen.json`; the script already used the pre-run seen history and then marks this approval batch as sent. Use `candidates.json` as the source of truth and do not invent older candidates.


Approval Telegram format now includes `תמצית` and `כותרת מקור` per ליאור’s 2026-05-05 instruction:
- `כותרת פואנטה`: new, short, decisive, not copied, not a question, answers the point.
- `תמצית`: exactly two sentences — first what happened, second why it matters.
- `תובנה עבורך`: one practical sentence; if no direct impact, say so.
- `כותרת מקור`: exact source title word-for-word for comparison/footer link.

- אין להציג שם מקור/לוגו/באדג׳ על גבי תמונת הכרטיס עצמה; התמונה חייבת להישאר נקייה. המקור יכול להופיע רק במטה/באדג׳ שמחוץ לתמונה.

Anti-repeat hard rule added 2026-05-05 after cron repeated an already approved/sent batch:
- `scripts/update_feed.py --draft` must clear `candidates.json` at the start of a draft run.
- If a fresh draft fails or finds fewer than 4 unseen items, `candidates.json` must contain `status: failed_too_few_fresh_items` and `items: []`.
- Cron agents must never send old `candidates.json` or `feed.json` as fallback. Only send when `candidates.json.status == "draft"` from the current successful run.
- Repeating a previously sent/published URL, canonical article id, original title, Poanta headline, or same topic is forbidden even if the source still promotes it.
