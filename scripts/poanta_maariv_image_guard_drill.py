#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression drill: Maariv automation must not publish misassigned images.

Maariv article pages/RSS fallbacks can surface unrelated images.maariv.co.il
assets (for example 103fm artwork on a politics article).  For www.maariv.co.il
feed cards, a neutral no-image card is safer than a wrong image.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from update_feed import fetch_article_image, is_rejected_source_image  # noqa: E402


def main() -> int:
    maariv_article = "https://www.maariv.co.il/news/politics/article-1327400"
    bad_image = "https://images.maariv.co.il/image/upload/f_auto,fl_lossy/c_fill,g_faces:center,h_250,w_250/873456"
    tmi_article = "https://tmi.maariv.co.il/celebs-news/article-1327400"

    checks = [
        (is_rejected_source_image(bad_image, maariv_article), "www.maariv.co.il images.maariv.co.il asset should be rejected"),
        (not is_rejected_source_image(bad_image, tmi_article), "tmi.maariv.co.il keeps its separate visual contract"),
        (fetch_article_image(maariv_article) == "", "Maariv fallback enrichment must not repopulate rejected images"),
    ]
    failures = [msg for ok, msg in checks if not ok]
    if failures:
        for msg in failures:
            print(f"FAIL: {msg}", file=sys.stderr)
        return 1
    print("ok: Maariv misassigned-image guard holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
