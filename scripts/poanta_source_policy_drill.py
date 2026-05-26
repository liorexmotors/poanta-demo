#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Poanta source-policy regression checks.

Keeps approved source strategy deterministic: N12/mako infrastructure is allowed,
but the noisy broad N12 news feed should not be active once precise N12 section
feeds are configured.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "rss_sources.json"

REQUIRED_N12_SECTION_FEEDS = {
    "N12 - ביטחוני ופוליטי",
    "N12 - פלילים ומשפט",
    "N12 - בארץ",
    "N12 - כלכלה וצרכנות",
    "N12 - בעולם",
}
BROAD_N12_NEWS = "N12 - חדשות"


def main() -> int:
    data = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    active = data.get("active", [])
    active_names = {src.get("name") for src in active}
    errors: list[str] = []

    if BROAD_N12_NEWS in active_names:
        errors.append(
            f"{BROAD_N12_NEWS} is active; use precise N12 section feeds instead to avoid category noise."
        )

    missing_sections = sorted(REQUIRED_N12_SECTION_FEEDS - active_names)
    if missing_sections:
        errors.append("missing required N12 section feeds: " + ", ".join(missing_sections))

    mislabeled = [
        src.get("name", "")
        for src in active
        if src.get("rss", "").startswith("https://rcs.mako.co.il/rss/news-")
        and src.get("logo") != "N12"
    ]
    if mislabeled:
        errors.append("N12 section feeds must keep visible logo N12: " + ", ".join(mislabeled))

    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "active_n12_sections": sorted(REQUIRED_N12_SECTION_FEEDS),
                "broad_n12_news_active": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
