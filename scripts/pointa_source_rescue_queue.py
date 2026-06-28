#!/usr/bin/env python3
"""Build a non-blocking rescue queue for fresh important-source candidates.

Purpose: catch cases where a source has fresh RSS items, but deterministic Pointa
rewriting fails QA and the item silently disappears before the full editor sees it.
This script reports only. It does not modify feed.json, publish, or trigger repair.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import update_feed  # type: ignore

TZ = timezone(timedelta(hours=3))
IMPORTANT_SOURCES = ["הארץ", "ynet", "וואלה", "מעריב", "גלובס", "ישראל היום", "דה מרקר", "N12", "Jerusalem Post", "דובר צה״ל", "דוברות משטרת ישראל", "סרוגים", "ערוץ 14", "C14", "ערוץ 7 / INN", "ערוץ 7", "INN", "Israel National News", "כיפה", "בשבע", "מקור ראשון"]
FOREIGN_SOURCES = ["BBC", "CNN", "Sky News", "Reuters", "AP", "Guardian", "NYT", "Axios", "Politico", "Bloomberg", "Al Jazeera"]
GOSSIP_SOURCES = ["Pplus", "TMI", "Daily Mail", "Mirror", "Page Six"]
QUEUE_GROUPS = IMPORTANT_SOURCES + FOREIGN_SOURCES + GOSSIP_SOURCES
DEFAULT_OUT = ROOT / "tmp" / "pointa_source_rescue_queue.json"
DEFAULT_AUDITOR = ROOT / "tmp" / "pointa_live_auditor_last.json"
DEFAULT_DOMAIN_SOURCES = ROOT / "config" / "pointa_domain_sources.json"

EDITORIAL_REPAIR_CODES = {
    "headline_missing", "headline_too_long", "headline_orphan_prefix", "headline_looks_cut",
    "headline_pipe_artifact", "headline_source_style", "headline_generic", "headline_copies_source",
    "headline_duplicates_summary", "headline_is_summary_prefix", "headline_missing_core_entity",
    "summary_missing", "summary_pipe_artifact", "summary_generic_or_mediated",
    "takeaway_missing", "takeaway_generic", "takeaway_topic_mismatch",
    "takeaway_duplicates_context", "takeaway_duplicates_headline",
    "category_iran_deal_security", "category_world_story",
    "opinion_generic_author_reference", "opinion_author_missing",
}

HARD_REJECT_CODES = {
    "html_artifact", "quality_exception",
}

DOMAIN_KEYWORDS = {
    "ביטחון": [
        "צה\"ל", "צה״ל", "צהל", "פיקוד העורף", "חיזבאללה", "חמאס", "איראן", "כטב", "רחפן",
        "טיל", "טילים", "רקטה", "רקטות", "לבנון", "עזה", "צבא", "לוחם", "לוחמים", "מילואים", "טרור", "מחבל",
        "מלחמה", "גבול", "יירוט", "אוויריות חשודות", "כלי טיס עוין", "איום הרחפנים",
    ],
    "פוליטיקה": ["כנסת", "ממשלה", "קואליציה", "אופוזיציה", "בחירות", "נתניהו", "ח״כ", "ח\"כ", "שר ", "שרים"],
    "חדשות": ["משרד", "ועדה", "עירייה", "תושבים", "ישראל", "בארץ"],
    "פלילים": ["רצח", "ירי", "דקירה", "נעצר", "מעצר", "משטרה", "חשוד", "חקירה", "פיצוץ רכב"],
    "משפט": ["בית המשפט", "בגץ", "בג\"ץ", "עליון", "שופט", "כתב אישום", "עתירה", "פרקליטות"],
    "כלכלה": ["בורסה", "שקל", "דולר", "ריבית", "אינפלציה", "מניות", "בנק", "בנקים", "אשראי", "חברה", "עסקה", "שוק"],
    "רכב": ["רכב", "מכונית", "אופנוע", "קטנוע", "כביש", "תאונה", "נהג", "נהיגה", "חשמלי", "תחבורה"],
    "ספורט": ["כדורגל", "כדורסל", "ליגה", "מאמן", "שחקן", "קבוצה", "נבחרת", "מכבי", "הפועל", "ביתר", "בית״ר"],
    "אקטואליה בעולם": ["ארהב", "ארה\"ב", "ארה״ב", "אירופה", "רוסיה", "אוקראינה", "סין", "טראמפ", "נאטו", "או\"ם", "או״ם"],
    "מקורות זרים": ["Trump", "US", "Iran", "Israel", "Middle East", "Russia", "Ukraine", "China", "Europe", "NATO"],
    "צרכנות": ["צרכן", "צרכנים", "מחיר", "מבצע", "רשת", "מוצר", "קנייה", "הנחה", "יוקר"],
    "דעות": ["טור", "דעה", "פרשנות", "כותב", "כותבת", "טוען", "מזהיר"],
    "טכנולוגיה": ["טכנולוגיה", "AI", "בינה מלאכותית", "סייבר", "אפל", "גוגל", "מטא", "מיקרוסופט", "סטארטאפ"],
    "בריאות": ["בריאות", "רופא", "חולים", "מחקר", "תרופה", "חיסון", "מחלה", "תזונה", "שיניים"],
    "תרבות": ["סרט", "סדרה", "מוזיקה", "זמר", "שחקן", "תיאטרון", "פסטיבל", "אלבום"],
    "רכילות": ["כוכב", "כוכבת", "סלב", "חתונה", "זוגיות", "נפרד", "נפרדה", "אינסטגרם"],
    "נדל״ן": ["נדלן", "נדל\"ן", "נדל״ן", "דירה", "דירות", "משכנתה", "פרויקט", "בנייה", "מחירי הדיור"],
    "מזג אוויר": ["מזג", "גשם", "שרב", "טמפרטורות", "תחזית", "רוחות", "חום", "קור"],
}

def qa_error_codes(errors: list[dict[str, Any]]) -> set[str]:
    return {str(e.get("code") or "") for e in errors if isinstance(e, dict)}

def rescue_disposition(errors: list[dict[str, Any]]) -> str:
    """Classify deterministic QA failures for rescue.

    Most item-level QA errors mean the candidate is newsworthy but the deterministic
    card is bad.  Those must go to the full editor for repair, not disappear as
    final rejects.  Only explicitly hard/sanitation failures are report-only.
    """
    codes = qa_error_codes(errors)
    if codes and codes <= HARD_REJECT_CODES:
        return "hard_reject_report_only"
    return "repair_editorial_soft_fail"

def domain_candidate_matches(domain: str, item: dict[str, Any], candidate: Any) -> bool:
    if not domain:
        return True
    text = " ".join(str(x or "") for x in [
        item.get("category"), item.get("headline"), item.get("context"), item.get("takeaway"),
        item.get("originalTitle"), item.get("source"), getattr(candidate, "title", ""),
        getattr(candidate, "original_title", ""), getattr(candidate, "description", ""),
    ])
    if str(item.get("category") or "").strip() == domain:
        return True
    if domain == "חדשות" and str(item.get("category") or "").strip() in {"חדשות", "בארץ"}:
        return True
    return any(keyword_in_text(k, text) for k in DOMAIN_KEYWORDS.get(domain, []))

def keyword_in_text(keyword: str, text: str) -> bool:
    # Avoid Hebrew substring false positives: רקט in הפרקט, צהל in צהלה, etc.
    if not keyword:
        return False
    pattern = r"(?<![0-9A-Za-z\u0590-\u05ff])" + re.escape(keyword) + r"(?![0-9A-Za-z\u0590-\u05ff])"
    return re.search(pattern, text) is not None


def source_group(name: str) -> str:
    low = (name or "").lower()
    if "הארץ" in name or "haaretz" in low:
        return "הארץ"
    if "דה מרקר" in name or "themarker" in low:
        return "דה מרקר"
    if "ynet" in low:
        return "ynet"
    if "וואלה" in name or "walla" in low:
        return "וואלה"
    if "מעריב" in name or "maariv" in low:
        return "מעריב"
    if "גלובס" in name or "globes" in low:
        return "גלובס"
    if "ישראל היום" in name or "israel hayom" in low:
        return "ישראל היום"
    if "bbc" in low:
        return "BBC"
    if "n12" in low or "mako" in low:
        return "N12"
    if "jerusalem post" in low or "jpost" in low:
        return "Jerusalem Post"
    if "סרוגים" in name:
        return "סרוגים"
    if "ערוץ 14" in name or "c14" in low or "now14" in low:
        return "ערוץ 14"
    if "ערוץ 7" in name or "israel national news" in low or "inn" in low:
        return "ערוץ 7 / INN"
    if "כיפה" in name or "kipa" in low:
        return "כיפה"
    if "בשבע" in name or "besheva" in low:
        return "בשבע"
    if "מקור ראשון" in name or "makorrishon" in low:
        return "מקור ראשון"
    if "דובר צה" in name or "idf" in low:
        return "דובר צה״ל"
    if "משטרת ישראל" in name or "israel_police" in low:
        return "דוברות משטרת ישראל"
    if "pplus" in low or "פנאי פלוס" in name:
        return "Pplus"
    if "tmi" in low:
        return "TMI"
    if "daily mail" in low or "dailymail" in low:
        return "Daily Mail"
    if "mirror" in low:
        return "Mirror"
    if "page six" in low or "pagesix" in low:
        return "Page Six"
    if "cnn" in low:
        return "CNN"
    if "sky" in low:
        return "Sky News"
    if "reuters" in low:
        return "Reuters"
    if "associated press" in low or low.strip() == "ap" or " ap " in f" {low} ":
        return "AP"
    if "guardian" in low:
        return "Guardian"
    if "new york times" in low or "nyt" in low:
        return "NYT"
    if "axios" in low:
        return "Axios"
    if "politico" in low:
        return "Politico"
    if "bloomberg" in low:
        return "Bloomberg"
    if "jazeera" in low:
        return "Al Jazeera"
    return ""


def parse_dt(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    except Exception:
        return None


def candidate_to_item(c: Any) -> dict[str, Any]:
    c.original_title = c.original_title or c.title
    c.title = update_feed.sanitize_title(c.title)
    category, cls = update_feed.categorize_item(c.title, c.description, c.source)
    return {
        "category": category,
        "categoryClass": cls,
        "source": c.source,
        "sourceLogo": update_feed.source_logo(c.source),
        "sourceUrl": c.url,
        "imageUrl": c.image_url,
        "publishedAt": c.published_at,
        "hasSourceDate": bool(c.published_at),
        "time": "rescue-candidate",
        "headline": update_feed.poanta_headline(c.title, c.description, c.source),
        "originalTitle": c.original_title or c.title,
        "context": update_feed.context_text(c.title, c.description, c.source),
        "takeaway": update_feed.takeaway_text(category, c.title, c.description),
    }


def stale_groups_from_auditor(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    groups: set[str] = set()
    # Live auditor treats stale source-view findings as warnings by design: they
    # must not block an otherwise fresh feed.  For rescue prioritization they are
    # still important signals, otherwise the rescue queue can miss exactly the
    # sources that made the app look stuck (for example foreign/דה מרקר views)
    # while the top feed is already repaired.
    findings = list(data.get("errors", [])) + list(data.get("warnings", []))
    for issue in findings:
        code = issue.get("code")
        group_name = str(issue.get("group") or "")
        # Timing auditor errors are dashboard-red incidents even when the live
        # feed itself looks fresh.  They must feed the same rescue
        # prioritization path; otherwise the auditor can declare live OK while
        # the timing agent keeps flashing red for foreign/important sources.
        if code == "publication_timing_sla":
            if group_name == "foreign":
                groups.update(FOREIGN_SOURCES)
                continue
            if group_name in IMPORTANT_SOURCES or group_name in FOREIGN_SOURCES:
                groups.add(group_name)
                continue
        if code == "stale_foreign_source_view":
            groups.update(FOREIGN_SOURCES)
            continue
        if code != "stale_important_source_view":
            continue
        message = str(issue.get("message") or "")
        for group in IMPORTANT_SOURCES:
            if f"Latest {group} item" in message:
                groups.add(group)
    return groups


def load_domain_source_groups(domain: str, path: Path = DEFAULT_DOMAIN_SOURCES) -> set[str]:
    if not domain:
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    spec = data.get(domain) if isinstance(data, dict) else None
    if not isinstance(spec, dict):
        return set()
    groups = {source_group(str(src)) or str(src) for src in spec.get("sources") or []}
    return {g for g in groups if g}


def freshness_sla_failing_from_auditor(path: Path) -> bool:
    """Return true when the live feed itself is stale/thin, not just one source view.

    This is intentionally separate from stale source-view prioritization.  The
    2026-05-21 stuck-feed incident exposed a bad failure mode: when the auditor
    reports both a top-feed freshness SLA error and stale source-view warnings,
    the rescue queue can spend its first editor slots on old stale-source cards
    instead of the newest candidates that would actually move the visible top
    feed forward.  In that state, freshness must win; source-view repair still
    matters, but it must not block the top-feed rescue lane.
    """
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    for issue in list(data.get("errors", [])) + list(data.get("warnings", [])):
        if issue.get("code") in {"no_new_top_item_sla", "too_few_recent_items_sla", "too_few_recent_sources_sla", "low_recent_top_volume", "low_recent_feed_volume"}:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-min", type=int, default=180)
    ap.add_argument("--sync-profile", choices=["all", "fast", "medium", "slow"], default="all")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--auditor", default=str(DEFAULT_AUDITOR), help="Auditor JSON used to prioritize stale source views")
    ap.add_argument("--per-source", type=int, default=8, help="Candidates scanned per source; stale groups use this full budget")
    ap.add_argument("--domain", default="", help="Limit rescue queue to sources mapped for this domain/category")
    ap.add_argument("--domain-sources", default=str(DEFAULT_DOMAIN_SOURCES), help="Domain-to-source mapping JSON")
    args = ap.parse_args()

    now = datetime.now(TZ)
    cutoff = now - timedelta(minutes=args.max_age_min)
    stale_groups = stale_groups_from_auditor(Path(args.auditor))
    domain_groups = load_domain_source_groups(args.domain, Path(args.domain_sources))
    freshness_sla_failing = freshness_sla_failing_from_auditor(Path(args.auditor))
    rows: list[dict[str, Any]] = []
    source_diagnostics: list[dict[str, Any]] = []

    for source in update_feed.load_sources(args.sync_profile):
        group = source_group(source.get("name", ""))
        if domain_groups:
            if group not in domain_groups:
                continue
        elif group not in QUEUE_GROUPS:
            continue
        try:
            candidates = update_feed.extract_source(source)
        except Exception as exc:
            rows.append({"sourceGroup": group, "source": source.get("name"), "status": "fetch_error", "error": str(exc)})
            source_diagnostics.append({
                "sourceGroup": group,
                "source": source.get("name"),
                "profile": update_feed.source_sync_profile(source),
                "status": "fetch_error",
                "error": str(exc),
                "raw": 0,
                "valid": 0,
                "recent": 0,
                "editorFirst": 0,
                "repairable": 0,
                "latestCandidateAt": "",
                "latestValidAt": "",
            })
            continue
        candidates = sorted(candidates, key=lambda x: (x.published_at, x.score), reverse=True)
        scan_limit = args.per_source if group in stale_groups else max(4, args.per_source // 2)
        valid_count = 0
        recent_count = 0
        editor_first_count = 0
        repairable_count = 0
        latest_valid_at = ""
        for c in candidates[:scan_limit]:
            dt = parse_dt(c.published_at)
            if not dt or dt < cutoff:
                continue
            if group in FOREIGN_SOURCES and not update_feed.is_foreign_relevant(c.original_title or c.title, c.description):
                continue
            valid_count += 1
            recent_count += 1
            latest_valid_at = latest_valid_at or c.published_at
            item = candidate_to_item(c)
            if not domain_candidate_matches(args.domain, item, c):
                continue
            errors = update_feed.item_quality_errors(item)
            if errors and update_feed.source_editor_first_candidate(c, source):
                editor_first_count += 1
                rows.append({
                    "sourceGroup": group,
                    "source": c.source,
                    "publishedAt": c.published_at,
                    "sourceUrl": c.url,
                    "originalTitle": c.original_title or c.title,
                    "deterministicHeadline": item["headline"],
                    "deterministicContext": item["context"],
                    "deterministicTakeaway": item["takeaway"],
                    "deterministicCategory": item.get("category", ""),
                    "qaErrors": errors,
                    "qaErrorCodes": sorted(qa_error_codes(errors)),
                    "rescueDisposition": "editor_first_source",
                    "priority": "freshness" if freshness_sla_failing else ("high" if group in stale_groups else "normal"),
                    "staleSourceView": group in stale_groups,
                    "recommendedAction": "send_to_full_editor_rescue_queue",
                })
                continue
            if errors:
                disposition = rescue_disposition(errors)
                if disposition == "hard_reject_report_only":
                    recommended = "hard_reject_report_only"
                else:
                    repairable_count += 1
                    recommended = "send_to_full_editor_rescue_queue"
                rows.append({
                    "sourceGroup": group,
                    "source": c.source,
                    "publishedAt": c.published_at,
                    "sourceUrl": c.url,
                    "originalTitle": c.original_title or c.title,
                    "deterministicHeadline": item["headline"],
                    "deterministicContext": item["context"],
                    "deterministicTakeaway": item["takeaway"],
                    "deterministicCategory": item.get("category", ""),
                    "qaErrors": errors,
                    "qaErrorCodes": sorted(qa_error_codes(errors)),
                    "rescueDisposition": disposition,
                    "priority": "freshness" if freshness_sla_failing else ("high" if group in stale_groups else "normal"),
                    "staleSourceView": group in stale_groups,
                    "recommendedAction": recommended,
                })
        source_diagnostics.append({
            "sourceGroup": group,
            "source": source.get("name"),
            "profile": update_feed.source_sync_profile(source),
            "status": "ok",
            "raw": len(candidates),
            "valid": valid_count,
            "recent": recent_count,
            "editorFirst": editor_first_count,
            "repairable": repairable_count,
            "latestCandidateAt": candidates[0].published_at if candidates else "",
            "latestValidAt": latest_valid_at,
            "staleSourceView": group in stale_groups,
        })

    if freshness_sla_failing:
        # Top-feed freshness incidents need the newest valid candidates first.
        # Stale source-view rows remain present and marked, but do not consume
        # the first rescue-editor batch ahead of newer cards that can make the
        # app visibly fresh again.
        rows = sorted(rows, key=lambda r: r.get("publishedAt") or "", reverse=True)
    else:
        high = sorted([r for r in rows if r.get("priority") == "high"], key=lambda r: r.get("publishedAt") or "", reverse=True)
        normal = sorted([r for r in rows if r.get("priority") != "high"], key=lambda r: r.get("publishedAt") or "", reverse=True)
        rows = high + normal

    deduped: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for row in rows:
        url = row.get("sourceUrl") or ""
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        deduped.append(row)
    rows = deduped

    active_groups = sorted(domain_groups) if domain_groups else QUEUE_GROUPS
    report = {
        "name": "Pointa source rescue queue",
        "mode": "shadow-report-only",
        "checkedAt": now.isoformat(timespec="seconds"),
        "maxAgeMin": args.max_age_min,
        "domain": args.domain or None,
        "domainSourceGroups": sorted(domain_groups),
        "freshnessSlaFailing": freshness_sla_failing,
        "items": rows,
        "staleSourceGroups": sorted(stale_groups),
        "itemsNeedingRescueForStaleViews": sum(1 for r in rows if r.get("staleSourceView")),
        "sourceDiagnostics": source_diagnostics,
        "counts": {
            "total": len(rows),
            "repairableEditorial": sum(1 for r in rows if r.get("rescueDisposition") == "repair_editorial_soft_fail"),
            "editorFirst": sum(1 for r in rows if r.get("rescueDisposition") == "editor_first_source"),
            "hardRejectReportOnly": sum(1 for r in rows if r.get("rescueDisposition") == "hard_reject_report_only"),
            "bySource": {s: sum(1 for r in rows if r.get("sourceGroup") == s) for s in active_groups},
        },
        "note": "Report only. Does not modify feed.json or publish. Editorial QA failures are repairable soft failures and go to full-editor rescue; only hard sanitation/exception failures are report-only rejects. If the top-feed freshness SLA is failing, newest candidates are prioritized first; otherwise stale source-view rows are prioritized while quality gates remain strict.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"items": len(rows), "freshnessSlaFailing": freshness_sla_failing, "staleSourceGroups": sorted(stale_groups), "staleViewRescueItems": report["itemsNeedingRescueForStaleViews"], "out": str(out), "bySource": report["counts"]["bySource"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
