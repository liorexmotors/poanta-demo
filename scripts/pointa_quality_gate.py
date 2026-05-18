#!/usr/bin/env python3
"""Pointa feed quality gate.

Blocks releases when generated Pointa cards violate the editorial/UI contract.
This is intentionally conservative: a questionable card should be reviewed or
excluded rather than shipped as a broken Pointa card.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "feed.json"
REPORT_PATH = ROOT / "pointa_quality_report.md"

HEADLINE_MAX = 75
SUMMARY_MAX = 220
TAKEAWAY_MAX = 95

ORPHAN_PREFIX_RE = re.compile(r"^\s*[-–—]+\s*|^\s*(ואז|אבל|אולם|כי|לכן)\b")
DANGLING_ENDINGS = {
    "של", "את", "על", "עם", "אל", "כל", "כי", "אבל", "אולם", "כאשר", "בגלל",
    "בין", "תוך", "לפני", "אחרי", "עד", "מול", "נגד", "כדי", "אם", "בעקבות",
    "ח\"כ", "ח״כ", "גררו", "נאלצו", "התייחס", "התארח", "נחשף", "יוכלו",
}
GENERIC_HEADLINE_PATTERNS = [
    "במרכז הסיפור", "הידיעה חשובה", "הסיפור חשוב", "השאלה היא", "החשיבות היא",
    "מה מסתתר", "זה מה", "כל מה", "לא תאמינו", "סערה", "דרמה", "טירוף",
]
GENERIC_SUMMARY_PATTERNS = [
    "פורסם", "דיווח", "המקור", "הכתב", "כתבה בנושא", "הידיעה חשובה בגלל",
    "הסיפור חשוב בגלל", "במרכז הסיפור:", "החשיבות היא ההשפעה המעשית",
]
GENERIC_TAKEAWAY_PATTERNS = [
    "משנה את תמונת המצב", "ההשפעה המעשית", "השאלה היא איך", "השאלה היא מי",
    "החשיבות של", "המשמעות של", "הסיכון סביב", "הסיפור סביב", "הפרטים הקטנים סביב",
    "חשוב יותר מהניסוח", "נקודת ההשלכה המרכזית", "אין פואנטה אמינה",
]
SOURCE_MEDIATION = ["הכתב מתאר", "הכתבה עוסקת", "המקור מדווח", "פורסם כי", "דווח כי"]
ALLOWED_LATIN = {
    "AI", "BBC", "CNN", "Sky", "News", "MV", "Hondius", "T1", "UKMTO", "FBI",
    "NBA", "MMA", "MBA", "SUV", "LDL", "Hailo", "OpenAI", "GPT", "N12",
}

GOLDEN_CASES = [
    {
        "name": "Genesis/Pinchasov broad story",
        "match_any": ["ג׳נסיס", "פנחסוב"],
        "headline_contains": "פסטיבל ג׳נסיס הפך ל־12 שעות של אסקפיזם מוזיקלי מהמציאות",
        "takeaway_contains": "רגע נדיר של חופש",
        "category": "תרבות",
    },
    {
        "name": "Malinovsky Oct 7 law",
        "match_any": ["מלינובסקי", "מחבלי 7 באוקטובר", "מרד של כלל חברי הכנסת"],
        "headline_contains": "ח״כ מלינובסקי מאיימת לשבש הצבעות",
        "category": "פוליטיקה",
    },
    {
        "name": "Helium/Iran war",
        "match_any": ["הליום", "הגז הנדיר"],
        "headline_contains": "המלחמה באיראן הקפיצה את מחירי ההליום",
        "category": "כלכלה",
    },
    {
        "name": "Smotrich/Elgart hearing",
        "match_any": ["סמוטריץ", "דני אלגרט", "מי אדוני"],
        "headline_contains": "שאלה של סמוטריץ׳ לדני אלגרט הציתה עימות בוועדה",
    },
    {
        "name": "Amos Luzon celebrity classification",
        "match_any": ["עמוס לוזון", "פער של 33 שנה"],
        "headline_contains": "פער הגילים הפך את הזוגיות של עמוס לוזון לכותרת סלבס",
        "category": "תרבות",
    },
]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def tokens(text: str) -> list[str]:
    return [w for w in re.sub(r"[^0-9A-Za-z\u0590-\u05ff]+", " ", norm(text)).lower().split() if len(w) > 2]


def overlap_ratio(a: str, b: str) -> float:
    aw = tokens(a)
    bw = set(tokens(b))
    if not aw or not bw:
        return 0.0
    return sum(1 for w in aw if w in bw) / max(1, len(aw))


def has_latin_leak(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text or "")
    return [w for w in words if w not in ALLOWED_LATIN]


def looks_cut(headline: str) -> bool:
    h = norm(headline).strip(" ,;:-–—")
    if not h:
        return True
    last = h.split()[-1].strip('"׳״.,;:!?()[]')
    return last in DANGLING_ENDINGS or bool(re.search(r"[,;:–—-]\s*$", headline or ""))


def card_blob(item: dict[str, Any]) -> str:
    return " | ".join(norm(item.get(k, "")) for k in ["headline", "context", "takeaway", "originalTitle", "source", "sourceUrl"])


def add_issue(issues: list[dict[str, Any]], severity: str, idx: int, code: str, msg: str, item: dict[str, Any]) -> None:
    issues.append({
        "severity": severity,
        "index": idx,
        "code": code,
        "message": msg,
        "headline": norm(item.get("headline", "")),
        "originalTitle": norm(item.get("originalTitle", "")),
        "source": norm(item.get("source", "")),
        "url": norm(item.get("sourceUrl", "")),
    })


def validate_item(item: dict[str, Any], idx: int, issues: list[dict[str, Any]]) -> None:
    headline = norm(item.get("headline", ""))
    context = norm(item.get("context", ""))
    takeaway = norm(item.get("takeaway", ""))
    original = norm(item.get("originalTitle", ""))
    category = norm(item.get("category", ""))
    source = norm(item.get("source", ""))

    if not headline:
        add_issue(issues, "error", idx, "headline_missing", "Headline is empty", item)
    if len(headline) > HEADLINE_MAX:
        add_issue(issues, "error", idx, "headline_too_long", f"Headline length {len(headline)} > {HEADLINE_MAX}", item)
    if ORPHAN_PREFIX_RE.search(headline):
        add_issue(issues, "error", idx, "headline_orphan_prefix", "Headline starts with an orphan suffix/connective", item)
    if looks_cut(headline):
        add_issue(issues, "error", idx, "headline_looks_cut", "Headline appears mechanically cut", item)
    if headline.endswith("?") or headline.startswith(('"', "׳", "״", "“", "”")):
        add_issue(issues, "error", idx, "headline_source_style", "Headline is question/quote/source style", item)
    if any(p in headline for p in GENERIC_HEADLINE_PATTERNS):
        add_issue(issues, "error", idx, "headline_generic", "Headline contains generic/clickbait framing", item)
    if original and (headline in original or original in headline or overlap_ratio(original, headline) >= 0.72):
        add_issue(issues, "error", idx, "headline_copies_source", "Pointa headline is too close to original title", item)

    if not context:
        add_issue(issues, "error", idx, "summary_missing", "Summary/context is empty", item)
    if len(context) > SUMMARY_MAX:
        add_issue(issues, "warning", idx, "summary_long", f"Summary length {len(context)} > {SUMMARY_MAX}", item)
    if any(p in context for p in GENERIC_SUMMARY_PATTERNS + SOURCE_MEDIATION):
        add_issue(issues, "error", idx, "summary_generic_or_mediated", "Summary is generic or source-mediated", item)

    if not takeaway:
        add_issue(issues, "error", idx, "takeaway_missing", "Takeaway is empty", item)
    if len(takeaway) > TAKEAWAY_MAX:
        add_issue(issues, "warning", idx, "takeaway_long", f"Takeaway length {len(takeaway)} > {TAKEAWAY_MAX}", item)
    if any(p in takeaway for p in GENERIC_TAKEAWAY_PATTERNS):
        add_issue(issues, "error", idx, "takeaway_generic", "Takeaway is generic/reusable", item)

    if "סלבס" in source and category != "תרבות":
        add_issue(issues, "error", idx, "category_celebs", "Celebs source must be תרבות", item)
    if any(x in source for x in ["ספורט", "NBA", "כדורגל", "כדורסל"]) and category != "ספורט":
        add_issue(issues, "warning", idx, "category_sport_source", "Sport source should usually be ספורט", item)

    if any(x in source for x in ["CNN", "BBC", "Sky News"]):
        for field in ["headline", "context", "takeaway"]:
            leaks = has_latin_leak(norm(item.get(field, "")))
            if leaks:
                add_issue(issues, "error", idx, "foreign_latin_leak", f"Latin leak in {field}: {', '.join(leaks[:5])}", item)

    if any(x in headline for x in ["מלחמה במפרץ והפגיעה", "הדיון יצא משליטה", "עמוס לוזון בזוגיות חדשה"]):
        add_issue(issues, "error", idx, "known_bad_regression", "Known bad headline regression", item)


def validate_golden(items: list[dict[str, Any]], issues: list[dict[str, Any]]) -> None:
    for case in GOLDEN_CASES:
        matches = [it for it in items if any(term in card_blob(it) for term in case["match_any"])]
        if not matches:
            issues.append({"severity": "error", "index": -1, "code": "golden_missing", "message": f"Missing golden case: {case['name']}", "headline": "", "originalTitle": "", "source": "", "url": ""})
            continue
        best = matches[0]
        if case.get("headline_contains") and case["headline_contains"] not in norm(best.get("headline", "")):
            add_issue(issues, "error", -1, "golden_headline", f"Golden case failed: {case['name']}", best)
        if case.get("takeaway_contains") and case["takeaway_contains"] not in norm(best.get("takeaway", "")):
            add_issue(issues, "error", -1, "golden_takeaway", f"Golden takeaway failed: {case['name']}", best)
        if case.get("category") and norm(best.get("category", "")) != case["category"]:
            add_issue(issues, "error", -1, "golden_category", f"Golden category failed: {case['name']} expected {case['category']}", best)


def render_report(items: list[dict[str, Any]], issues: list[dict[str, Any]]) -> str:
    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]
    by_code = Counter(i["code"] for i in issues)
    by_cat = Counter(norm(i.get("category", "")) for i in items)
    lines = [
        "# Pointa Quality Gate Report",
        "",
        f"Items checked: {len(items)}",
        f"Errors: {len(errors)}",
        f"Warnings: {len(warnings)}",
        "",
        "## Category distribution",
        "",
    ]
    for cat, count in by_cat.most_common():
        lines.append(f"- {cat or 'ללא'}: {count}")
    lines += ["", "## Issue counts", ""]
    if by_code:
        for code, count in by_code.most_common():
            lines.append(f"- {code}: {count}")
    else:
        lines.append("- No issues found")
    lines += ["", "## Issues", ""]
    for issue in issues[:200]:
        lines.append(f"### {issue['severity'].upper()} · {issue['code']} · item {issue['index']}")
        lines.append(f"- {issue['message']}")
        lines.append(f"- Headline: `{issue['headline']}`")
        if issue.get("originalTitle"):
            lines.append(f"- Original: `{issue['originalTitle']}`")
        if issue.get("source"):
            lines.append(f"- Source: {issue['source']}")
        if issue.get("url"):
            lines.append(f"- URL: {issue['url']}")
        lines.append("")
    if len(issues) > 200:
        lines.append(f"_Truncated: {len(issues)-200} additional issues not shown._")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default=str(FEED_PATH))
    ap.add_argument("--report", default=str(REPORT_PATH))
    ap.add_argument("--warnings-fail", action="store_true")
    args = ap.parse_args()

    data = json.loads(Path(args.feed).read_text(encoding="utf-8"))
    items = data.get("items", [])
    issues: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        validate_item(item, idx, issues)
    validate_golden(items, issues)
    report = render_report(items, issues)
    Path(args.report).write_text(report, encoding="utf-8")

    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]
    print(f"Pointa quality gate: {len(items)} items, {len(errors)} errors, {len(warnings)} warnings")
    print(f"Report: {args.report}")
    if errors or (args.warnings_fail and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
