#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression drill: article-page enrichment must not erase source/RSS text.

Lior reported a visible freshness/filtering failure where Ynet RSS items were
fresh and contained useful descriptions, but article-page metadata extraction
failed and the enrichment step erased that source text.  This drill generalizes
that invariant across all active Poanta sources: when article fetch/enrichment
fails, an already-useful Candidate.description from the source feed/telegram row
must survive unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_feed  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify enrichment preserves existing source descriptions for all active sources")
    ap.add_argument("--sync-profile", choices=["all", "fast", "medium", "slow"], default="all")
    ap.add_argument("--sample-per-source", type=int, default=2)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows: list[dict] = []
    failures: list[dict] = []
    original_fetch = update_feed.fetch

    try:
        sources = update_feed.load_sources(args.sync_profile)
        for source in sources:
            name = source.get("name", "")
            try:
                candidates = update_feed.extract_source(source)
            except Exception as exc:  # source health is reported, but not this invariant's failure
                rows.append({"source": name, "status": "source_extract_error", "error": str(exc)})
                continue

            with_desc = [c for c in candidates if (c.description or "").strip()]
            tested = 0
            for candidate in with_desc[: max(1, args.sample_per_source)]:
                before = candidate.description

                def failing_article_fetch(url: str, timeout: int = 15) -> str:  # type: ignore[override]
                    # RSS/telegram extraction already happened.  During enrichment,
                    # force article/Jina fetch failure to simulate WAF/blocked/empty pages.
                    raise RuntimeError(f"forced article fetch failure for {url}")

                update_feed.fetch = failing_article_fetch
                try:
                    enriched = update_feed.enrich(candidate)
                finally:
                    update_feed.fetch = original_fetch
                tested += 1
                if enriched.description != before:
                    failure = {
                        "source": name,
                        "url": candidate.url,
                        "before": before,
                        "after": enriched.description,
                    }
                    failures.append(failure)
            if tested:
                rows.append({"source": name, "status": "ok", "candidates": len(candidates), "with_description": len(with_desc), "tested": tested})
            else:
                rows.append({"source": name, "status": "no_source_description_to_test", "candidates": len(candidates), "with_description": 0})
    finally:
        update_feed.fetch = original_fetch

    summary = {
        "status": "fail" if failures else "ok",
        "sources_checked": len(rows),
        "sources_tested": sum(1 for r in rows if r.get("status") == "ok"),
        "items_tested": sum(int(r.get("tested") or 0) for r in rows),
        "failures": failures,
        "source_rows": rows,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"status={summary['status']} sources_checked={summary['sources_checked']} sources_tested={summary['sources_tested']} items_tested={summary['items_tested']} failures={len(failures)}")
        for row in rows:
            if row.get("status") != "ok":
                print(f"WARN {row.get('source')}: {row.get('status')} candidates={row.get('candidates')} error={row.get('error','')}")
        for failure in failures:
            print(f"FAIL {failure['source']} {failure['url']}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
