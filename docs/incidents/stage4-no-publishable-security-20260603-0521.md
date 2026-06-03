# Stage 4 ביטחון — no publishable editor cards

- checkedAt: 2026-06-03T05:21:00+03:00
- runDir: `tmp/editor-runs/domain-ביטחון-20260603-052024`
- status: blocked
- incidentType: `stage4_no_publishable_editor_cards`
- deploy: no

## What happened
Stage 4 prepared a security-domain rescue batch after the public main feed had already been repaired and verified OK.
The prepared run validated structurally as on-domain: 8/8 on-domain, 0 off-domain.

## Editor result
- itemsPrepared: 8
- pass: 0
- reject: 8
- qaFailures: 0

All candidates were rejected because they were either:
- same US/Iran/Hormuz/Bahrain/Kuwait/tanker semantic cluster already visible in the public feed after the duplicate hotfix;
- older/non-fresh Hormuz background that would not improve the breached security-domain SLA;
- Google News bridge row with no usable article text.

## Decision
No feed mutation and no deploy. Publishing any of these rows would either reintroduce the duplicate regression or publish a weak/non-fresh card just to satisfy timing telemetry.

## Public state at block time
Public health gate: OK. Live auditor: OK. Remaining issue is Stage 4/domain SLA debt, not public main-feed failure.
