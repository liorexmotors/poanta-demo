#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Poanta agent training camp / מחנה אימונים לסוכנים.

Creates and grades synthetic adversarial drills for every active Poanta agent.
The drills are intentionally fake but realistic: they are designed to catch the
failure classes Lior flagged before they reach the live feed.

Default mode writes:
- tmp/agent-training/poanta_agent_training_cases.json
- tmp/agent-training/poanta_agent_training_gold_answers.json
- tmp/agent-training/poanta_agent_training_report.json

The gold answers are a contract: any agent implementation/prompt change should
be compared against these expected decisions and must score 100/100 before it is
trusted for the matching responsibility.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "tmp" / "agent-training"
CASES_PATH = OUT_DIR / "poanta_agent_training_cases.json"
GOLD_PATH = OUT_DIR / "poanta_agent_training_gold_answers.json"
REPORT_PATH = OUT_DIR / "poanta_agent_training_report.json"

AGENTS = ["collector", "editor", "gatekeeper", "auditor", "repairer"]
AGENT_HE = {
    "collector": "האספן",
    "editor": "העורך",
    "gatekeeper": "השוער",
    "auditor": "המבקר",
    "repairer": "המתקן",
}


def case(case_id: str, agent: str, title: str, trap: str, payload: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": case_id,
        "agent": agent,
        "agentHebrew": AGENT_HE[agent],
        "title": title,
        "trap": trap,
        "payload": payload,
        "expected": expected,
    }


def build_collector_cases() -> list[dict[str, Any]]:
    traps = [
        ("fresh_security_rejected_by_deterministic", "Fresh important security item fails deterministic QA", "route_to_editor_rescue"),
        ("old_dead_run_blocks_fast", "Incomplete FAST run is 3 hours old", "abandon_stale_run_and_continue"),
        ("recent_run_incomplete", "Incomplete FAST run is 8 minutes old", "wait_do_not_start_duplicate"),
        ("duplicate_url_new_title", "Same URL appears with slightly different title", "dedupe_keep_best"),
        ("foreign_unrelated_world", "BBC story about US weather with no Israel/Middle East angle", "reject_foreign_irrelevant"),
        ("foreign_relevant_iran", "Reuters story about Iran sanctions and Israel implications", "accept_foreign_relevant"),
        ("important_source_no_items", "ynet feed temporarily returns empty", "log_fetch_issue_continue_others"),
        ("article_date_missing", "RSS item has no publishedAt but article has source date", "extract_source_date"),
        ("evergreen_lifestyle_fast", "Lifestyle evergreen item appears in FAST source", "demote_or_reject_from_fast"),
        ("weather_card_sticky", "Daily weather card would sort above news", "do_not_pin_above_fresh_news"),
        ("thin_title_only", "Candidate has title only, no URL text", "send_to_editor_only_if_extractable_else_reject"),
        ("paywall_short_article", "Haaretz text extraction is short", "keep_candidate_but_mark_text_thin"),
        ("source_group_mismatch", "Google News URL wraps CNN story", "canonicalize_source_identity"),
        ("stale_seen_state", "New article suppressed by stale seen title similarity", "prefer_url_and_time_over_title_similarity"),
        ("breaking_mivzak", "Short ynet breaking update about security incident", "accept_with_mivzak_profile"),
        ("sports_noise", "Sports transfer rumor in FAST", "reject_or_slow_profile"),
        ("economy_fast_relevant", "Major market/company report from Globes", "accept_fast_if_recent_important"),
        ("rss_timeout_one_source", "One source times out", "continue_and_report_source_error"),
        ("same_story_many_sources", "Same Knesset vote appears in 5 feeds", "cluster_duplicate_story"),
        ("manual_correction_overwrite", "Fresh sync would overwrite manually repaired card", "preserve_known_correction"),
        ("bad_image_logo", "Foreign card image is Google generic logo", "use_source_identity_image"),
        ("future_timestamp", "RSS item timestamp is in the future", "normalize_or_quarantine"),
        ("low_quality_source", "Unknown scraper source with copied content", "quarantine_source"),
        ("rescue_queue_large", "100 fresh rejected items exist", "prioritize_important_recent_rescue"),
        ("no_new_candidates", "No genuinely new items", "do_not_recycle_old_articles"),
    ]
    return [case(f"collector-{i:02d}", "collector", t, d, {"syntheticArticle": t, "source": "training"}, {"decision": exp}) for i, (t, d, exp) in enumerate(traps, 1)]


def build_editor_cases() -> list[dict[str, Any]]:
    traps = [
        ("source_title_copy", "Headline copies source", "reject_or_rewrite"),
        ("generic_takeaway", "Takeaway fits any article", "reject_or_rewrite"),
        ("summary_mediation", "Summary starts with 'הכתבה עוסקת'", "reject_or_rewrite"),
        ("sensational_detail", "Nudity/quote hides broader festival story", "broader_frame"),
        ("stolen_weapon_restaurant", "Restaurant debt story is actually stolen IDF weapon", "security_frame"),
        ("quote_title", "Source title is only a quote", "event_headline"),
        ("ellipsis_headline", "Headline visibly truncated", "rewrite_complete_short"),
        ("thin_article", "Article text has 80 chars only", "reject"),
        ("foreign_relevance_uncertain", "Foreign item weakly mentions Israel", "reject_if_uncertain"),
        ("mivzak_short_but_clear", "Short breaking update has enough facts", "pass_concise"),
        ("finance_not_food", "Airline loss story accidentally gets food takeaway", "finance_takeaway"),
        ("health_claim", "Medical claim lacks evidence", "avoid_overclaim"),
        ("legal_suspect", "Suspect not convicted", "use_alleged_or_expected_charge"),
        ("duplicate_story", "Two sources same event", "distinct_or_reject_duplicate"),
        ("category_confusion", "Political coalition story classified as lifestyle", "correct_category"),
        ("source_mistaken_as_subject", "CNN/Reuters becomes story subject", "event_not_source"),
        ("opinion_piece", "Opinion article treated as fact", "label_as_opinion_or_reject"),
        ("old_background", "Backgrounder presented as new", "reject_or_contextualize"),
        ("missing_actor", "Headline lacks who did what", "add_actor_action"),
        ("too_long_headline", "Headline over 75 chars", "compress"),
        ("reusable_security_takeaway", "'This changes the security picture'", "specific_takeaway"),
        ("consumer_tip_generic", "'Check before buying' generic", "specific_consumer_point"),
        ("multiple_claims", "Article has several claims; choose real lead", "lead_mechanism"),
        ("image_misleads", "Image suggests wrong person/source", "do_not_infer_from_image"),
        ("article_contradicts_title", "Body contradicts RSS title", "trust_article_text"),
    ]
    return [case(f"editor-{i:02d}", "editor", t, d, {"articleText": f"Synthetic adversarial article for {t}", "sourceTitle": t}, {"decision": exp, "mustScore": 100}) for i, (t, d, exp) in enumerate(traps, 1)]


def build_gatekeeper_cases() -> list[dict[str, Any]]:
    traps = [
        ("qa_error_present", "QA has 1 error", "block_publish"),
        ("qa_warnings_only", "Warnings only, no errors", "allow_with_log"),
        ("missing_batch_results", "One batch result file missing", "block_incomplete_run"),
        ("stale_run_newer_feed", "Run would overwrite newer live feed", "block_stale_apply"),
        ("preview_has_rejects", "Preview excludes rejects correctly", "allow_if_qg_zero"),
        ("build_failure", "npm build fails", "block_publish"),
        ("git_push_failed", "Git auth failure", "escalate_access_blocker"),
        ("live_raw_mismatch", "raw gh-pages differs from GitHub Pages", "wait_then_verify_or_escalate"),
        ("manual_fix_not_in_preview", "Known correction missing from preview", "block_overwrite"),
        ("weather_top", "Weather card sorted above breaking news", "block_or_reorder"),
        ("zero_items", "Feed has 0 items", "block_publish"),
        ("bad_json", "feed.json invalid", "block_publish"),
        ("foreign_irrelevant_in_preview", "Foreign unrelated item in preview", "block_publish"),
        ("source_logo_missing", "Foreign logo missing", "warn_not_block"),
        ("duplicate_cluster", "Duplicate story cluster found", "warn_or_dedupe_before_publish"),
        ("old_top_item", "Top item older than freshness max", "trigger_repair_not_publish_old"),
        ("results_index_mismatch", "Editor result indices do not match input", "block_publish"),
        ("unknown_category", "Unknown category returned", "block_or_normalize_if_safe"),
        ("category_class_mismatch", "CategoryClass mismatch", "normalize_then_qa"),
        ("editor_reject_reason_missing", "Reject lacks reason", "block_or_auto_reject_invalid"),
        ("rescue_manual_card", "Manual rescue card passes QG", "allow_feed_only"),
        ("uncertain_rescue_card", "Manual rescue card has weak source", "block_ask"),
        ("deploy_without_approval_ui", "UI code changed with feed", "block_release_ask"),
        ("feed_only_autonomy", "Feed-only deterministic QG 0 repair", "allow_under_option_2"),
        ("repeated_agent_failure", "Same failure class repeats", "block_and_add_guard"),
    ]
    return [case(f"gatekeeper-{i:02d}", "gatekeeper", t, d, {"qaErrors": 0, "syntheticRun": t}, {"decision": exp}) for i, (t, d, exp) in enumerate(traps, 1)]


def build_auditor_cases() -> list[dict[str, Any]]:
    traps = [
        ("feed_updated_but_source_stale", "Overall feed fresh; Haaretz view stale", "trigger_one_repair_attempt"),
        ("top_old", "Top item older than 2h", "trigger_fast_sync"),
        ("foreign_view_stale", "World tab stale", "trigger_rescue_or_escalate"),
        ("bad_takeaway_live", "Live card has generic takeaway", "flag_and_repair_if_known"),
        ("headline_copy_live", "Live headline copied from source", "flag_quality_error"),
        ("known_bad_phrase", "Known bad phrase reappears", "repair_and_add_guard"),
        ("duplicate_story_live", "Same story twice in top feed", "warn_or_repair_cluster"),
        ("github_pages_cache", "raw fresh but pages stale", "wait_verify_then_escalate"),
        ("fast_sync_failed", "FAST script fails with QA error", "escalate_decision"),
        ("rescue_queue_exists", "Fresh rejected candidates exist", "prepare_rescue_batches"),
        ("after_one_repair_still_stale", "Still stale after one safe attempt", "ask_lior_decision"),
        ("auth_block", "GitHub token blocked", "ask_lior_access"),
        ("false_positive_warning", "Non-blocking warning only", "log_quietly"),
        ("zero_items_live", "Live feed empty", "urgent_blocker"),
        ("bad_json_live", "Live feed invalid JSON", "urgent_blocker"),
        ("weather_stuck_top", "Weather card stuck top", "safe_repair"),
        ("manual_correction_overwritten", "Corrected card overwritten", "restore_known_fix"),
        ("source_selector_confusing", "UI source list stale", "warn_not_feed_repair"),
        ("telegram_noise", "Many routine errors", "do_not_spam_lior"),
        ("decision_needed", "Policy/source relevance uncertain", "ask_with_two_options"),
        ("rescue_prepared_not_applied", "Rescue batches ready but not edited", "log_or_assign_editor"),
        ("cron_disabled", "Finalizer disabled", "escalate_if_blocks_freshness"),
        ("stale_runs", "Old incomplete editor runs", "abandon_stale_runs"),
        ("quality_gate_disagreement", "Auditor fail but QG pass", "treat_as_product_failure"),
        ("no_alert_on_failure", "Auditor silently logs persistent failure", "fail_training"),
    ]
    return [case(f"auditor-{i:02d}", "auditor", t, d, {"liveFeedState": t}, {"decision": exp}) for i, (t, d, exp) in enumerate(traps, 1)]


def build_repairer_cases() -> list[dict[str, Any]]:
    traps = [
        ("safe_feed_refresh", "FAST refresh QG 0", "deploy_feed_only"),
        ("qa_error_after_fix", "Repair produces QA error", "rollback_or_block"),
        ("editorial_uncertainty", "Needs new editorial judgment", "ask_not_invent"),
        ("known_correction", "Restore previously approved correction", "apply_and_test"),
        ("foreign_irrelevant_remove", "Remove obvious unrelated world item", "safe_remove_qg_build"),
        ("mass_delete", "Would delete many items", "ask_lior"),
        ("secret_missing", "Git token missing", "ask_access"),
        ("network_transient", "Source timeout", "retry_later_no_noise"),
        ("build_then_deploy", "Must build before deploy", "run_build_then_deploy"),
        ("auditor_rerun", "Repair done but auditor not rerun", "fail_until_rerun"),
        ("rescue_prepare", "Prepare rescue batches", "prepare_only_no_publish"),
        ("rescue_apply_uncertain", "Rescue result uncertain", "block_ask"),
        ("wrong_branch", "On gh-pages while editing main", "checkout_main"),
        ("dirty_ui_changes", "Feed repair with unrelated UI changes", "do_not_publish_ui_without_approval"),
        ("stale_worktree", "Worktree stale", "fetch_pull_ff_only"),
        ("duplicate_fix", "Dedupe top story", "dedupe_safe_if_same_url_cluster"),
        ("bad_category", "Wrong category from known mapping", "fix_mapping_add_test"),
        ("old_run_abandon", "Incomplete old run", "write_abandoned"),
        ("cron_prompt_weak", "Cron did not specify escalation", "harden_prompt"),
        ("manual_card_too_close", "Manual card too close to source", "rewrite_then_qg"),
        ("deploy_cache", "Pages cache delay", "verify_raw_and_live"),
        ("report_noise", "Fix succeeded", "no_telegram_noise"),
        ("incident_doc", "Severe repeated failure", "write_incident_and_guard"),
        ("rollback_needed", "Bad deploy found", "restore_previous_good_feed"),
        ("one_attempt_failed", "Option 2 repair failed once", "ask_lior_decision"),
    ]
    return [case(f"repairer-{i:02d}", "repairer", t, d, {"repairScenario": t}, {"decision": exp}) for i, (t, d, exp) in enumerate(traps, 1)]


def build_cases() -> list[dict[str, Any]]:
    return build_collector_cases() + build_editor_cases() + build_gatekeeper_cases() + build_auditor_cases() + build_repairer_cases()


def gold_answers(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {c["id"]: {"decision": c["expected"]["decision"], "notes": "gold contract"} for c in cases}


def score(cases: list[dict[str, Any]], answers: dict[str, Any]) -> dict[str, Any]:
    rows = []
    by_agent = {a: {"passed": 0, "total": 0} for a in AGENTS}
    for c in cases:
        cid = c["id"]
        expected = c["expected"]["decision"]
        got = (answers.get(cid) or {}).get("decision")
        ok = got == expected
        rows.append({"id": cid, "agent": c["agent"], "expected": expected, "got": got, "passed": ok})
        by_agent[c["agent"]]["total"] += 1
        by_agent[c["agent"]]["passed"] += 1 if ok else 0
    total = len(rows)
    passed = sum(1 for r in rows if r["passed"])
    for stats in by_agent.values():
        stats["score"] = round(100 * stats["passed"] / max(1, stats["total"]), 2)
    return {
        "name": "Poanta Agent Training Camp",
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "score": round(100 * passed / max(1, total), 2),
        "passed": passed,
        "total": total,
        "byAgent": by_agent,
        "failed": [r for r in rows if not r["passed"]],
        "status": "pass" if passed == total else "fail",
        "requiredScore": 100,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", default="", help="Optional answers JSON to grade. Defaults to generated gold answers.")
    ap.add_argument("--fail-under-100", action="store_true")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = build_cases()
    answers = gold_answers(cases)
    CASES_PATH.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    GOLD_PATH.write_text(json.dumps({"answers": answers}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.answers:
        answers_data = json.loads(Path(args.answers).read_text(encoding="utf-8"))
        answers = answers_data.get("answers", answers_data)

    report = score(cases, answers)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"score": report["score"], "status": report["status"], "total": report["total"], "byAgent": report["byAgent"], "report": str(REPORT_PATH)}, ensure_ascii=False))
    if args.fail_under_100 and report["score"] < 100:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
