#!/usr/bin/env python3
"""Fail closed on V5 trial policy violations without rolling feed data back."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse


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


def image_identity(value: object) -> str:
    """Return the underlying asset identity, ignoring Poenta overlay versions."""
    filename = Path(urlparse(str(value or "")).path).name
    stem = Path(filename).stem
    stem = re.sub(r"-[0-9a-f]{10}-poenta-v\d+$", "", stem)
    stem = re.sub(r"-poenta-v\d+$", "", stem)
    return stem


def historical_image_unchanged(current: dict, previous: dict) -> bool:
    current_fields = image_fields(current)
    previous_fields = image_fields(previous)
    current_url = current_fields.pop("imageUrl", "")
    previous_url = previous_fields.pop("imageUrl", "")
    # Overlay metadata is presentation-only. Adding/upgrading the Poenta logo
    # must not be mistaken for changing the image assigned to an old article.
    current_fields.pop("poentaLogoOverlay", None)
    previous_fields.pop("poentaLogoOverlay", None)
    return (
        current_fields == previous_fields
        and image_identity(current_url) == image_identity(previous_url)
    )


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
        if previous is not None and not historical_image_unchanged(item, previous):
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
