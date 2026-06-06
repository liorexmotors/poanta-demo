# Stage 4 פוליטיקה blocked — off-domain selection

- checkedAt: 2026-06-06T11:24:35+03:00
- runDir: `tmp/editor-runs/domain-פוליטיקה-20260606-112435`
- deploy: no
- feed mutation: no

## What happened
Autopilot prepared a Stage 4 `פוליטיקה` domain rescue run with 1 selected usable row from `הארץ`.

The selected row was off-domain after extraction:
- `הארץ - כל הכתבות`
- `המועמד לנשיאות ריאל מדריד: "אם אנצח, אעשה הכל כדי שיורגן קלופ יהיה המאמן"`
- `https://www.haaretz.co.il/sport/world-soccer/2026-06-06/ty-article/0000019e-9beb-d0a9-a7df-bbfb362b0000`

This is a sports/football governance item, not `פוליטיקה` for Poanta timing SLA.

## Decision
No editor result files were written. Do not apply or deploy this Stage 4 run.

## Blocker
`domain_rescue_off_domain_selection_false_ok`: the prepared batch was structurally valid but the selected article facts do not match the breached domain.

## Required follow-up
Strengthen Stage 4 politics source selection/validation so sports rows from broad feeds are filtered after article extraction before editor batching.
