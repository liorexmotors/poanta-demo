#!/usr/bin/env python3
"""Convert Poenta's public V5 image bank to one lightweight WebP format.

The source feed and image generator use the same 960x540 assets for Web and
native apps. Existing PNG/JPEG files are removed only after every conversion
has been decoded successfully and the active feed references have been
rewritten.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "assets" / "poenta-image-bank-v5"
PUBLIC_PREFIX = "https://poanta-demo.pages.dev/assets/poenta-image-bank-v5/"
FEED_PATHS = (
    ROOT / "feed.json",
    ROOT / "breaking_feed.json",
    ROOT / "feed_b.json",
    ROOT / "feed_a_side.json",
    ROOT / "feed_a_breaking.json",
)
TARGET_SIZE = (960, 540)
QUALITY = 78


def convert(source: Path) -> Path:
    if source.suffix.lower() == ".webp":
        target = source
    else:
        target = source.with_suffix(".webp")
    if target != source and target.exists():
        raise RuntimeError(f"target collision: {target}")
    if target == source:
        with Image.open(source) as current:
            if current.size[0] <= TARGET_SIZE[0] and current.size[1] <= TARGET_SIZE[1]:
                current.verify()
                return target
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        image.thumbnail(TARGET_SIZE, Image.Resampling.LANCZOS)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        image.save(tmp, format="WEBP", quality=QUALITY, method=6)
    with Image.open(tmp) as verified:
        verified.verify()
    tmp.replace(target)
    return target


def rewrite_urls(value: Any, replacements: dict[str, str]) -> tuple[Any, int]:
    if isinstance(value, dict):
        changed = 0
        output: dict[str, Any] = {}
        for key, child in value.items():
            output[key], count = rewrite_urls(child, replacements)
            changed += count
        return output, changed
    if isinstance(value, list):
        changed = 0
        output = []
        for child in value:
            rewritten, count = rewrite_urls(child, replacements)
            output.append(rewritten)
            changed += count
        return output, changed
    if isinstance(value, str):
        replacement = replacements.get(value)
        return (replacement, 1) if replacement else (value, 0)
    return value, 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    sources = sorted(path for path in ASSET_DIR.iterdir() if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
    if not args.apply:
        print(json.dumps({"mode": "dry-run", "assets": len(sources), "target": list(TARGET_SIZE), "quality": QUALITY}))
        return

    replacements: dict[str, str] = {}
    converted: list[tuple[Path, Path]] = []
    original_bytes = sum(path.stat().st_size for path in sources)
    for source in sources:
        target = convert(source)
        converted.append((source, target))
        if source != target:
            replacements[PUBLIC_PREFIX + source.name] = PUBLIC_PREFIX + target.name

    changed_by_file: dict[str, int] = {}
    for path in FEED_PATHS:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        rewritten, changed = rewrite_urls(payload, replacements)
        if changed:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(rewritten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            json.loads(tmp.read_text(encoding="utf-8"))
            tmp.replace(path)
        changed_by_file[path.name] = changed

    for source, target in converted:
        if source != target:
            source.unlink()

    targets = sorted(ASSET_DIR.glob("*.webp"))
    optimized_bytes = sum(path.stat().st_size for path in targets)
    print(json.dumps({
        "mode": "applied",
        "assets": len(targets),
        "referencesChanged": changed_by_file,
        "originalBytes": original_bytes,
        "optimizedBytes": optimized_bytes,
        "reductionPercent": round((1 - optimized_bytes / max(1, original_bytes)) * 100, 2),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
