#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pointa_publish_rollback_guard as guard  # noqa: E402


def feed(updated, top, headline="כותרת", count=3):
    items = [{"publishedAt": top, "headline": headline, "source": "בדיקה"}]
    for i in range(count - 1):
        items.append({"publishedAt": top, "headline": f"עוד {i}", "source": "בדיקה"})
    return {"updatedAt": updated, "items": items}


class PointaPublishRollbackGuardTests(unittest.TestCase):
    def test_blocks_candidate_with_older_top_than_known_public(self):
        candidate = guard.feed_fingerprint(
            feed("2026-06-09T13:00:00+03:00", "2026-06-09T13:00:00+03:00"),
            source="candidate",
        )
        public = guard.feed_fingerprint(
            feed("2026-06-09T16:00:00+03:00", "2026-06-09T16:00:00+03:00"),
            source="public",
        )

        report = guard.compare_candidate(candidate, [public])

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["reason"], "candidate_older_than_known_public")
        self.assertEqual(report["freshestReference"]["source"], "public")

    def test_allows_candidate_newer_than_known_public(self):
        candidate = guard.feed_fingerprint(
            feed("2026-06-09T17:00:00+03:00", "2026-06-09T17:00:00+03:00"),
            source="candidate",
        )
        public = guard.feed_fingerprint(
            feed("2026-06-09T16:00:00+03:00", "2026-06-09T16:00:00+03:00"),
            source="public",
        )

        report = guard.compare_candidate(candidate, [public])

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["reason"], "candidate_not_older_than_known_public")

    def test_state_fingerprint_participates_in_rollback_detection(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "last.json"
            state.write_text(json.dumps({
                "freshest": {
                    "source": "previous-good-deploy",
                    "updatedAt": "2026-06-09T16:00:00+03:00",
                    "topPublishedAt": "2026-06-09T16:00:00+03:00",
                    "itemCount": 100,
                }
            }), encoding="utf-8")

            loaded = guard.load_state(state)

        candidate = guard.feed_fingerprint(
            feed("2026-06-09T15:00:00+03:00", "2026-06-09T15:00:00+03:00"),
            source="candidate",
        )
        report = guard.compare_candidate(candidate, [loaded])

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["freshestReference"]["source"], "previous-good-deploy")


if __name__ == "__main__":
    unittest.main()
