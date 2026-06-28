#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pointa_publication_health_gate as gate  # noqa: E402


class PointaPublicationHealthGateTests(unittest.TestCase):
    def test_strict_freshness_turns_live_status_errors_into_blockers(self):
        live = {
            "errors": [
                {"code": "stale_updated_at", "message": "live feed is stale"},
                {"code": "no_new_top_item_sla", "message": "top item is old"},
            ],
            "warnings": [],
        }

        blockers, freshness = gate.split_live_findings(live, mode="candidate", strict_freshness=True)

        self.assertEqual([b["code"] for b in blockers], ["stale_updated_at", "no_new_top_item_sla"])
        self.assertTrue(all(row["publicationPolicy"] == "freshness_blocks_publication" for row in freshness))

    def test_default_candidate_keeps_freshness_as_signal_only(self):
        live = {"errors": [{"code": "stale_updated_at", "message": "live feed is stale"}], "warnings": []}

        blockers, freshness = gate.split_live_findings(live, mode="candidate", strict_freshness=False)

        self.assertEqual(blockers, [])
        self.assertEqual(freshness[0]["publicationPolicy"], "freshness_monitoring_only")


if __name__ == "__main__":
    unittest.main()
