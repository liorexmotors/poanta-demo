# משה cron — Stage 4 politics no publishable cards — 2026-06-04 01:24

## Status
- Public main feed health gate: OK.
- Public live auditor: OK, only non-blocking warning.
- Timing auditor: FAIL on domain SLA, including `פוליטיקה`.
- Autopilot prepared Stage 4 domain rescue for `פוליטיקה` at `tmp/editor-runs/domain-פוליטיקה-20260604-022327`.
- Deploy: no.

## Run details
- Queue: `tmp/pointa_source_rescue_queue_פוליטיקה.json`
- Run dir: `tmp/editor-runs/domain-פוליטיקה-20260604-022327`
- Prepared items: 1
- Editor QA: pass=0, reject=1, qaFailures=0
- Autopilot after results: `status=blocked`, `incidentType=stage4_no_publishable_editor_cards`, `automaticAction=do_not_publish`.

## Editorial decision
The only usable candidate was Israel Hayom article:
`"אוכלת תינוקות": יהודייה הותקפה ברכבת התחתית בניו יורק`

Article facts describe an antisemitic physical assault / hate-crime incident in the New York subway. It is not a clean `פוליטיקה` domain rescue card, and publishing it as politics would force the category to close the SLA. The row was rejected as `off_domain_for_politics`.

## Outcome
No feed mutation and no deployment. The public feed remains OK, but the domain/timing SLA remains blocked and requires a fresh, lawful, on-domain politics card or improved source selection.
