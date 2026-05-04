# Poanta Feed Automation

Runs every two hours via GitHub Actions.

What it does:
- scans approved sources
- scores homepage/RSS items by signal, public prominence, and clickbait-style wording
- selects up to two items per source
- rewrites into Poanta card structure in `feed.json`
- commits the updated feed back to the repo

Current caveats:
- public views/comments are not consistently exposed by the source sites, so v1 uses prominence + headline signal as proxy
- Channel 14 currently returns 403/WAF to automated fetches, so the script logs a warning and continues
- push notifications still require a backend subscription store + VAPID push sender

Safety direction:
- v1 publishes automatically to the demo feed
- recommended production mode: generate candidates first, then approve before publishing
