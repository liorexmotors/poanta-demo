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
5. Use adaptive rescue preparation: oversample the queue, extract article text first, and send usable article-text candidates to the editor before thin/premium/stale fallback rows.
6. Expand to additional approved sources/profiles if still thin.
7. Publish only QG=0 feed-only updates.
8. If FAST sync produces only a partial technical refresh, continue immediately to full rescue/editor/QA rather than stopping.
9. If hard gates still cannot be met, do not publish weak cards and do not ask Lior to decide inside feed-card scope; keep deterministic repair internal and report only true blockers/outcomes.

## What not to do

- Do not lower QA thresholds just to increase count.
- Do not recycle old articles as “new”.
- Do not fill the feed with evergreen/lifestyle noise in FAST.
- Do not hide stale-source failures by weakening the auditor.
- Do not treat source-view stale warnings as noise. They may be non-blocking warnings, but they are rescue-prioritization signals.
- Do not let source-view rescue consume the whole first editor run with thin or blocked articles while fresher usable cards are waiting lower in the queue.

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

## Opinion column attribution invariant — 2026-05-21
- Opinion-source cards, especially `מעריב - דעות`, must use the columnist's name when available.
- Cards must not say “הטור...”, “הכותבת טוענת...”, “הכותב טוען...”, or similar generic source mediation.
- Quality Gate blocks Maariv opinion cards when the author is identifiable but not visible in the card text.
- A user 👎 on this pattern is treated as `category/editorial attribution mismatch` and must become a repair/training case, not only passive feedback.

## Semantic duplicate invariant — 2026-05-21
- The feed must not show two cards for the same event merely because two publishers used different wording.
- Duplicate logic must consider semantic anchors: event, timing, affected place/group, named actors, and topic-specific signals.
- Example regression fixed: Walla and Maariv both published the same Shavuot rain/wind forecast; only one card should remain.
- המבקר owns live duplicate detection; האספן/update pipeline owns pre-publish dedupe; השוער must treat duplicate clusters as publish-quality warnings requiring repair.
