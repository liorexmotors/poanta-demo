#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pointa_editor_pipeline as pipeline  # type: ignore


class PointaEditorPipelineTests(unittest.TestCase):
    def test_preview_adds_source_activity_for_new_editor_items(self) -> None:
        feed = {"updatedAt": "2026-05-27T10:00:00+03:00", "items": [], "sourceActivity": []}
        editor_input = [{
            "index": 0,
            "source": "N12 - בעולם",
            "sourceGroup": "N12",
            "sourceUrl": "https://example.com/n12",
            "originalTitle": "מקור מקורי",
            "publishedAt": "2026-05-27T11:00:00+03:00",
            "currentCard": {"category": "חדשות", "categoryClass": "", "headline": "ישן", "summary": "ישן", "takeaway": "ישן"},
            "suggestedCard": {"category": "חדשות", "categoryClass": ""},
        }]
        results = [{
            "index": 0,
            "status": "pass",
            "category": "חדשות",
            "categoryClass": "",
            "headline": "כותרת פואנטה חדשה",
            "summary": "סיכום חדש",
            "takeaway": "פואנטה חדשה",
        }]

        preview = pipeline.build_preview_feed(feed, editor_input, results)

        self.assertEqual(len(preview.get("sourceActivity", [])), 1)
        row = preview["sourceActivity"][0]
        self.assertEqual(row["source"], "N12")
        self.assertEqual(row["subSource"], "N12 - בעולם")
        self.assertEqual(row["publishedAt"], "2026-05-27T11:00:00+03:00")
        self.assertEqual(row["title"], "כותרת פואנטה חדשה")


if __name__ == "__main__":
    unittest.main()
