#!/usr/bin/env python3
"""Generate static article share pages with OpenGraph metadata for WhatsApp."""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

APP_NAME = "Poenta"
DEFAULT_IMAGE = "https://poenta.app/icon-512.png"
LEGACY_ASSET_HOSTS = {"poanta-demo.pages.dev"}
TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src"}


def clean_url(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        parts = urlsplit(value)
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    except Exception:
        return value.split("?")[0].split("#")[0].rstrip("/")


def item_identity(item: dict) -> str:
    url = clean_url(item.get("sourceUrl") or item.get("url") or "")
    if url:
        return url.lower()
    text = "|".join(str(item.get(k, "")) for k in ("source", "sourceLogo", "originalTitle", "headline"))
    return re.sub(r"[^0-9A-Za-z\u0590-\u05ff]+", "", text).lower()[:160]


def share_id(item: dict) -> str:
    # FNV-1a 64-bit is intentionally mirrored in index.html so the static app can
    # build the exact same share URL without loading the manifest first.
    value = 0xCBF29CE484222325
    for byte in item_identity(item).encode("utf-8"):
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"a-{value:016x}"


def compact(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def display_headline(item: dict) -> str:
    return compact(item.get("headline") or item.get("originalTitle") or "ידיעה חדשה ב־Poenta", 120)


def description(item: dict) -> str:
    return compact(item.get("context") or item.get("summary") or item.get("takeaway") or item.get("originalTitle") or "פתחו את הידיעה ב־Poenta.", 220)


def preview_image(item: dict, app_base: str) -> str:
    """Return a stable HTTPS image URL for social preview crawlers."""
    value = str(item.get("imageUrl") or DEFAULT_IMAGE).strip()
    try:
        parts = urlsplit(value)
        if parts.netloc.lower() in LEGACY_ASSET_HOSTS and parts.path.startswith("/assets/"):
            base = urlsplit(app_base)
            return urlunsplit((base.scheme or "https", base.netloc, parts.path, "", ""))
    except Exception:
        pass
    return value


def safe_item(item: dict, sid: str, share_url: str) -> dict:
    keep = {
        "shareId": sid,
        "shareUrl": share_url,
        "source": item.get("source", ""),
        "sourceGroup": item.get("sourceGroup", ""),
        "sourceLogo": item.get("sourceLogo", ""),
        "sourceUrl": item.get("sourceUrl", ""),
        "originalTitle": item.get("originalTitle", ""),
        "publishedAt": item.get("publishedAt", ""),
        "updatedAt": item.get("updatedAt", ""),
        "category": item.get("category", "חדשות"),
        "categoryClass": item.get("categoryClass", ""),
        "headline": item.get("headline", ""),
        "context": item.get("context", ""),
        "takeaway": item.get("takeaway", ""),
        "imageUrl": item.get("imageUrl", ""),
    }
    return {k: v for k, v in keep.items() if v not in (None, "")}


def page_html(item: dict, sid: str, app_base: str, share_url: str) -> str:
    title = display_headline(item)
    desc = description(item)
    image = preview_image(item, app_base)
    redirect = f"./../../app/?share={sid}&view=saved"
    canonical = share_url
    return f"""<!doctype html>
<html lang=\"he\" dir=\"rtl\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>{html.escape(title)}</title>
<link rel=\"canonical\" href=\"{html.escape(canonical)}\">
<meta name=\"description\" content=\"{html.escape(desc)}\">
<meta property=\"og:type\" content=\"article\">
<meta property=\"og:site_name\" content=\"{APP_NAME}\">
<meta property=\"og:title\" content=\"{html.escape(title)}\">
<meta property=\"og:description\" content=\"{html.escape(desc)}\">
<meta property=\"og:image\" content=\"{html.escape(image)}\">
<meta property=\"og:image:secure_url\" content=\"{html.escape(image)}\">
<meta property=\"og:url\" content=\"{html.escape(canonical)}\">
<meta name=\"twitter:card\" content=\"summary_large_image\">
<meta name=\"twitter:title\" content=\"{html.escape(title)}\">
<meta name=\"twitter:description\" content=\"{html.escape(desc)}\">
<meta name=\"twitter:image\" content=\"{html.escape(image)}\">
<script>window.location.replace('{redirect}');</script>
<style>body{{margin:0;min-height:100vh;background:#071015;color:#f6f7f8;font-family:Arial,sans-serif;display:grid;place-items:center;text-align:right;padding:24px}}.card{{max-width:520px;border:1px solid rgba(255,196,0,.24);border-radius:20px;padding:22px;background:#0b151a}}a{{color:#ffc400}}</style>
</head>
<body><main class=\"card\"><h1>{html.escape(title)}</h1><p>{html.escape(desc)}</p><p><a href=\"{redirect}\">פתחו את הידיעה ב־Poenta</a></p></main></body>
</html>
"""


def generate(feed_path: Path, out_dir: Path, app_base: str) -> int:
    data = json.loads(feed_path.read_text(encoding="utf-8"))
    items = data.get("items") if isinstance(data, dict) else []
    share_root = out_dir / "share"
    share_root.mkdir(parents=True, exist_ok=True)
    manifest_items = []
    seen = set()
    app_base = app_base.rstrip("/") + "/"
    for item in items or []:
        if not isinstance(item, dict):
            continue
        sid = share_id(item)
        if sid in seen:
            continue
        seen.add(sid)
        share_url = f"{app_base}share/{sid}/"
        row = safe_item(item, sid, share_url)
        manifest_items.append(row)
        page_dir = share_root / sid
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "index.html").write_text(page_html(row, sid, app_base, share_url), encoding="utf-8")
    (share_root / "articles.json").write_text(json.dumps({"items": manifest_items}, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(manifest_items)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", default="feed.json", type=Path)
    parser.add_argument("--out", default="dist", type=Path)
    parser.add_argument("--app-base", default="https://poenta.app/")
    args = parser.parse_args()
    count = generate(args.feed, args.out, args.app_base)
    print(f"Generated {count} share pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
