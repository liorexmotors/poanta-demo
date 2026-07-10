#!/usr/bin/env python3
"""Apply Poenta's local image bank to a feed draft and report gaps.

This script is safe-by-default: it writes a new output feed and report, and does
not deploy or overwrite the live feed unless the caller explicitly points --out
at feed.json.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from poenta_image_bank import apply_image_bank_to_item, load_catalog


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEED = ROOT / "feed.json"
DEFAULT_OUT = ROOT / "tmp" / "poenta-image-bank" / "feed.with-image-bank.json"
DEFAULT_REPORT = ROOT / "tmp" / "poenta-image-bank" / "image-bank-report.json"
DEFAULT_REPORT_CSV = ROOT / "tmp" / "poenta-image-bank" / "image-bank-missing.csv"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_poenta_image(url: str) -> bool:
    return "poanta-demo.pages.dev/assets/" in (url or "") or "/assets/" in (url or "")


def item_identity(item: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "index": index,
        "category": item.get("category", ""),
        "source": item.get("source", ""),
        "headline": item.get("headline") or item.get("title") or "",
        "originalTitle": item.get("originalTitle", ""),
        "sourceUrl": item.get("sourceUrl") or item.get("url") or "",
        "previousImageUrl": item.get("imageUrl", ""),
    }


def apply_feed(feed: dict[str, Any], *, catalog_path: str | None, min_score: float) -> tuple[dict[str, Any], dict[str, Any]]:
    catalog = load_catalog(catalog_path)
    out = dict(feed)
    out_items: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    matched: list[dict[str, Any]] = []
    kept_local = 0
    external_before = 0
    default_after = 0
    category_counts: Counter[str] = Counter()
    bank_key_counts: Counter[str] = Counter()
    non_object_items = 0

    for index, raw in enumerate(feed.get("items") or []):
        if not isinstance(raw, dict):
            out_items.append(raw)
            non_object_items += 1
            continue
        previous_url = str(raw.get("imageUrl") or "")
        if previous_url and not is_poenta_image(previous_url):
            external_before += 1

        fixed, info = apply_image_bank_to_item(raw, catalog, min_score=min_score)
        out_items.append(fixed)

        category_counts[str(fixed.get("category") or "")] += 1
        if str(fixed.get("imageFallbackKind") or ""):
            default_after += 1
        if info["status"] == "matched":
            match = info["match"]
            bank_key_counts[str(match.get("key") or "")] += 1
            matched.append(
                {
                    **item_identity(raw, index),
                    "imageBankKey": match.get("key"),
                    "imageBankTitle": match.get("title_he"),
                    "imageBankScore": match.get("matchScore"),
                    "imageBankSignals": match.get("matchSignals"),
                    "newImageUrl": fixed.get("imageUrl", ""),
                }
            )
        else:
            missing.append(
                {
                    **item_identity(raw, index),
                    "fallbackKind": info.get("fallbackKind"),
                    "newImageUrl": fixed.get("imageUrl", ""),
                }
            )

        if previous_url and is_poenta_image(previous_url):
            kept_local += 1

    out["items"] = out_items
    out["imageBankAppliedAt"] = datetime.now(timezone(timedelta(hours=3))).isoformat(timespec="seconds")
    out["imageBankPolicy"] = {
        "rssImagesRemoved": True,
        "minScore": min_score,
        "missingFallback": "local feed-defaults image + imageBankMissing=true",
    }
    report = {
        "generatedAt": out["imageBankAppliedAt"],
        "items": len(out_items),
        "catalogItems": len(catalog),
        "externalRssImagesBefore": external_before,
        "localImagesBefore": kept_local,
        "matchedToImageBank": len(matched),
        "missingImageBankMatch": len(missing),
        "nonObjectItemsPreserved": non_object_items,
        "localDefaultImagesAfter": default_after,
        "categories": dict(category_counts.most_common()),
        "topImageBankKeys": dict(bank_key_counts.most_common(40)),
        "missing": missing,
        "matchedSample": matched[:100],
    }
    return out, report


def write_missing_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["index", "category", "source", "headline", "originalTitle", "sourceUrl", "fallbackKind", "previousImageUrl"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default=str(DEFAULT_FEED))
    ap.add_argument("--catalog", default=None)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--missing-csv", default=str(DEFAULT_REPORT_CSV))
    ap.add_argument("--min-score", type=float, default=4.0)
    args = ap.parse_args()

    feed = load_json(Path(args.feed))
    out, report = apply_feed(feed, catalog_path=args.catalog, min_score=args.min_score)
    write_json(Path(args.out), out)
    write_json(Path(args.report), report)
    write_missing_csv(Path(args.missing_csv), report["missing"])
    print(
        json.dumps(
            {
                "ok": True,
                "out": args.out,
                "report": args.report,
                "missingCsv": args.missing_csv,
                "items": report["items"],
                "catalogItems": report["catalogItems"],
                "externalRssImagesBefore": report["externalRssImagesBefore"],
                "matchedToImageBank": report["matchedToImageBank"],
                "missingImageBankMatch": report["missingImageBankMatch"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
