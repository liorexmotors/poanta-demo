# Stage 4 politics domain rescue blocked — no publishable editor cards

- Checked: 2026-06-05 17:03 Asia/Jerusalem
- Run dir: `tmp/editor-runs/domain-פוליטיקה-20260605-170135`
- Domain: `פוליטיקה`
- Autopilot incident: `stage4_no_publishable_editor_cards`
- Public main feed: OK after Stage 3 rescue; top item `ישראל הפעילה יחידות קומנדו באזרבייג׳ן בזמן המלחמה באיראן`, publishedAt `2026-06-05T16:42:28+03:00`.
- Prepared candidates: 1
- Editor QA: pass 0, reject 1, qaFailures 0
- Rejected candidate: Reuters / Google News bridge row `Israel plans first embassy in Slovenia, says foreign minister - Reuters`
- Reject reason: bridge row had no usable `articleText` (`articleTextChars: 0`) and only generic Google News description; publishing would be title-only/thin and would bypass Pointa editorial standards.
- Deploy: no additional Stage 4 deploy. `feed.json` unchanged by this Stage 4 lane.
- Loop protection: active, repeatCount 3 (`same_incident_repeated`).

Conclusion: public top-feed freshness was repaired separately, but politics/domain timing SLA remains blocked by lack of fresh publishable in-domain article text. Do not rerun the same Reuters bridge batch blindly; improve source acquisition/extraction or select a usable on-domain source before retrying.
