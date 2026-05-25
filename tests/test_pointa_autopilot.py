#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pointa_autopilot as autopilot  # noqa: E402


class PointaAutopilotTests(unittest.TestCase):
    def test_classifies_healthy_public_feed_as_ok(self):
        snapshot = autopilot.HealthSnapshot(
            public_health={"status": "ok", "blockers": []},
            live={"status": "ok", "errors": [], "warnings": []},
            timing={"status": "ok", "errors": [], "warnings": []},
            raw_health={"status": "ok", "blockers": []},
            local_health={"status": "ok", "blockers": []},
            local_quality={"exit": 0, "summary": "Pointa quality gate: 10 items, 0 errors"},
            feed_signature={"updatedAt": "2026-05-25T15:36:00+03:00", "items": 10, "topHeadline": "חדשה"},
        )

        incident = autopilot.classify_incident(snapshot)

        self.assertEqual(incident["status"], "ok")
        self.assertEqual(incident["incidentType"], "healthy")
        self.assertEqual(incident["recommendedStage"], "none")
        self.assertEqual(incident["automaticAction"], "none")

    def test_classifies_pages_lag_when_public_fails_but_raw_is_ok(self):
        snapshot = autopilot.HealthSnapshot(
            public_health={"status": "fail", "blockers": [{"code": "stale_updated_at"}]},
            live={"status": "fail", "errors": [{"code": "stale_updated_at"}], "warnings": []},
            timing={"status": "ok", "errors": [], "warnings": []},
            raw_health={"status": "ok", "blockers": []},
            local_health={"status": "ok", "blockers": []},
            local_quality={"exit": 0, "summary": "Pointa quality gate: 10 items, 0 errors"},
            feed_signature={"updatedAt": "old", "items": 10, "topHeadline": "ישן"},
        )

        incident = autopilot.classify_incident(snapshot)

        self.assertEqual(incident["status"], "degraded")
        self.assertEqual(incident["incidentType"], "github_pages_propagation_lag")
        self.assertEqual(incident["recommendedStage"], "wait_and_reverify")
        self.assertEqual(incident["automaticAction"], "verify_public_again")

    def test_classifies_safe_deploy_when_local_ok_and_public_stale(self):
        snapshot = autopilot.HealthSnapshot(
            public_health={"status": "fail", "blockers": [{"code": "no_new_top_item_sla"}]},
            live={"status": "fail", "errors": [{"code": "no_new_top_item_sla"}], "warnings": []},
            timing={"status": "fail", "errors": [{"group": "all", "code": "publication_timing_sla"}], "warnings": []},
            raw_health={"status": "fail", "blockers": [{"code": "no_new_top_item_sla"}]},
            local_health={"status": "ok", "blockers": []},
            local_quality={"exit": 0, "summary": "Pointa quality gate: 11 items, 0 errors"},
            feed_signature={"updatedAt": "old", "items": 10, "topHeadline": "ישן"},
            local_signature={"updatedAt": "new", "items": 11, "topHeadline": "חדש"},
        )

        incident = autopilot.classify_incident(snapshot)

        self.assertEqual(incident["status"], "repair_needed")
        self.assertEqual(incident["incidentType"], "deploy_public_stale_local_candidate_healthy")
        self.assertEqual(incident["recommendedStage"], "stage_2_safe_deploy")
        self.assertEqual(incident["automaticAction"], "deploy_current_feed_then_verify_public")

    def test_classifies_general_rescue_when_public_and_local_are_stale(self):
        snapshot = autopilot.HealthSnapshot(
            public_health={"status": "fail", "blockers": [{"code": "stale_updated_at"}, {"code": "no_new_top_item_sla"}]},
            live={"status": "fail", "errors": [{"code": "stale_updated_at"}, {"code": "no_new_top_item_sla"}], "warnings": []},
            timing={"status": "fail", "errors": [{"group": "all", "code": "publication_timing_sla"}], "warnings": []},
            raw_health={"status": "fail", "blockers": [{"code": "stale_updated_at"}]},
            local_health={"status": "fail", "blockers": [{"code": "stale_updated_at"}]},
            local_quality={"exit": 0, "summary": "Pointa quality gate: 10 items, 0 errors"},
            feed_signature={"updatedAt": "old", "items": 10, "topHeadline": "ישן"},
        )

        incident = autopilot.classify_incident(snapshot)

        self.assertEqual(incident["status"], "repair_needed")
        self.assertEqual(incident["incidentType"], "top_feed_stale_or_thin")
        self.assertEqual(incident["recommendedStage"], "stage_3_general_rescue")
        self.assertEqual(incident["automaticAction"], "prepare_general_rescue_worker")

    def test_classifies_quality_blocked_when_local_quality_has_errors(self):
        snapshot = autopilot.HealthSnapshot(
            public_health={"status": "fail", "blockers": [{"code": "stale_updated_at"}]},
            live={"status": "fail", "errors": [{"code": "stale_updated_at"}], "warnings": []},
            timing={"status": "fail", "errors": [], "warnings": []},
            raw_health={"status": "fail", "blockers": []},
            local_health={"status": "fail", "blockers": [{"code": "summary_fragment_headline"}]},
            local_quality={"exit": 1, "summary": "Pointa quality gate: 10 items, 2 errors"},
            feed_signature={"updatedAt": "old", "items": 10, "topHeadline": "ישן"},
        )

        incident = autopilot.classify_incident(snapshot)

        self.assertEqual(incident["status"], "blocked")
        self.assertEqual(incident["incidentType"], "local_candidate_quality_blocked")
        self.assertEqual(incident["recommendedStage"], "editor_or_agent_review")
        self.assertEqual(incident["automaticAction"], "do_not_publish")

    def test_updates_state_with_loop_protection(self):
        incident = {
            "incidentKey": "same-problem",
            "incidentType": "top_feed_stale_or_thin",
            "status": "repair_needed",
            "automaticAction": "prepare_general_rescue_worker",
        }

        state1 = autopilot.update_state({}, incident, now="2026-05-25T10:00:00+03:00")
        state2 = autopilot.update_state(state1, incident, now="2026-05-25T10:05:00+03:00")
        state3 = autopilot.update_state(state2, incident, now="2026-05-25T10:10:00+03:00")
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "state.json"
            autopilot.write_json(state_path, state3)
            loaded = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(loaded["currentIncidentKey"], "same-problem")
        self.assertEqual(loaded["currentIncidentRepeatCount"], 3)
        self.assertTrue(loaded["loopProtection"]["active"])
        self.assertEqual(loaded["loopProtection"]["reason"], "same_incident_repeated")

    def test_dry_run_exit_code_is_zero_even_when_repair_is_needed(self):
        incident = {"status": "repair_needed", "incidentType": "top_feed_stale_or_thin"}

        self.assertEqual(autopilot.exit_code_for_mode("dry-run", incident), 0)

    def test_dry_run_report_never_contains_write_or_deploy_action(self):
        incident = {
            "status": "repair_needed",
            "incidentType": "top_feed_stale_or_thin",
            "recommendedStage": "stage_3_general_rescue",
            "automaticAction": "prepare_general_rescue_worker",
            "incidentKey": "k",
        }
        report = autopilot.build_report(
            mode="dry-run",
            snapshot={"publicHealth": {"status": "fail"}},
            incident=incident,
            state={"currentIncidentRepeatCount": 1},
            started_at="2026-05-25T10:00:00+03:00",
        )

        self.assertEqual(report["mode"], "dry-run")
        self.assertEqual(report["wouldRun"], ["prepare_general_rescue_worker"])
        self.assertEqual(report["executedActions"], [])
        self.assertFalse(report["mutatesFeed"])
        self.assertFalse(report["deploys"])


if __name__ == "__main__":
    unittest.main()
