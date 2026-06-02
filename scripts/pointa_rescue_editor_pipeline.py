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
FEED_FILE = ROOT / "feed.json"


def load_queue(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError(f"{path} must contain an object with an items array")
    return data


def load_existing_feed_urls(feed_file: Path = FEED_FILE) -> set[str]:
    """Return source URLs already visible in feed.json.

    Stage-3 rescue must not create artificial freshness by selecting a row whose
    exact article URL is already in the public/local feed. Re-publishing the same
    URL with a newer rescue timestamp makes the top feed look fresh without a new
    story and repeatedly wastes editor batches on duplicates.
    """
    if not feed_file.exists():
        return set()
    try:
        with feed_file.open(encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return set()
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return set()
    urls: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or item.get("sourceUrl") or "").strip()
        if url:
            urls.add(url)
    return urls


def select_rescue_items(queue: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    existing_feed_urls = load_existing_feed_urls()
    for row in queue.get("items", []):
        if row.get("recommendedAction") != "send_to_full_editor_rescue_queue":
            continue
        url = (row.get("sourceUrl") or "").strip()
        if not url or url in seen_urls or url in existing_feed_urls:
            continue
        selected.append(row)
        seen_urls.add(url)
        if len(selected) >= limit:
            break
    return selected


def editor_item_matches_domain(domain: str, item: dict[str, Any]) -> bool:
    """Return whether an extracted editor item still belongs to a Stage-4 domain.

    The source rescue queue classifies rows from RSS snippets.  After full article
    extraction, titles/descriptions can change enough that a row no longer belongs
    to the breached domain.  Stage-4 must filter here, before writing editor
    batches, instead of preparing work that the autopilot hard gate will block as
    off-domain.
    """
    domain = (domain or "").strip()
    if not domain:
        return True
    # Match pointa_autopilot.validate_domain_editor_run exactly: validate against
    # the extracted title + description/article text that will be sent to the
    # editor, not against the RSS-snippet current card.
    title = str(item.get("originalTitle") or item.get("title") or item.get("headline") or "")
    desc = " ".join(str(item.get(k) or "") for k in ("description", "summary", "articleText"))
    source = str(item.get("source") or "")
    category, _category_class = update_feed.categorize_item(title, desc, source)
    if category == domain:
        return True
    if domain == "חדשות" and category in {"חדשות", "בארץ"}:
        return True
    return False


def select_editor_input_adaptive(queue: dict[str, Any], limit: int, min_article_chars: int, oversample_factor: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select rescue rows after article extraction, not before it.

    The 2026-05-21 stuck-feed incident exposed a repeat failure mode: the first
    rescue batch could be consumed by stale-source or premium/thin candidates
    that looked important in RSS but did not have enough extractable article
    text for a trustworthy Pointa card.  That made the project wait for editor
    work that was likely to reject the items anyway, while fresh usable
    candidates remained below the cutoff.

    To prevent that, we oversample the queue, extract article text, then fill the
    editor run with usable candidates first while preserving queue order.  Thin
    rows are still kept as fallback only when there are not enough usable rows,
    so quality remains strict and the editor can explicitly reject them.
    """
    oversample_factor = max(1, oversample_factor)
    candidates = select_rescue_items(queue, max(limit, limit * oversample_factor))
    all_input = make_editor_input(candidates, min_article_chars)
    domain = str(queue.get("domain") or "").strip()
    domain_filtered_input = [x for x in all_input if editor_item_matches_domain(domain, x)]
    domain_filtered_out = len(all_input) - len(domain_filtered_input)
    all_input = domain_filtered_input
    usable = [x for x in all_input if x.get("articleTextChars", 0) >= min_article_chars]
    thin = [x for x in all_input if x.get("articleTextChars", 0) < min_article_chars]
    def group_key(item: dict[str, Any]) -> str:
        rescue = item.get("rescue") or {}
        row = rescue.get("sourceQueueRow") or {}
        return (item.get("sourceGroup") or row.get("sourceGroup") or item.get("source") or "").strip()

    # Stuck-feed rescue is judged by visible freshness *and* source diversity.
    # A recurring failure mode was queue order: one very chatty publisher
    # (usually Walla) filled the first editor batch, so the final feed still
    # failed the recent-source SLA even after good editing.  Keep quality strict,
    # but select usable article-text rows with a soft per-source cap first, then
    # fill remaining slots.  This makes the rescue batch capable of satisfying
    # the publication health gate without lowering editorial standards.
    per_group_cap = max(2, limit // 6)
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    group_counts: dict[str, int] = {}

    def consider(rows: list[dict[str, Any]], *, enforce_cap: bool) -> None:
        for item in rows:
            if len(selected) >= limit:
                return
            ident = id(item)
            if ident in selected_ids:
                continue
            key = group_key(item)
            if enforce_cap and group_counts.get(key, 0) >= per_group_cap:
                continue
            selected.append(item)
            selected_ids.add(ident)
            group_counts[key] = group_counts.get(key, 0) + 1

    consider(usable, enforce_cap=True)
    consider(usable, enforce_cap=False)
    consider(thin, enforce_cap=True)
    consider(thin, enforce_cap=False)
    selected = selected[:limit]
    for new_index, item in enumerate(selected):
        item["index"] = new_index
    stats = {
        "queueItemsConsidered": len(candidates),
        "usableConsidered": len(usable),
        "thinConsidered": len(thin),
        "selectedUsable": sum(1 for x in selected if x.get("articleTextChars", 0) >= min_article_chars),
        "selectedThin": sum(1 for x in selected if x.get("articleTextChars", 0) < min_article_chars),
        "selectedSourceGroups": sorted({group_key(x) for x in selected}),
        "perSourceGroupSoftCap": per_group_cap,
        "oversampleFactor": oversample_factor,
        "selectionMode": "adaptive_extract_then_select_diverse_sources_first",
        "domain": domain or None,
        "domainFilteredOutAfterExtraction": domain_filtered_out,
    }
    return selected, stats


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
5. Category boundary: `אקטואליה בעולם` is only for global stories with no Israel/Middle-East angle. If the item is about Israel, Gaza, Iran, Lebanon, the Abraham Accords, normalization with Israel, or Middle-East diplomacy/security, use the normal domains (`ביטחון`, `פוליטיקה`, or `חדשות`) even when the source is foreign.
6. Do not publish, deploy, or apply results from this directory directly.

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
    run_id = args.run_id or "rescue-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    editor_input, selection_stats = select_editor_input_adaptive(queue, args.limit, args.min_article_chars, args.oversample_factor)
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
        "selection": selection_stats,
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
    p.add_argument("--oversample-factor", type=int, default=3, help="Extract up to limit*N queue rows, then pick usable article-text rows first")
    p.add_argument("--run-id", default="")
    p.set_defaults(func=command_prepare)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
