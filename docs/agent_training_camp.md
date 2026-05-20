# Poanta Agent Training Camp / מחנה אימונים לסוכנים

Purpose: teach each Poanta agent through adversarial synthetic drills before it is trusted to affect the live feed.

Approved by Lior: each active agent must train on at least **25 hard cases** and reach **100/100** before its responsibility is considered trusted.

## Agents covered

1. **האספן / collector** — source collection, freshness, dedupe, rescue routing.
2. **העורך / editor** — full-article rewrite, headline/summary/takeaway quality.
3. **השוער / gatekeeper** — QA, finalizer, build/deploy gates.
4. **המבקר / auditor** — live-feed freshness and product failures.
5. **המתקן / repairer** — safe repair, rollback, escalation, re-audit.

## Training files

Run:

```bash
python3 scripts/poanta_agent_training.py --fail-under-100
```

Outputs:

- `tmp/agent-training/poanta_agent_training_cases.json`
- `tmp/agent-training/poanta_agent_training_gold_answers.json`
- `tmp/agent-training/poanta_agent_training_report.json`

## Rules

- Minimum: 25 cases per agent.
- Required score: 100/100.
- A case is intentionally adversarial: it should try to trick the agent into doing the wrong thing.
- Any missed case becomes one of:
  - stronger QA rule,
  - new regression test,
  - prompt/skill rule,
  - source policy,
  - automation guard.

## Current training categories

- Copied source headlines.
- Generic takeaways.
- Source/reporter mediation in summaries.
- Fresh but weak cards.
- Foreign irrelevant world news.
- Important source stale views.
- Rescue queue routing.
- Duplicate stories.
- Manual correction overwrite.
- Build/deploy/QA failure handling.
- Option 2 limited autonomy: one safe repair attempt, then ask Lior.

## Enforcement principle

No “almost passed.” If score is below 100, the responsible agent is not trusted for that responsibility until the failure is converted into a deterministic guard or training rule.
