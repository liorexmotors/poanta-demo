#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pointa_quality_gate as quality_gate  # type: ignore


class PointaQualityGateTests(unittest.TestCase):
    def test_blocks_headline_that_starts_mid_source_sentence(self) -> None:
        item = {
            "headline": 'בהלוויה, בה נוכח גם יו"ר "ישר!" גדי איזנקוט',
            "context": "הלוויתו של סרן דוד חזות מתקיימת בבית העלמין באשקלון.",
            "originalTitle": "הלוויתו של סרן דוד חזות, שנפל בקרב בדרום לבנון | ישיר",
            "source": "וואלה חדשות - צבא וביטחון",
            "sourceUrl": "https://news.walla.co.il/item/3849295",
            "category": "ביטחון",
        }
        issues: list[dict[str, object]] = []

        quality_gate.validate_item(item, 1, issues)

        self.assertIn("headline_mid_sentence_fragment", {issue["code"] for issue in issues})


if __name__ == "__main__":
    unittest.main()
