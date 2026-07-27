#!/usr/bin/env python3
"""Fail closed on V5 trial policy violations without rolling feed data back."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "backups/poenta-v5-image-trial-baseline-20260727-v2/feed.json"
LIVE = ROOT / "feed.json"
DISABLE_MARKER = ROOT / ".poenta-v5-image-disabled"
TRIAL_ID = "pilot-20260727-v2"
TRIAL_LIMIT = 100


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def url(item: dict) -> str:
    return str(item.get("sourceUrl") or item.get("url") or "").strip()


def image_fields(item: dict) -> dict:
    return {
        key: value
        for key, value in item.items()
        if key == "imageUrl" or key.startswith("image") or key.startswith("poentaImage")
    }


def main() -> int:
    baseline = read(BASELINE)
    live = read(LIVE)
    baseline_by_url = {
        url(item): item
        for item in baseline.get("items", [])
        if isinstance(item, dict) and url(item)
    }
    live_items = [item for item in live.get("items", []) if isinstance(item, dict)]
    trial_items = [item for item in live_items if item.get("poentaImageTrialId") == TRIAL_ID]
    violations: list[dict] = []

    for item in live_items:
        key = url(item)
        previous = baseline_by_url.get(key)
        if previous is not None and image_fields(item) != image_fields(previous):
            violations.append({"code": "historical_image_changed", "url": key})

    if len(trial_items) > TRIAL_LIMIT:
        violations.append({"code": "trial_limit_exceeded", "count": len(trial_items)})

    for item in trial_items:
        key = url(item)
        if key in baseline_by_url:
            violations.append({"code": "trial_applied_to_historical_item", "url": key})
        image_url = str(item.get("imageUrl") or "")
        if not (
            image_url.startswith("/assets/")
            or "poanta-demo.pages.dev/assets/" in image_url
        ):
            violations.append({"code": "trial_external_or_missing_image", "url": key, "imageUrl": image_url})

    if violations:
        DISABLE_MARKER.touch()

    print(json.dumps({
        "ok": not violations,
        "trialId": TRIAL_ID,
        "trialItems": len(trial_items),
        "trialLimit": TRIAL_LIMIT,
        "historicalItemsChecked": sum(1 for item in live_items if url(item) in baseline_by_url),
        "imageMechanismEnabled": not DISABLE_MARKER.exists(),
        "autoDisabled": bool(violations),
        "violations": violations[:50],
    }, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
