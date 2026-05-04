# Poanta Feed Automation

Approval mode: OpenClaw cron drafts candidates every two hours and sends them to Telegram for approval. GitHub Actions publishing is manual-only for now.
Approval cron schedule: every two hours during daytime only, 07:00-21:00 Asia/Jerusalem (`0 7-22/2 * * *`), with no scans or Telegram updates between 23:00 and 07:00.

What it does:
- scans approved sources
- scores homepage/RSS items by signal, public prominence, and clickbait-style wording
- selects up to two items per source
- rewrites into Poanta card structure in `candidates.json` for approval
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
