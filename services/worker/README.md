# Worker Service — Production Skeleton

Working name only. The public app name is not final.

Current worker is a smoke check against legacy `feed.json`.
Next jobs:
- collector / האספן
- editor / העורך
- quality gate / השוער
- live auditor / המבקר
- repair queue / המתקן

Feedback markings:
- `python3 scripts/pointa_feedback_report.py --format text --only-actionable`
- Reads `feedback_events` from Postgres and reports only marked cards that need attention.
- Routed to מבקר איכות / העורך / השוער as report-only signals first.
