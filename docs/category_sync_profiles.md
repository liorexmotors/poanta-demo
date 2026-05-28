# Pointa category sync profiles

MVP for running different sync/editor cadences by content urgency.

## Profiles

- `fast` — every ~10 minutes: ביטחון, פוליטיקה, חדשות, פלילים, משפט
- `medium` — every ~10 minutes: כלכלה, צרכנות, רכב, ספורט, אקטואליה בעולם, דעות
- `slow` — every ~10 minutes: טכנולוגיה, בריאות, תרבות, רכילות, נדל״ן, מזג אוויר

The source of truth is `pointa_sync_profiles.json`.

## Script support

RSS/update scan:

```bash
python3 scripts/update_feed.py --sync-profile fast
python3 scripts/update_feed.py --sync-profile medium
python3 scripts/update_feed.py --sync-profile slow
```

Editor prepare:

```bash
python3 scripts/pointa_editor_pipeline.py prepare --sync-profile fast --limit 18 --batch-size 6 --max-per-category 6
python3 scripts/pointa_editor_pipeline.py prepare --sync-profile medium --limit 18 --batch-size 6 --max-per-category 6
python3 scripts/pointa_editor_pipeline.py prepare --sync-profile slow --limit 16 --batch-size 8 --max-per-category 5
```

NPM aliases:

```bash
npm run sync:fast
npm run sync:medium
npm run sync:slow
npm run editor:prepare:fast
npm run editor:prepare:medium
npm run editor:prepare:slow
```

## Important

This config aligns the dashboard freshness SLA with feed sync profiles. As of 2026-05-28 all profiles are configured for a ~10-minute collection/check cadence at Lior's request; publication is still gated by editorial QA and live health checks. If the live scheduler does not read `intervalMinutes` directly, update the scheduler separately under the same rollback rules before changing production cadence.
