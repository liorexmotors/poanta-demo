# Poanta Feed Freshness Control

Goal: the public app must *feel live*. A cron status of `ok` is not health. The only health signal is the public `feed.json` outcome.

## SLA

- Warning: no new top item for 15 minutes during active hours.
- Incident: no new top item for 25–30 minutes, stale `updatedAt`, or too few recent top items/sources.
- Recovery target: publish a clean feed candidate immediately when hard gates pass; otherwise prepare editor rescue and escalate automatically.

## New control layers

1. **Outcome auditor** — `pointa_live_auditor.py` checks the live GitHub Pages feed, not local files and not cron status.
2. **Deterministic repair** — `pointa_silent_freshness_sentinel.py --repair` tries FAST sync/deploy only under Quality Gate + Publication Health Gate.
3. **Independent SLA guard** — `pointa_freshness_sla_guard.py` runs outside the normal OpenClaw cron fan-out. If live is stale:
   - runs the silent repair path;
   - if FAST is insufficient, prepares a full-article rescue batch;
   - escalates once per incident to an agent run with the exact rescue directory;
   - rate-limits duplicate escalations to avoid noisy loops.
4. **Hard publication gates** — no deploy is considered successful unless:
   - Pointa Quality Gate has 0 errors;
   - Publication Health Gate is OK;
   - live auditor returns OK after cache propagation.

## Why this was needed

The previous setup had many OpenClaw cron jobs marked `running/error` with `next` times in the past. That means the scheduler/agent layer itself can become the single point of failure. The new SLA guard is intentionally small, deterministic, locked, and externally scheduled so it can wake the editor path even when the normal feed automation is wedged.

## Operational rule

If the guard sees a stale feed and deterministic repair cannot satisfy freshness, it must not publish weak cards. It must prepare rescue input and escalate editorial repair automatically. Freshness and quality are both required.
