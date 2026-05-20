#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare local Pointa editor batches from the source rescue queue.

Safe-by-default: this script only writes a local run directory under
``tmp/editor-runs/<run-id>``. It does not modify feed.json, publish, deploy, or
apply editor results.

Usage:
  python scripts/pointa_rescue_editor_pipeline.py prepare --limit 24 --batch-size 8
  python scripts/pointa_rescue_editor_pipeline.py prepare \
    --queue tmp/pointa_source_rescue_queue.json --run-id rescue-smoke --limit 2
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pointa_editor_pipeline as editor_pipeline  # type: ignore
import update_feed  # type: ignore

DEFAULT_QUEUE = ROOT / "tmp" / "pointa_source_rescue_queue.json"
RUNS_DIR = ROOT / "tmp" / "editor-runs"


def load_queue(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError(f"{path} must contain an object with an items array")
    return data


def select_rescue_items(queue: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for row in queue.get("items", []):
        if row.get("recommendedAction") != "send_to_full_editor_rescue_queue":
            continue
        url = row.get("sourceUrl") or ""
        if not url or url in seen_urls:
            continue
        selected.append(row)
        seen_urls.add(url)
        if len(selected) >= limit:
            break
    return selected


def row_to_editor_item(index: int, row: dict[str, Any], min_article_chars: int) -> dict[str, Any]:
    url = row.get("sourceUrl") or ""
    extraction = editor_pipeline.extract_article(url)
    original_title = row.get("originalTitle") or extraction.title or ""
    description = extraction.description or row.get("deterministicContext") or ""
    category, category_class = update_feed.categorize_item(
        original_title,
        description or extraction.text[:700],
        row.get("source", ""),
    )
    current_category, current_class = update_feed.categorize_item(
        row.get("deterministicHeadline") or original_title,
        row.get("deterministicContext") or description,
        row.get("source", ""),
    )
    return {
        "index": index,
        "source": row.get("source", ""),
        "sourceGroup": row.get("sourceGroup", ""),
        "sourceUrl": url,
        "originalTitle": original_title,
        "description": description,
        "articleText": extraction.text,
        "articleTextChars": len(extraction.text),
        "articleTextMethod": extraction.method,
        "articleTextUsable": len(extraction.text) >= min_article_chars,
        "publishedAt": row.get("publishedAt", ""),
        "language": "he",
        "rescue": {
            "source": "rescue",
            "recommendedAction": row.get("recommendedAction", ""),
            "qaErrors": row.get("qaErrors", []),
            "sourceQueueRow": row,
        },
        "suggestedCard": {
            "category": category,
            "categoryClass": category_class,
        },
        "currentCard": {
            "category": current_category,
            "categoryClass": current_class,
            "headline": row.get("deterministicHeadline", ""),
            "summary": row.get("deterministicContext", ""),
            "takeaway": row.get("deterministicTakeaway", ""),
        },
    }


def make_editor_input(rows: list[dict[str, Any]], min_article_chars: int) -> list[dict[str, Any]]:
    return [row_to_editor_item(i, row, min_article_chars) for i, row in enumerate(rows)]


def write_prompt(run_dir: Path, batch_files: list[Path]) -> None:
    batches = ", ".join(p.name for p in batch_files)
    prompt = f"""# Pointa full-editor rescue run

This is a **local rescue queue** run. It exists to inspect fresh items from important sources that deterministic Pointa QA rejected before the full editor could rewrite them.

Process each `batch_*.json` file in this directory: {batches}

For every item:
1. Treat `articleText` as the primary source when `articleTextChars` is sufficient.
2. Use `rescue.qaErrors` and `currentCard` only to understand why the deterministic card failed; do not preserve bad generic wording.
3. Return `reject` when the available text is too thin for a specific Pointa headline, summary, and takeaway.
4. Keep Hebrew output concise and follow the Pointa editor contract.
5. Do not publish, deploy, or apply results from this directory directly.

Write one result file per batch, named `batch_N_results.json`.
Each result object must include:

```json
{{
  "index": 0,
  "status": "pass|reject",
  "category": "...",
  "categoryClass": "security|money|tech|real|",
  "headline": "...",
  "summary": "...",
  "takeaway": "...",
  "rejectReason": "",
  "qualityNotes": ["..."],
  "currentProblems": ["..."],
  "changedFields": {{"headline": true, "summary": true, "takeaway": true, "category": false}}
}}
```
"""
    (run_dir / "EDITOR_PROMPT.md").write_text(prompt, encoding="utf-8")


def command_prepare(args: argparse.Namespace) -> int:
    queue_path = Path(args.queue)
    queue = load_queue(queue_path)
    selected = select_rescue_items(queue, args.limit)
    run_id = args.run_id or "rescue-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    editor_input = make_editor_input(selected, args.min_article_chars)
    (run_dir / "editor_input.json").write_text(
        json.dumps(editor_input, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    batch_files: list[Path] = []
    for batch_index, start in enumerate(range(0, len(editor_input), args.batch_size), start=1):
        batch = editor_input[start:start + args.batch_size]
        path = run_dir / f"batch_{batch_index}.json"
        path.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        batch_files.append(path)

    write_prompt(run_dir, batch_files)
    metadata = {
        "runId": run_id,
        "source": "rescue",
        "mode": "local-prepare-only",
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "queue": str(queue_path.resolve()),
        "queueCheckedAt": queue.get("checkedAt", ""),
        "queueRecommendedAction": "send_to_full_editor_rescue_queue",
        "items": len(editor_input),
        "usableArticleText": sum(1 for x in editor_input if x.get("articleTextChars", 0) >= args.min_article_chars),
        "minArticleChars": args.min_article_chars,
        "batchSize": args.batch_size,
        "batches": [p.name for p in batch_files],
        "note": "Local rescue editor input only; feed.json/dist are not changed and nothing is deployed.",
    }
    (run_dir / "run.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(run_dir)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="Prepare local editor batches from pointa_source_rescue_queue.json")
    p.add_argument("--queue", default=str(DEFAULT_QUEUE))
    p.add_argument("--limit", type=int, default=24)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--min-article-chars", type=int, default=350)
    p.add_argument("--run-id", default="")
    p.set_defaults(func=command_prepare)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
