#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run a bounded Pointa feed rescue cycle.

This is the missing bridge between RSS collection and publication: when FAST
sync leaves the feed thin or with weak cards, prepare a small rescue editor run,
write conservative deterministic results, QA them, and apply only if the normal
editor gates pass.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "tmp"
TZ = timezone(timedelta(hours=3))
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from pointa_silent_freshness_sentinel import run_codex_rescue_editor  # type: ignore  # noqa: E402
except ImportError:
    def run_codex_rescue_editor(run_dir: Path) -> dict[str, Any]:
        return {
            "ok": False,
            "reason": "codex_rescue_editor_function_unavailable",
            "runDir": str(run_dir),
        }


def run(cmd: list[str], *, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, env={**os.environ, **(env or {})})
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def run_json(cmd: list[str], *, env: dict[str, str] | None = None, check: bool = True) -> dict[str, Any]:
    proc = run(cmd, env=env, check=check)
    out = proc.stdout.strip()
    if not out:
        if check:
            raise RuntimeError(f"command produced no JSON: {' '.join(cmd)}")
        return {}
    return json.loads(out)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def latest_editor_run_from_prepare(stdout: str) -> Path:
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith(str(ROOT / "tmp" / "editor-runs")):
            return Path(line)
    raise RuntimeError("prepare did not print an editor run directory")


def count_recent_top(feed_path: Path, minutes: int = 60, top_n: int = 12) -> int:
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    cutoff = datetime.now(TZ) - timedelta(minutes=minutes)
    count = 0
    for item in (feed.get("items") or [])[:top_n]:
        try:
            dt = datetime.fromisoformat(str(item.get("publishedAt") or "").replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ)
            if dt.astimezone(TZ) >= cutoff:
                count += 1
        except Exception:
            continue
    return count


def needs_rescue(feed: Path, health_out: Path) -> tuple[bool, dict[str, Any]]:
    live = run_json([sys.executable, "scripts/pointa_live_auditor.py", "--feed-file", str(feed), "--json"], check=False)
    write_json(TMP / "pointa_live_auditor_last.json", live)
    gate = run_json([
        sys.executable,
        "scripts/pointa_publication_health_gate.py",
        "--mode",
        "candidate",
        "--feed",
        str(feed),
        "--out",
        str(health_out.relative_to(ROOT)),
        "--json",
    ], check=False)
    signal_codes = {str(x.get("code") or "") for x in gate.get("freshnessSignals") or []}
    error_codes = {str(x.get("code") or "") for x in gate.get("liveErrors") or []}
    rescue_codes = {
        "no_new_top_item_sla",
        "stale_top_item",
        "too_few_recent_items_sla",
        "too_few_recent_sources_sla",
        "summary_fragment_headline",
        "headline_too_close_to_source",
    }
    return bool((signal_codes | error_codes) & rescue_codes), gate


HARD_FRESHNESS_CODES = {
    "no_new_top_item_sla",
    "stale_top_item",
    "too_few_fresh_top_items",
    "too_few_recent_items_sla",
    "too_few_recent_sources_sla",
}


def hard_freshness_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for key in ("blockers", "liveErrors", "freshnessSignals"):
        for item in report.get(key) or []:
            if item.get("code") in HARD_FRESHNESS_CODES:
                findings.append(dict(item))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--feed", default="feed.json")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--batch-size", type=int, default=5)
    ap.add_argument("--oversample-factor", type=int, default=2)
    ap.add_argument("--min-pass", type=int, default=1)
    ap.add_argument("--min-article-chars", type=int, default=300)
    ap.add_argument("--max-age-min", type=int, default=180)
    ap.add_argument("--per-source", type=int, default=6)
    ap.add_argument("--force", action="store_true", help="Run even if candidate health does not currently ask for rescue")
    ap.add_argument("--require-freshness", action="store_true", help="Fail and roll back when the edited feed still misses active-hours freshness SLA")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    feed = Path(args.feed)
    if not feed.is_absolute():
        feed = ROOT / feed
    run_id = "rescue-autopilot-" + datetime.now(TZ).strftime("%Y%m%dT%H%M%S%z")
    summary_path = TMP / "pointa_feed_rescue_autopilot_last.json"
    health_before_path = TMP / "rescue_autopilot_health_before.json"
    health_after_path = TMP / "rescue_autopilot_health_after.json"

    try:
        recent_top12_before = count_recent_top(feed, 60, 12)
        should_run, health_before = needs_rescue(feed, health_before_path)
        if not should_run and not args.force:
            summary = {
                "status": "skip",
                "reason": "candidate_feed_does_not_need_rescue",
                "runId": run_id,
                "healthBefore": health_before,
            }
            write_json(summary_path, summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0

        queue_proc = run([
            sys.executable,
            "scripts/pointa_source_rescue_queue.py",
            "--sync-profile",
            "fast",
            "--max-age-min",
            str(args.max_age_min),
            "--per-source",
            str(args.per_source),
            "--out",
            "tmp/pointa_source_rescue_queue.json",
        ])
        queue_report = json.loads(queue_proc.stdout.strip() or "{}")

        editor_env = {
            "POINTA_EDITOR_ARTICLE_FETCH_TIMEOUT": "5",
            "POINTA_EDITOR_JINA_FETCH_TIMEOUT": "6",
            "POINTA_EDITOR_JINA_MAX_ATTEMPTS": "1",
        }
        prepare_proc = run([
            sys.executable,
            "scripts/pointa_rescue_editor_pipeline.py",
            "prepare",
            "--limit",
            str(args.limit),
            "--batch-size",
            str(args.batch_size),
            "--oversample-factor",
            str(args.oversample_factor),
            "--min-article-chars",
            str(args.min_article_chars),
            "--run-id",
            run_id,
        ], env=editor_env)
        run_dir = latest_editor_run_from_prepare(prepare_proc.stdout)

        editor_source = os.environ.get("POINTA_RESCUE_EDITOR_SOURCE", "codex").strip().lower()
        editor_result: dict[str, Any]
        if editor_source == "codex":
            editor_result = run_codex_rescue_editor(run_dir)
            if not editor_result.get("ok"):
                if os.environ.get("POINTA_ALLOW_LOCAL_FALLBACK") == "1":
                    editor_result = {
                        "codex": editor_result,
                        "fallback": run_json([
                            sys.executable,
                            "scripts/pointa_deterministic_rescue_editor.py",
                            "--run-dir",
                            str(run_dir),
                            "--overwrite",
                            "--json",
                        ], check=False),
                    }
                else:
                    summary = {
                        "status": "fail",
                        "reason": "codex_rescue_editor_failed",
                        "runId": run_id,
                        "queue": queue_report,
                        "runDir": str(run_dir),
                        "editor": editor_result,
                    }
                    write_json(summary_path, summary)
                    print(json.dumps(summary, ensure_ascii=False, indent=2))
                    return 3
        elif editor_source == "deterministic":
            editor_result = run_json([
                sys.executable,
                "scripts/pointa_deterministic_rescue_editor.py",
                "--run-dir",
                str(run_dir),
                "--overwrite",
                "--json",
            ], check=False)
        else:
            summary = {"status": "fail", "reason": "unknown_editor_source", "runId": run_id, "editorSource": editor_source}
            write_json(summary_path, summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 3

        qa = run_json([
            sys.executable,
            "scripts/pointa_editor_pipeline.py",
            "qa",
            "--run-dir",
            str(run_dir),
            "--feed",
            str(feed),
            "--auto-reject-failed",
        ], check=False)
        if int(qa.get("pass", 0)) < args.min_pass:
            summary = {
                "status": "fail",
                "reason": "not_enough_safe_editor_passes",
                "runId": run_id,
                "queue": queue_report,
                "runDir": str(run_dir),
                "editor": editor_result,
                "qa": qa,
            }
            write_json(summary_path, summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 3
        if int(qa.get("qaFailures", 1)) != 0:
            summary = {"status": "fail", "reason": "editor_qa_failed", "runId": run_id, "runDir": str(run_dir), "qa": qa}
            write_json(summary_path, summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 4

        feed_before_apply = feed.read_text(encoding="utf-8") if feed.exists() else ""
        apply_proc = run([
            sys.executable,
            "scripts/pointa_editor_pipeline.py",
            "apply",
            "--run-dir",
            str(run_dir),
            "--feed",
            str(feed),
        ])
        quality = run([
            sys.executable,
            "scripts/pointa_quality_gate.py",
            "--report",
            "pointa_quality_report.md",
        ], check=False)
        if quality.returncode != 0:
            if feed_before_apply:
                feed.write_text(feed_before_apply, encoding="utf-8")
            summary = {
                "status": "fail",
                "reason": "post_apply_quality_gate_failed_rolled_back",
                "runId": run_id,
                "runDir": str(run_dir),
                "qualityStdout": quality.stdout,
                "qualityStderr": quality.stderr,
            }
            write_json(summary_path, summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 5
        health_after = run_json([
            sys.executable,
            "scripts/pointa_publication_health_gate.py",
            "--mode",
            "candidate",
            "--feed",
            str(feed),
            "--out",
            str(health_after_path.relative_to(ROOT)),
            "--json",
            *(["--strict-freshness"] if args.require_freshness else []),
        ], check=False)
        freshness_blockers = hard_freshness_findings(health_after) if args.require_freshness else []
        if health_after.get("status") == "fail" or freshness_blockers:
            if feed_before_apply:
                feed.write_text(feed_before_apply, encoding="utf-8")
            summary = {
                "status": "fail",
                "reason": "post_apply_freshness_sla_failed_rolled_back" if freshness_blockers else "post_apply_publication_health_blocker_rolled_back",
                "runId": run_id,
                "runDir": str(run_dir),
                "healthAfter": health_after,
                "freshnessBlockers": freshness_blockers,
                "recentTop12Before": recent_top12_before,
                "recentTop12After": count_recent_top(feed, 60, 12),
            }
            write_json(summary_path, summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 6

        summary = {
            "status": "ok",
            "runId": run_id,
            "runDir": str(run_dir),
            "queue": queue_report,
            "editor": editor_result,
            "qa": qa,
            "apply": apply_proc.stdout.strip(),
            "quality": quality.stdout.strip(),
            "recentTop12Before": recent_top12_before,
            "recentTop12After": count_recent_top(feed, 60, 12),
            "healthBefore": health_before,
            "healthAfter": health_after,
        }
        write_json(summary_path, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        summary = {"status": "fail", "runId": run_id, "error": str(exc)}
        write_json(summary_path, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
