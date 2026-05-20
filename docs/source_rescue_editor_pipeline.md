# Pointa source rescue editor pipeline

`pointa_source_rescue_queue.py` remains a shadow/report-only detector for fresh important-source items that failed deterministic QA.

When that report contains `recommendedAction: send_to_full_editor_rescue_queue`, prepare a local full-editor batch with:

```bash
python scripts/pointa_rescue_editor_pipeline.py prepare --limit 24 --batch-size 8
```

The script writes `tmp/editor-runs/<run-id>/` with `run.json`, `editor_input.json`, `batch_*.json`, and `EDITOR_PROMPT.md`.

Safety notes:

- `run.json` is marked `source: "rescue"` and `mode: "local-prepare-only"`.
- Full article text is extracted through `pointa_editor_pipeline.extract_article`.
- The script does not modify `feed.json`, `dist/`, or any live feed artifact.
- It does not publish, deploy, finalize, or send messages.
