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

    def test_stage2_executes_only_safe_deploy_and_verifies_public(self):
        calls = []

        def fake_run(cmd, timeout=120):
            calls.append(cmd)
            return 0, "deployed"

        def fake_collect():
            return autopilot.HealthSnapshot(
                public_health={"status": "ok", "blockers": []},
                live={"status": "ok", "errors": [], "warnings": []},
                timing={"status": "ok", "errors": [], "warnings": []},
                raw_health={"status": "ok", "blockers": []},
                local_health={"status": "ok", "blockers": []},
                local_quality={"exit": 0, "summary": "Pointa quality gate: 11 items, 0 errors"},
                feed_signature={"updatedAt": "new", "items": 11, "topHeadline": "חדש"},
            )

        incident = {
            "status": "repair_needed",
            "incidentType": "deploy_public_stale_local_candidate_healthy",
            "recommendedStage": "stage_2_safe_deploy",
            "automaticAction": "deploy_current_feed_then_verify_public",
            "incidentKey": "deploy-needed",
        }

        actions, post_incident = autopilot.execute_stage2_repair(incident, run_func=fake_run, collect_func=fake_collect)

        self.assertEqual(calls, [["bash", "scripts/deploy_current_feed.sh"]])
        self.assertEqual(actions[0]["action"], "deploy_current_feed")
        self.assertEqual(actions[0]["exit"], 0)
        self.assertEqual(actions[1]["action"], "verify_public_after_deploy")
        self.assertEqual(post_incident["status"], "ok")
        self.assertEqual(post_incident["incidentType"], "healthy")

    def test_stage2_refuses_general_rescue_or_quality_blocked_actions(self):
        calls = []

        def fake_run(cmd, timeout=120):
            calls.append(cmd)
            return 0, "should not run"

        incident = {
            "status": "repair_needed",
            "incidentType": "top_feed_stale_or_thin",
            "recommendedStage": "stage_3_general_rescue",
            "automaticAction": "prepare_general_rescue_worker",
            "incidentKey": "stale",
        }

        actions, post_incident = autopilot.execute_stage2_repair(incident, run_func=fake_run, collect_func=lambda: None)

        self.assertEqual(calls, [])
        self.assertEqual(actions, [])
        self.assertIs(post_incident, incident)

    def test_auto_repair_report_marks_deploy_only_after_execution(self):
        incident = {
            "status": "repair_needed",
            "incidentType": "deploy_public_stale_local_candidate_healthy",
            "recommendedStage": "stage_2_safe_deploy",
            "automaticAction": "deploy_current_feed_then_verify_public",
            "incidentKey": "deploy-needed",
        }
        report = autopilot.build_report(
            mode="auto-repair",
            snapshot={"publicHealth": {"status": "fail"}},
            incident=incident,
            state={"currentIncidentRepeatCount": 1},
            started_at="2026-05-25T10:00:00+03:00",
            executed_actions=[{"action": "deploy_current_feed", "exit": 0}],
        )

        self.assertEqual(report["executedActions"][0]["action"], "deploy_current_feed")
        self.assertTrue(report["deploys"])
        self.assertFalse(report["mutatesFeed"])

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

    def test_stage3_prepares_worker_but_does_not_apply_without_editor_results(self):
        calls = []
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "tmp" / "editor-runs" / "autopilot-test"
            lock_path = Path(td) / "stage3.lock"

            def fake_run(cmd, timeout=120):
                calls.append(cmd)
                if any("pointa_rescue_editor_pipeline.py" in part for part in cmd):
                    run_dir.mkdir(parents=True, exist_ok=True)
                    return 0, str(run_dir) + "\n{}"
                return 0, "queue ok"

            incident = {
                "status": "repair_needed",
                "incidentType": "top_feed_stale_or_thin",
                "recommendedStage": "stage_3_general_rescue",
                "automaticAction": "prepare_general_rescue_worker",
                "incidentKey": "stale-1",
            }
            actions, post_incident, state = autopilot.execute_stage3_repair(
                incident, {}, now="2026-05-25T10:00:00+03:00", run_func=fake_run, lock_path=lock_path
            )

        self.assertEqual(actions[0]["action"], "stage3_prepare_source_rescue_queue")
        self.assertEqual(actions[1]["action"], "stage3_prepare_editor_run")
        self.assertEqual(actions[2]["action"], "stage3_wait_for_editor_results")
        self.assertEqual(post_incident["incidentType"], "stage3_waiting_for_editor_results")
        self.assertEqual(state["lastStage3IncidentKey"], "stale-1")
        self.assertFalse(any("pointa_editor_pipeline.py" in cmd for cmd in calls))
        self.assertFalse(any("deploy_current_feed.sh" in cmd for cmd in calls))

    def test_stage3_respects_cooldown_for_same_incident(self):
        incident = {
            "status": "repair_needed",
            "incidentType": "top_feed_stale_or_thin",
            "recommendedStage": "stage_3_general_rescue",
            "automaticAction": "prepare_general_rescue_worker",
            "incidentKey": "same",
        }
        state = {"lastStage3StartedAt": "2026-05-25T10:00:00+03:00", "lastStage3IncidentKey": "same"}
        actions, post_incident, _ = autopilot.execute_stage3_repair(
            incident, state, now="2026-05-25T10:05:00+03:00", run_func=lambda *a, **k: self.fail("must not run")
        )

        self.assertEqual(actions, [{"action": "stage3_skip_cooldown", "cooldownMinutes": autopilot.STAGE3_COOLDOWN_MINUTES}])
        self.assertEqual(post_incident["incidentType"], "stage3_cooldown_active")

    def test_stage3_full_path_applies_only_after_gates_then_deploys(self):
        calls = []
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            run_dir = base / "tmp" / "editor-runs" / "autopilot-ready"
            run_dir.mkdir(parents=True)
            (run_dir / "batch_1_results.json").write_text("[]", encoding="utf-8")
            lock_path = base / "stage3.lock"

            def fake_run(cmd, timeout=120):
                calls.append(cmd)
                if any("pointa_rescue_editor_pipeline.py" in part for part in cmd):
                    return 0, str(run_dir) + "\n{}"
                return 0, "ok"

            def fake_collect():
                return autopilot.HealthSnapshot(
                    public_health={"status": "ok", "blockers": []},
                    live={"status": "ok", "errors": [], "warnings": []},
                    timing={"status": "ok", "errors": [], "warnings": []},
                    raw_health={"status": "ok", "blockers": []},
                    local_health={"status": "ok", "blockers": []},
                    local_quality={"exit": 0, "summary": "Pointa quality gate: 12 items, 0 errors"},
                    feed_signature={"updatedAt": "new", "items": 12, "topHeadline": "חדש"},
                )

            incident = {
                "status": "repair_needed",
                "incidentType": "top_feed_stale_or_thin",
                "recommendedStage": "stage_3_general_rescue",
                "automaticAction": "prepare_general_rescue_worker",
                "incidentKey": "stale-ready",
            }
            actions, post_incident, _ = autopilot.execute_stage3_repair(
                incident, {}, now="2026-05-25T10:00:00+03:00", run_func=fake_run, collect_func=fake_collect, lock_path=lock_path
            )

        action_names = [a["action"] for a in actions]
        self.assertIn("stage3_qa_editor_results", action_names)
        self.assertIn("stage3_apply_editor_preview", action_names)
        self.assertIn("stage3_quality_gate", action_names)
        self.assertIn("stage3_deploy_current_feed", action_names)
        self.assertEqual(post_incident["status"], "ok")
        self.assertEqual(calls[-1], ["bash", "scripts/deploy_current_feed.sh"])

    def test_stage3_report_marks_mutation_and_deploy_after_execution(self):
        report = autopilot.build_report(
            mode="auto-repair",
            snapshot={"publicHealth": {"status": "fail"}},
            incident={"status": "ok", "incidentType": "healthy", "automaticAction": "none"},
            state={"currentIncidentRepeatCount": 1},
            started_at="2026-05-25T10:00:00+03:00",
            executed_actions=[
                {"action": "stage3_apply_editor_preview", "exit": 0},
                {"action": "stage3_deploy_current_feed", "exit": 0},
            ],
        )

        self.assertTrue(report["mutatesFeed"])
        self.assertTrue(report["deploys"])
        self.assertEqual(report["version"], 3)


if __name__ == "__main__":
    unittest.main()
