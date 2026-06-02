#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pointa_rescue_editor_pipeline as rescue_pipeline  # type: ignore


class PointaRescueEditorPipelineDomainFilterTests(unittest.TestCase):
    def test_stage4_domain_filter_runs_after_article_extraction(self) -> None:
        extracted_items = [
            {
                "source": "ynet - כל ערוץ החדשות",
                "sourceUrl": "https://example.com/security",
                "originalTitle": "שרים בבת מצווה, רק 3 התייצבו ל\"דיון המיוחד\" על הצפון. נתניהו הגיע באיחור",
                "description": "הממשלה קיימה ישיבה על המלחמה בצפון וחיזבאללה",
                "articleText": "הממשלה קיימה ישיבה על המלחמה בצפון וחיזבאללה",
                "articleTextChars": 900,
                "suggestedCard": {"category": "ביטחון"},
                "currentCard": {"category": "פוליטיקה"},
            },
            {
                "source": "Israel National News English",
                "sourceUrl": "https://example.com/politics",
                "originalTitle": "הקואליציה דחתה את הצעת האופוזיציה בכנסת",
                "description": "המאבק הפוליטי נמשך ללא קשר לביטחון או מלחמה",
                "articleText": "הקואליציה דחתה את הצעת האופוזיציה בכנסת במסגרת מאבק פוליטי על סדר היום של הכנסת.",
                "articleTextChars": 900,
                "suggestedCard": {"category": "פוליטיקה"},
                "currentCard": {"category": "פוליטיקה"},
            },
            {
                "source": "וואלה חדשות - אסור לפספס",
                "sourceUrl": "https://example.com/weather",
                "originalTitle": "מה יצר את זכוכית החייזרים של הפרעה המפורסם? התשובה מפתיעה",
                "description": "מחקר חדש בוחן תופעה במדבר אחרי פגיעת מטאור",
                "articleText": "מחקר מדעי על סלעים וזכוכית מדברית אינו קשור לכנסת או לממשלה.",
                "articleTextChars": 900,
                "suggestedCard": {"category": "מזג אוויר"},
                "currentCard": {"category": "פוליטיקה"},
            },
        ]
        queue = {
            "domain": "פוליטיקה",
            "items": [
                {"sourceUrl": "https://example.com/security", "recommendedAction": "send_to_full_editor_rescue_queue"},
                {"sourceUrl": "https://example.com/politics", "recommendedAction": "send_to_full_editor_rescue_queue"},
                {"sourceUrl": "https://example.com/weather", "recommendedAction": "send_to_full_editor_rescue_queue"},
            ],
        }
        with patch.object(rescue_pipeline, "load_existing_feed_urls", return_value=set()), patch.object(
            rescue_pipeline, "make_editor_input", return_value=extracted_items
        ):
            selected, stats = rescue_pipeline.select_editor_input_adaptive(
                queue,
                limit=8,
                min_article_chars=400,
                oversample_factor=4,
            )

        self.assertEqual([item["sourceUrl"] for item in selected], ["https://example.com/politics"])
        self.assertEqual(stats["domain"], "פוליטיקה")
        self.assertEqual(stats["domainFilteredOutAfterExtraction"], 2)

    def test_non_domain_rescue_keeps_all_extracted_items(self) -> None:
        extracted_items = [
            {"sourceUrl": "https://example.com/a", "articleTextChars": 900, "suggestedCard": {"category": "ביטחון"}, "currentCard": {"category": "ביטחון"}},
            {"sourceUrl": "https://example.com/b", "articleTextChars": 900, "suggestedCard": {"category": "ספורט"}, "currentCard": {"category": "ספורט"}},
        ]
        queue = {
            "items": [
                {"sourceUrl": "https://example.com/a", "recommendedAction": "send_to_full_editor_rescue_queue"},
                {"sourceUrl": "https://example.com/b", "recommendedAction": "send_to_full_editor_rescue_queue"},
            ],
        }
        with patch.object(rescue_pipeline, "load_existing_feed_urls", return_value=set()), patch.object(
            rescue_pipeline, "make_editor_input", return_value=extracted_items
        ):
            selected, stats = rescue_pipeline.select_editor_input_adaptive(
                queue,
                limit=8,
                min_article_chars=400,
                oversample_factor=4,
            )

        self.assertEqual(len(selected), 2)
        self.assertIsNone(stats["domain"])
        self.assertEqual(stats["domainFilteredOutAfterExtraction"], 0)


if __name__ == "__main__":
    unittest.main()
