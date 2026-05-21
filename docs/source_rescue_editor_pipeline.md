# Pointa source rescue editor pipeline

`pointa_source_rescue_queue.py` remains a shadow/report-only detector for fresh important-source items that failed deterministic QA.

When that report contains `recommendedAction: send_to_full_editor_rescue_queue`, prepare a local full-editor batch with:

```bash
python scripts/pointa_rescue_editor_pipeline.py prepare --limit 24 --batch-size 8
```

The script writes `tmp/editor-runs/<run-id>/` with `run.json`, `editor_input.json`, `batch_*.json`, and `EDITOR_PROMPT.md`.

## 2026-05-21 stuck-rescue rule

The rescue editor must not get stuck on the first RSS rows when they are thin,
premium-blocked, duplicated, or stale-source-only candidates.

Default prepare behavior is now adaptive:

1. Read the ordered rescue queue.
2. Oversample candidates before the editor run (`--oversample-factor`, default 3).
3. Extract article text for the oversampled rows.
4. Select usable article-text rows first while preserving queue order.
5. Use thin rows only as fallback if there are not enough usable rows.

This keeps the feed rescue lane moving: top-feed freshness incidents get fresh
usable candidates first, while stale-source warnings still remain visible and
actionable. Quality is unchanged: thin/uncertain cards must still be rejected by
the editor/QA and must never be published just to satisfy freshness.

Safety notes:

- `run.json` is marked `source: "rescue"` and `mode: "local-prepare-only"`.
- Full article text is extracted through `pointa_editor_pipeline.extract_article`.
- `run.json.selection` records how many rows were considered, how many had usable
  text, and how many thin fallback rows were selected.
- The script does not modify `feed.json`, `dist/`, or any live feed artifact.
- It does not publish, deploy, finalize, or send messages.
