#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pointa_source_rescue_queue as queue  # type: ignore


class PointaSourceRescueQueueTests(unittest.TestCase):
    def test_editorial_qa_errors_are_repair_not_final_reject(self) -> None:
        errors = [
            {"code": "headline_copies_source"},
            {"code": "takeaway_generic"},
        ]
        self.assertEqual(queue.rescue_disposition(errors), "repair_editorial_soft_fail")

    def test_hard_sanitation_errors_are_report_only(self) -> None:
        self.assertEqual(queue.rescue_disposition([{"code": "html_artifact"}]), "hard_reject_report_only")

    def test_security_domain_keeps_security_candidate_even_if_deterministic_category_is_wrong(self) -> None:
        item = {
            "category": "חדשות",
            "headline": "אבד קשר עם מטרות אוויריות חשודות בצפון",
            "context": "שברי רחפן נפלו במרחב צבאי ללא נפגעים.",
            "source": "ynet - מבזקי החדשות",
            "originalTitle": "צה\"ל: אבד קשר עם מטרות אוויריות חשודות, שברי רחפן נפלו במרחב צבאי",
        }
        candidate = SimpleNamespace(title=item["originalTitle"], original_title=item["originalTitle"], description=item["context"])
        self.assertTrue(queue.domain_candidate_matches("ביטחון", item, candidate))

    def test_security_domain_filters_off_domain_sports_from_broad_source_group(self) -> None:
        item = {
            "category": "ספורט",
            "headline": "הפועל באר שבע תחזור להרכב הקלאסי בגמר",
            "context": "מאמן הקבוצה צפוי להחזיר שחקנים להרכב.",
            "source": "וואלה ספורט",
            "originalTitle": "תשכחו מהחגיגות: הפועל באר שבע תחזור להרכב הקלאסי שלה בגמר",
        }
        candidate = SimpleNamespace(title=item["originalTitle"], original_title=item["originalTitle"], description=item["context"])
        self.assertFalse(queue.domain_candidate_matches("ביטחון", item, candidate))

    def test_security_keyword_matching_does_not_match_hebrew_substrings(self) -> None:
        self.assertFalse(queue.keyword_in_text("רקטה", "הפרקט של ניו יורק"))
        self.assertFalse(queue.keyword_in_text("צהל", "בית בצהלה נמכר"))
        self.assertTrue(queue.keyword_in_text("רקטה", "רקטה שוגרה לצפון"))


if __name__ == "__main__":
    unittest.main()
