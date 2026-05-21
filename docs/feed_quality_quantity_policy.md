# Poanta Quality + Quantity Policy

Approved direction: Poanta must optimize for **both** quality and volume. These are separate obligations.

## Principle

- **Quality is the gate.** No item may be published if it fails the editorial/QA bar.
- **Quantity is an SLA.** A small clean feed is not success if the viewer experience feels stale or thin.

## Non-negotiable quality gate

Never publish:

- Quality Gate errors.
- Generic/reusable takeaways.
- Copied source headlines.
- Source/reporter-mediated summaries.
- Foreign-source items without Israel/Middle East/Jews/antisemitism/regional-security relevance.
- Rescue cards with editorial uncertainty.

## Quantity / freshness obligation

If the feed is technically valid but weak, stale, or thin, that is a production issue.

Do not confuse automation activity with health. A cron run marked `ok` and a fresh
`updatedAt` timestamp are only implementation signals. The product signal is the
user-visible result: a fresh top item, enough fresh top-card volume, enough recent
source diversity, and live/raw/cache agreement.

The auditor must track separately:

1. Overall feed top freshness.
2. Number of fresh items added in the recent window.
3. Freshness by important source view.
4. Rescue queue size and age.
5. Whether fresh candidates are being rejected before editor review.
6. Whether source-view stale warnings are being routed into rescue prioritization.

## Repair ladder when quantity is low but quality is protected

1. Run FAST sync.
2. Preserve recent approved rescue cards.
3. Build source rescue queue from important sources.
4. Prepare full-article editor rescue batches.
5. Expand to additional approved sources/profiles if still thin.
6. Publish only QG=0 feed-only updates.
7. If FAST sync produces only a partial technical refresh, continue immediately to full rescue/editor/QA rather than stopping.
8. If hard gates still cannot be met, do not publish weak cards and do not ask Lior to decide inside feed-card scope; keep deterministic repair internal and report only true blockers/outcomes.

## What not to do

- Do not lower QA thresholds just to increase count.
- Do not recycle old articles as “new”.
- Do not fill the feed with evergreen/lifestyle noise in FAST.
- Do not hide stale-source failures by weakening the auditor.
- Do not treat source-view stale warnings as noise. They may be non-blocking warnings, but they are rescue-prioritization signals.

## Target state

A healthy feed is:

- Fresh at the top.
- Broad enough to feel alive.
- Strict enough that every visible card is trustworthy.

## Source-view freshness decision

Lior selected Option 2 for stale source views:

- Do not weaken source-view freshness thresholds just to reduce failures.
- A stale important/foreign source view warning must trigger source-targeted rescue preparation/prioritization, even when it is not a blocking error.
- Source-targeted rescue must still obey all quality/relevance gates.
- If the rescue queue has no usable candidates for the stale source, or the editor cannot produce QG=0 cards after one safe attempt, keep repairing deterministically or report the blocker/outcome; do not lower standards and do not transfer feed-card decisions back to Lior.
