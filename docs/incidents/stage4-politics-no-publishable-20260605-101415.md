# Stage 4 politics rescue blocked — no publishable cards

- checkedAt: 2026-06-05T10:15+03:00
- domain: פוליטיקה
- runDir: `tmp/editor-runs/domain-פוליטיקה-20260605-101415`
- queue: `tmp/pointa_source_rescue_queue_פוליטיקה.json`
- prepared items: 1 usable article from הארץ
- editor result: 0 pass / 1 reject / QA failures 0
- deploy: no

## Reason
The only selected article was about FIFA/World Cup bottle policy, sponsor/commercial considerations and stadium safety. After reading the extracted article it is sports/consumer/event operations, not politics. It was rejected as `off_domain_sports_event_operations`.

## Gate decision
Do not force an off-domain card into `פוליטיקה` and do not publish same/weak cards to satisfy timing SLA. Public main feed gate was OK at the time, but timing/domain SLA remains blocked and requires fresher genuinely political candidates.
