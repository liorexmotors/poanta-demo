#!/usr/bin/env python3
"""Create branded copies for all V5 images currently referenced by feed.json."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path

from PIL import Image
from poenta_v5_feed_images import (
    DOMAIN_DEFAULT_DIR,
    DOMAIN_DEFAULT_FILES,
    EMERGENCY_FALLBACK_FILE,
    build_catalog,
    canonical,
)

ROOT = Path(__file__).resolve().parents[1]
FEED_PATHS = (ROOT / "feed.json", ROOT / "dist/feed.json")
ASSET_DIRS = (ROOT / "assets/poenta-image-bank-v5", ROOT / "dist/assets/poenta-image-bank-v5")
LOGO_PATH = ROOT / "assets/poenta-logo-watermark-transparent.png"
PUBLIC_PREFIX = "https://poanta-demo.pages.dev/assets/poenta-image-bank-v5/"
SUFFIX = "-poenta-v3"


def branded_name(filename: str, public_path: str) -> str:
    digest = hashlib.sha256(public_path.encode("utf-8")).hexdigest()[:10]
    return f"{Path(filename).stem}-{digest}{SUFFIX}.png"


def brand_image(source: Path, target: Path) -> None:
    with Image.open(source) as base_source, Image.open(LOGO_PATH) as logo_source:
        base = base_source.convert("RGBA")
        logo = logo_source.convert("RGBA")
        width = max(64, round(base.width * 0.10))
        height = max(1, round(logo.height * width / logo.width))
        logo = logo.resize((width, height), Image.Resampling.LANCZOS)
        margin_x = max(48, round(base.width * 0.10))
        margin_y = max(24, round(base.height * 0.065))
        base.alpha_composite(logo, (margin_x, margin_y))
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = ROOT / "tmp" / "poenta-image-branding"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp = tmp_dir / f"{target.name}.{os.getpid()}.tmp"
        base.convert("RGB").save(tmp, format="PNG", optimize=True)
        tmp.replace(target)


def main() -> None:
    payload = json.loads(FEED_PATHS[0].read_text(encoding="utf-8"))
    catalog_by_id = {row["imageId"]: Path(row["file"]) for row in build_catalog()}
    generated: set[str] = set()
    changed = 0
    missing: list[str] = []
    for item in payload.get("items", []):
        url = str(item.get("imageUrl") or "")
        filename = url.rsplit("/", 1)[-1]
        if (
            not filename
            or filename.endswith(f"{SUFFIX}.png")
        ):
            continue
        public_path = url.split("poanta-demo.pages.dev/", 1)[-1].split("?", 1)[0].lstrip("/")
        image_id = str(item.get("poentaImageId") or "")
        source = catalog_by_id.get(image_id)
        if image_id.startswith("DOMAIN-"):
            domain_file = DOMAIN_DEFAULT_FILES.get(canonical(item.get("imageDomain") or item.get("category")))
            source = DOMAIN_DEFAULT_DIR / domain_file if domain_file else None
        elif image_id == "EMERGENCY-POENTA-NEWS":
            source = EMERGENCY_FALLBACK_FILE
        if source is None:
            # Legacy, unbranded local files can still be used directly. Never
            # stack a second logo on an already-branded asset.
            candidate = ROOT / public_path
            source = candidate if "-poenta-v" not in filename else None
        if source is None:
            # Historical feed cards outside the V5 trial have no catalog id.
            # Leave them unchanged; the active V5 cards are re-rendered from
            # their clean catalog source so the old logo is never duplicated.
            continue
        if not source.is_file():
            missing.append(filename)
            continue
        output_name = branded_name(filename, public_path)
        if output_name not in generated:
            brand_image(source, ASSET_DIRS[0] / output_name)
            generated.add(output_name)
        item["imageUrl"] = PUBLIC_PREFIX + output_name
        item["poentaLogoOverlay"] = {
            "position": "top-left",
            "size": "small",
            "version": 1,
        }
        changed += 1

    if missing:
        raise SystemExit(f"Missing {len(set(missing))} source assets: {sorted(set(missing))[:5]}")

    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for feed_path in FEED_PATHS:
        feed_path.write_text(rendered, encoding="utf-8")
    for output_name in generated:
        source = ASSET_DIRS[0] / output_name
        target = ASSET_DIRS[1] / output_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    print(json.dumps({"updatedItems": changed, "generatedAssets": len(generated)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
