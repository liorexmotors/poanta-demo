# Poanta Limited Autonomy Policy

Approved by Lior: start with **Option 2 — limited autonomy with hard gates**.

## Decision

Poanta may repair feed freshness automatically, but only inside strict quality and safety limits.

## Allowed without asking Lior

The auditor/repair path may run quietly when the feed is weak, stale, or an important source view is stale:

1. Run FAST sync/refresh.
2. Run deterministic Quality Gate.
3. Run build/smoke checks.
4. Deploy a feed-only freshness repair **only if Quality Gate has 0 errors**.
5. Prepare rescue editor batches for fresh important-source candidates rejected by deterministic QA.
6. Log handled issues quietly.

## Must stop and ask Lior

The system must not publish and must escalate with a concise decision request when any of these happens:

- Quality Gate has any error.
- The repair requires editorial judgment rather than deterministic correction.
- The rescue batch is prepared but needs human/editor pass before applying.
- Source identity, story relevance, or foreign-source relevance is uncertain.
- The same freshness failure remains after one safe repair attempt.
- Git/auth/automation/secrets/source access blocks repair.
- A subordinate agent repeats a previously fixed failure class.

## Alert format

When escalation is required, do not send raw errors. Send:

1. The blocker.
2. Two options maximum.
3. Recommended choice.

## Non-negotiable gates

- Freshness never bypasses editorial quality.
- No feed publish with Quality Gate errors.
- No weak/generic/uncertain rescue card goes live.
- If in doubt, prepare locally and ask.
