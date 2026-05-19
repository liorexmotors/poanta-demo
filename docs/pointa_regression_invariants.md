# Pointa Regression Invariants

These are production rules created from user-reported regressions. A fix is not complete unless the rule is preserved in code, QA, documentation, or the editor contract.

## Local accident / traffic cards

- A traffic accident, vehicle strike, bicycle/e-bike injury, road or street crash is not `פוליטיקה` unless the actual story is about policy/government.
- Prefer `רכב` for practical road/vehicle incidents.
- If the source contains a concrete city/street that changes understanding, preserve it in the Pointa headline or context.
- Example invariant: `רוכב אופניים חשמליים בן 10 נפצע בתאונה בעכו` must become a compact event headline that includes `עכו` and must not be categorized as politics.

## Domestic violence / murder warning cards

- Do not leave source-teaser phrasing as the Pointa headline when the article contains a concrete violent event.
- Preserve the sequence that changes the meaning: warning/fear before the violence, relationship to suspect, location/context, and alleged acts.
- The takeaway must name the article-specific bottom line, not a generic phrase.
- Example invariant: Marlin Al-Turi card should foreground that she feared her husband before being run over, stabbed, and burned; the takeaway should connect the warning to a failure around domestic-violence alert signals.

## Generic takeaways are regressions

- Reusable lines such as `הוא הפרט שקובע מה באמת השתנה` are unacceptable when a specific article-level conclusion exists.
- If a generic fallback appears in a user-visible bad card, add a deterministic rewrite or QA guard for that class before release.

## QA hard block for known generic fallback

- `הפרט שקובע מה באמת השתנה` is a known-bad fallback, not a valid insight.
- Quality Gate must fail/quarantine cards that still contain this phrase after rewrite attempts.
- If this lowers volume, prefer lower volume over shipping weak cards.
