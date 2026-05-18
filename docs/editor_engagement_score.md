# Pointa Editor Engagement Score

## Goal

Pointa should satisfy the user inside the feed. Opening the original article is not automatically success; it can be a signal that the card did not provide enough information.

The score must be relative, not nominal. A card is bad when users behave differently from comparable cards.

## Core concept

Use a relative metric: `editorReviewScore`.

A card needs editor review when it is an outlier versus its peer group.

Peer group should be chosen in this order:

1. Same category + same source + similar age bucket.
2. Same category + similar age bucket.
3. Whole feed in same age bucket, only if sample is too small.

Age buckets:

- 0–2h
- 2–6h
- 6–24h
- 1–3d
- 3d+

## Events to track

Per card:

- `impression`: card became visible enough to count.
- `source_open`: user opened original article.
- `save`: user saved the card.
- `mark_read`: card was read/marked read without source open.
- `card_dwell_ms`: time card was in focus/visible.
- `quick_return`: user opened source and returned quickly.
- `expand_or_more`: if future UI has expansion.

## Derived rates

For each card after minimum impressions:

- `openRate = source_open / impressions`
- `quickReturnRate = quick_return / source_open`
- `saveRate = save / impressions`
- `readWithoutOpenRate = mark_read_without_source_open / impressions`
- `medianDwellMs`

## Relative comparisons

For each metric, compute peer baseline:

- peer median
- peer interquartile range (IQR)
- peer percentile

Prefer robust statistics over averages because news behavior has spikes.

## Badness signals

A card is suspicious when:

### 1. Relative Open Gap

`openRate` is high relative to peers.

Example:

- card openRate is above peer P80/P90, or
- robust z-score > 1.5 versus peer median/IQR.

Interpretation: users needed the source more than usual for similar cards.

### 2. Quick Return Gap

`quickReturnRate` is high relative to peers.

Interpretation: users opened the source looking for a missing detail, found/failed quickly, and returned. This often means the card missed a practical detail like date, location, amount, name, consequence, or explanation.

### 3. Low Satisfied Read

`readWithoutOpenRate` is low relative to peers, especially with high openRate.

Interpretation: the card did not close the story inside the feed.

### 4. Low Save / High Open mismatch

High openRate but low saveRate relative to peers.

Interpretation: curiosity/click gap, not value.

### 5. Short Dwell + High Open

Low dwell time on card + high source open.

Interpretation: user immediately felt the card lacked enough information.

## Proposed score

`editorReviewScore` should be 0–100 but computed from relative ranks.

Initial formula:

```text
openGap = percentile(openRate within peer group)
quickReturnGap = percentile(quickReturnRate within peer group)
unsatisfiedReadGap = 100 - percentile(readWithoutOpenRate within peer group)
saveWeakness = 100 - percentile(saveRate within peer group)
dwellWeakness = 100 - percentile(medianDwellMs within peer group)

editorReviewScore =
  0.40 * openGap +
  0.25 * quickReturnGap +
  0.20 * unsatisfiedReadGap +
  0.10 * saveWeakness +
  0.05 * dwellWeakness
```

This is not final; weights should be tuned after real usage.

## Minimum sample rules

Do not judge too early.

Suggested thresholds:

- Minimum 30 impressions before card-level scoring.
- Minimum 10 source opens before trusting quickReturnRate.
- Minimum 8 peer cards in peer group; otherwise broaden peer group.

## Review thresholds

- `0–60`: normal.
- `60–75`: watchlist.
- `75–85`: editor review candidate.
- `85+`: urgent editor review.

But thresholds should be calibrated by percentile distribution, not fixed forever.

A better production rule:

- Top 10% `editorReviewScore` per day → review queue.
- Top 3% → urgent review.

## What the editor receives

When a card is flagged, send to “העורך”:

```json
{
  "reason": "high_open_gap",
  "peerGroup": "category=בריאות, age=2-6h",
  "metrics": {
    "impressions": 240,
    "openRate": 0.38,
    "peerOpenRateMedian": 0.14,
    "openRatePercentile": 92,
    "quickReturnRate": 0.61,
    "quickReturnPercentile": 88,
    "readWithoutOpenRate": 0.21,
    "peerReadWithoutOpenMedian": 0.54
  },
  "hypothesis": [
    "missing_date_or_time",
    "missing_amount",
    "headline_too_teasing",
    "summary_did_not_answer_why_it_matters",
    "takeaway_too_generic"
  ],
  "card": { ... },
  "sourceArticleText": "..."
}
```

## Editor task on flagged card

The editor should answer:

1. What was probably missing?
2. Was the source-open behavior justified because the article was inherently high-interest, or because the card was incomplete?
3. Rewrite card if needed.
4. If the card was actually good and opens are natural for the topic, mark `no_editor_change` with reason.

## Important distinction

High source opens can mean two things:

1. **Good curiosity**: major breaking story, exclusive, photos/video, primary document.
2. **Bad incompleteness**: missing date, price, location, consequence, names, numbers, why-it-matters.

Therefore the score only triggers review; it does not automatically declare failure.

The editor makes the final judgment.

## Product principle

Pointa optimizes for understanding inside the feed, not outbound click-through.

A successful card should produce:

- enough dwell/read time,
- high read-without-open,
- reasonable saves,
- lower-than-peer source-open need,
- and fewer quick returns.
