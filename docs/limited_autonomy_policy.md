# Poanta Feed-Publication Autonomy Policy

Approved by Lior for one narrow domain only: **uploading, publishing, repairing, and quality control of Poanta feed articles/cards**.

This policy does not apply to product/UI features, app/backend architecture, new skills, installs/downloads, external accounts, paid services, security-sensitive actions, or broad content-policy changes.

## Decision

Poanta may manage feed article freshness and publication autonomously under hard gates. The system must not transfer feed-publication decisions back to Lior when a safe recommendation exists.

## Allowed without asking Lior

The auditor/repair path may run quietly when the feed is weak, stale, or an important source view is stale:

1. Run FAST sync/refresh.
2. Run source rescue queues and full-article editor/rescue batches.
3. Run deterministic Quality Gate.
4. Run live/quality/timing auditors and build/smoke checks.
5. Deploy a feed-only freshness/card repair **only if all hard gates pass**.
6. Add deterministic guards/prompts/tests that prevent the same feed-publication failure from recurring.
7. Log handled issues quietly and report outcomes, not decision requests.

## Hard gates for publication

- Quality Gate has 0 errors.
- Live auditor is OK, or only agreed warnings remain.
- No uncertain editorial/source-policy judgment.
- No lowered editorial standards.
- No freshness-threshold weakening.
- No QA bypass.

## If hard gates fail

Do not publish. Continue deterministic rescue/repair internally where possible, or log/report the outcome. Do **not** send Lior decision/options messages for feed-card publication/quality.

## Ask Lior only outside this scope

Ask/confirm for product/UI/content-policy changes, app/backend architecture, new skills, installs/downloads, external accounts, paid services, security-sensitive actions, or anything outside feed article publication/quality.

## Non-negotiable gates

- Freshness never bypasses editorial quality.
- No feed publish with Quality Gate errors.
- No weak/generic/uncertain rescue card goes live.
- If in doubt, do not publish; keep repairing or log the outcome.
