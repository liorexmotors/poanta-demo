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
    "רק", "לא", "בלי", "בלתי", "תחת", "לצד", "במהלך", "לאחר", "לקראת", "בעוד",
    "ח\"כ", "ח״כ", "גררו", "נאלצו", "התייחס", "התארח", "נחשף", "יוכלו",
}
GENERIC_HEADLINE_PATTERNS = [
    "במרכז הסיפור", "הידיעה חשובה", "הסיפור חשוב", "השאלה היא", "החשיבות היא",
    "מה מסתתר", "זה מה", "כל מה", "לא תאמינו", "סערה", "דרמה", "טירוף",
    "מגייס פרעון", "מגייס פרשן פוליטי", "באותו אירוע בו",
]
GENERIC_SUMMARY_PATTERNS = [
    "פורסם", "דיווח", "המקור", "הכתב", "כתבה בנושא", "הידיעה חשובה בגלל",
    "הסיפור חשוב בגלל", "במרכז הסיפור:", "החשיבות היא ההשפעה המעשית",
]
GENERIC_TAKEAWAY_PATTERNS = [
    "משנה את תמונת המצב", "ההשפעה המעשית", "השאלה היא איך", "השאלה היא מי",
    "החשיבות של", "המשמעות של", "הסיכון סביב", "הסיפור סביב", "הפרטים הקטנים סביב",
    "חשוב יותר מהניסוח", "נקודת ההשלכה המרכזית", "אין פואנטה אמינה",
    "עדכון רשמי של המשטרה", "שימושי במיוחד למעקב", "מקור רשמי",
    "הפרט שקובע מה באמת השתנה", "עשוי לשנות היערכות", "מרחב פעולה",
    "קובע את המחיר האמיתי", "מסמן מי עלול לשלם", "משנה שימוש, פרטיות או אמון",
    "משפיע על עלות, בטיחות", "משנה את המשך העונה", "מחייב להבין את הסיכון",
    "מראה איך רגע פרטי", "חושף את קו הטיעון",
    "גם מוסד אהוב לא חסין מעלויות", "גם אוכל בטיסה הפך לכלי תחרות",
    "אצל ליגיונרים, הזדמנות אחת יכולה לשנות את העונה הבאה",
    "הערך של עדכון צבאי כזה תלוי בשאלה",
    "אירוע משטרתי משמעותי צריך להיבחן לפי",
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
        "category": "רכילות",
    },
]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def norm_sentence(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u0590-\u05ff]+", " ", norm(text)).strip().lower()


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
    if last in DANGLING_ENDINGS or bool(re.search(r"[,;:–—-]\s*$", headline or "")):
        return True
    # Mechanical cuts often leave an opened quote/parenthesis or end right after a
    # subordinating phrase. A headline must be a complete thought, not a clipped
    # source sentence.
    # ASCII quotes are usually paired; Hebrew gereshayim (״) also appears inside abbreviations
    # such as ח״כ/ארה״ב, so only treat a gereshayim as an open quote when the headline
    # contains source-style quoted speech marks around a phrase.
    quote_test = re.sub(r'(?<=[A-Za-zא-ת])"(?=[A-Za-zא-ת])', '', h)
    if quote_test.count('"') % 2 or h.count('(') > h.count(')'):
        return True
    if re.search(r"(?<![א-ת])(כי|כאשר|בזמן ש|לאחר ש|בעוד ש)(?![א-ת])\s+[^.?!]{0,90}$", h) and not re.search(r"[.?!]$", h):
        return True
    return False


def card_blob(item: dict[str, Any]) -> str:
    return " | ".join(norm(item.get(k, "")) for k in ["headline", "context", "originalTitle", "source", "sourceUrl"])


def opinion_author_from_item(item: dict[str, Any]) -> str:
    for key in ["author", "byline", "writer"]:
        val = norm(item.get(key, ""))
        if val:
            return val
    original = norm(item.get("originalTitle", ""))
    if "|" in original:
        candidate = original.rsplit("|", 1)[-1].strip()
        if 2 <= len(candidate) <= 40 and not any(x in candidate for x in ["מעריב", "וואלה", "ynet", "חדשות"]):
            return candidate
    return ""


def author_visible(author: str, blob: str) -> bool:
    if not author:
        return True
    variants = {author}
    variants.add(re.sub(r"^(?:עו[״\"]?ד|ד[״\"]?ר|פרופ[׳']?)\s+", "", author).strip())
    variants.add(author.replace('"', '״'))
    variants.add(author.replace('״', '"'))
    return any(v and v in blob for v in variants)


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
    source_url = norm(item.get("sourceUrl", item.get("url", "")))

    visible_blob = " | ".join([headline, context])
    if re.search(r"<[^>]+>|['\"]\s*>|\b(?:border|width|height|src|alt|class|style)=['\"]", visible_blob, flags=re.I):
        add_issue(issues, "error", idx, "html_artifact", "Visible card text contains HTML/attribute artifacts", item)

    if not headline:
        add_issue(issues, "error", idx, "headline_missing", "Headline is empty", item)
    if len(headline) > HEADLINE_MAX:
        add_issue(issues, "error", idx, "headline_too_long", f"Headline length {len(headline)} > {HEADLINE_MAX}", item)
    if ORPHAN_PREFIX_RE.search(headline):
        add_issue(issues, "error", idx, "headline_orphan_prefix", "Headline starts with an orphan suffix/connective", item)
    if looks_cut(headline):
        add_issue(issues, "error", idx, "headline_looks_cut", "Headline appears mechanically cut", item)
    if "|" in headline:
        add_issue(issues, "error", idx, "headline_pipe_artifact", "Headline contains a source-list pipe artifact", item)
    if headline.endswith("?") or headline.startswith(('"', "׳", "״", "“", "”")):
        add_issue(issues, "error", idx, "headline_source_style", "Headline is question/quote/source style", item)
    if any(p in headline for p in GENERIC_HEADLINE_PATTERNS):
        add_issue(issues, "error", idx, "headline_generic", "Headline contains generic/clickbait framing", item)
    official_alert_source = "פיקוד העורף" in source
    if original and not official_alert_source and (headline in original or original in headline or overlap_ratio(original, headline) >= 0.72):
        add_issue(issues, "error", idx, "headline_copies_source", "Pointa headline is too close to original title", item)
    if context and norm_sentence(headline) == norm_sentence(context):
        add_issue(issues, "error", idx, "headline_duplicates_summary", "Headline duplicates the summary", item)
    if context and len(headline) >= 24 and norm(context).startswith(norm(headline)):
        add_issue(issues, "error", idx, "headline_is_summary_prefix", "Headline is just the opening fragment of the summary", item)
    if context and overlap_ratio(headline, context) >= 0.88 and (len(headline) >= 58 or len(context) <= 120):
        add_issue(issues, "warning", idx, "headline_near_duplicate_summary", "Headline is a clipped/near-duplicate version of the summary", item)

    blob = " ".join([headline, context, original, source])
    content_blob = " ".join([headline, context, original])
    me_or_israel_terms = ["ישראל", "israel", "הסכמי אברהם", "abraham accords", "middle east", "mideast", "מזרח תיכון", "עזה", "gaza", "חמאס", "חיזבאללה", "לבנון", "איראן", "iran", "הורמוז", "סעודיה", "קטאר", "מצרים", "ירדן", "טורקיה", "פלסטיני"]
    world_only_terms = ["קובה", "cuba", "פוקושימה", "fukushima"]
    strong_local_terms = ["ישראל", "israel", "הסכמי אברהם", "abraham accords", "middle east", "mideast", "עזה", "gaza"]
    content_low = content_blob.lower()
    source_low = source.lower()
    is_me_or_israel = (
        any(x.lower() in content_low for x in me_or_israel_terms)
        and (not any(x.lower() in content_low for x in world_only_terms) or any(x.lower() in content_low for x in strong_local_terms))
    ) or any(x in source_low for x in ["middle east", "mideast", "מזרח תיכון"])
    if category == "אקטואליה בעולם" and is_me_or_israel:
        add_issue(issues, "error", idx, "category_world_boundary", "Israel/Middle-East stories must use the regular news/security/politics domains, not אקטואליה בעולם", item)
    if category == "פוליטיקה" and any(x in blob for x in ["איראן", "הורמוז", "גרעין", "אורניום"]) and any(x in blob for x in ["מו\"מ", "משא ומתן", "עסקה", "הסכם", "טראמפ"]):
        add_issue(issues, "error", idx, "category_iran_deal_security", "Iran nuclear/deal/Hormuz cards must be ביטחון, not פוליטיקה", item)
    if category in {"משפט", "פלילים", "חדשות", "פוליטיקה"} and any(x in blob for x in ["קובה", "פוקושימה", "הבית הלבן", "White House"]):
        add_issue(issues, "error", idx, "category_world_story", "Cuba/Fukushima/White House stories must be אקטואליה בעולם", item)
    weather_blob = " ".join([headline, context, original, source]).lower()
    if category in {"חדשות", "פוליטיקה"} and any(x.lower() in weather_blob for x in ["תחזית מזג אוויר", "מזג האוויר", "מזג אוויר", "טמפרטורות", "מעלות", "מעונן", "גשם", "שרב", "רוחות"]):
        add_issue(issues, "error", idx, "category_weather_forecast", "Weather forecast cards must be מזג אוויר, not חדשות/פוליטיקה", item)
    if any(x in headline for x in ["לפי אחד הבלוגים", "הגרסה החסכונית", "הקרוסאובר המוערך", "הקבוצה מאמסטרדם"]):
        add_issue(issues, "error", idx, "headline_missing_core_entity", "Headline is a summary fragment and misses the core entity/model/team", item)
    if re.search(r"^(זו כבר|זה כבר|אחרי שנים של|הרקע ל|ברקע ל)", headline):
        add_issue(issues, "error", idx, "headline_opener_fragment", "Headline starts like an article opener instead of a concrete Pointa headline", item)
    if any(x in headline for x in ["מחקר קשר", "מחקר מצא קשר בין", "מחקר מצא קשר ל"]):
        add_issue(issues, "error", idx, "headline_ungrammatical_study_framing", "Health-study headline must use complete Hebrew such as 'מחקר קושר...' and avoid ungrammatical source-style fragments", item)

    if not context:
        add_issue(issues, "error", idx, "summary_missing", "Summary/context is empty", item)
    if "|" in context:
        add_issue(issues, "error", idx, "summary_pipe_artifact", "Summary contains a source-list pipe artifact", item)
    if len(context) > SUMMARY_MAX:
        add_issue(issues, "warning", idx, "summary_long", f"Summary length {len(context)} > {SUMMARY_MAX}", item)
    if any(p in context for p in GENERIC_SUMMARY_PATTERNS + SOURCE_MEDIATION):
        add_issue(issues, "error", idx, "summary_generic_or_mediated", "Summary is generic or source-mediated", item)

    is_maariv_opinion = "מעריב" in source and ("דעות" in source or "דעות" in category or "/opinions/" in source_url)
    if is_maariv_opinion:
        author = opinion_author_from_item(item)
        if any(x in visible_blob for x in ["הטור", "הכותבת טוענת", "הכותב טוען", "לטענת הכותבת", "לטענת הכותב", "בעיני הכותבת", "בעיני הכותב"]):
            add_issue(issues, "error", idx, "opinion_generic_author_reference", "Opinion card uses generic writer/tour framing instead of the columnist's name", item)
        if author and not author_visible(author, visible_blob):
            add_issue(issues, "error", idx, "opinion_author_missing", f"Maariv opinion card must mention columnist by name: {author}", item)

    is_gossip_source = any(x in source for x in ["סלבס", "TMI", "Pplus", "פנאי פלוס", "פפראצי", "פפארצי", "רכילות"])
    if is_gossip_source and category != "רכילות":
        add_issue(issues, "error", idx, "category_celebs", "Celebs/gossip source must be רכילות", item)
    if is_gossip_source and not str(item.get("imageUrl") or "").strip():
        add_issue(issues, "error", idx, "gossip_missing_image", "Celebs/gossip cards must not publish without an article image", item)
    if category == "משפט":
        legal_terms = ["בית משפט", "בגץ", "בג\"ץ", "עליון", "שופט", "פרקליטות", "כתב אישום", "עתירה", "תביעה", "פסק דין", "הרשעה", "אישום"]
        sanctions_policy_terms = ["סנקציות", "קובה", "ממשל טראמפ", "ממשל", "מדינה", "מדיני", "פוליטי", "משלחת"]
        if any(x in visible_blob + " | " + original + " | " + source_url for x in sanctions_policy_terms) and not any(x in visible_blob + " | " + original for x in legal_terms):
            add_issue(issues, "error", idx, "category_law_without_legal_proceeding", "Do not classify sanctions/diplomatic-policy stories as משפט unless there is a concrete court/indictment/legal-proceeding angle", item)
    world_current_terms = ["סנקציות", "קובה", "ממשל טראמפ", "הבית הלבן", "ארה\"ב", "ארצות הברית", "רוסיה", "אוקראינה", "סין", "טייוואן", "נאטו"]
    is_world_current_story = any(x in visible_blob + " | " + original + " | " + source_url for x in world_current_terms) or "/news/world/" in source_url
    if is_world_current_story and category in {"משפט", "פוליטיקה"}:
        local_or_legal_terms = ["ישראל", "הכנסת", "ממשלה", "בגץ", "בג\"ץ", "בית משפט", "כתב אישום", "עתירה", "תביעה", "פסק דין"]
        if not any(x in visible_blob + " | " + original for x in local_or_legal_terms):
            add_issue(issues, "error", idx, "category_world_current_affairs", "Global sanctions/diplomacy/current-affairs stories should be אקטואליה בעולם, not משפט/פוליטיקה, unless the Israeli/local/legal angle is concrete", item)
    if "וואלה סלבס" in source and any(x in visible_blob for x in ["פרעון פוליטי", "מגייס פרעון", "מגייס פרשן פוליטי"]):
        add_issue(issues, "error", idx, "known_bad_gossip_headline", "Walla Celebs regression: bad/typo headline framing", item)
    if any(x in source for x in ["ספורט", "NBA", "כדורגל", "כדורסל"]) and category != "ספורט":
        add_issue(issues, "warning", idx, "category_sport_source", "Sport source should usually be ספורט", item)

    if any(x in source for x in ["CNN", "BBC", "Sky News"]):
        for field in ["headline", "context"]:
            leaks = has_latin_leak(norm(item.get(field, "")))
            if leaks:
                add_issue(issues, "error", idx, "foreign_latin_leak", f"Latin leak in {field}: {', '.join(leaks[:5])}", item)
    if any(x in source.lower() for x in ["al jazeera", "jazeera", "bbc", "cnn", "sky news", "reuters", "guardian", "new york times", "nyt", "axios", "politico", "bloomberg"]):
        foreign_text = " | ".join([headline, context, original, source_url]).lower()
        foreign_required = ["israel", "israeli", "jerusalem", "jewish", "jews", "antisemit", "zion", "iran", "tehran", "gaza", "hamas", "hezbollah", "lebanon", "syria", "iraq", "yemen", "houthi", "qatar", "saudi", "jordan", "egypt", "west bank", "palestinian", "rafah", "hormuz", "middle east", "mideast", "idf", "netanyahu", "ישראל", "ישראלי", "ירושלים", "יהודים", "אנטישמ", "איראן", "טהראן", "עזה", "חמאס", "חיזבאללה", "לבנון", "סוריה", "עיראק", "תימן", "חותים", "קטאר", "סעודיה", "ירדן", "מצרים", "הגדה", "פלסטינ", "רפיח", "הורמוז", "מזרח תיכון", "צה״ל", "צה\"ל", "נתניהו"]
        if not any(x in foreign_text for x in foreign_required):
            add_issue(issues, "error", idx, "foreign_item_not_middle_east_relevant", "Foreign-source item lacks Israel/Middle-East relevance", item)

    if any(x in headline for x in ["מלחמה במפרץ והפגיעה", "הדיון יצא משליטה", "עמוס לוזון בזוגיות חדשה"]):
        add_issue(issues, "error", idx, "known_bad_regression", "Known bad headline regression", item)
    if any(x in headline for x in ["אמר הבוקר בריאיון", "חוקרים בתחום תולדות האמנות חושדים זה זמן רב", "ללא פרסומות ותמונות"]):
        add_issue(issues, "error", idx, "headline_source_fragment_regression", "Headline is a copied/source-fragment sentence, not a Pointa event headline", item)


def validate_golden(items: list[dict[str, Any]], issues: list[dict[str, Any]]) -> None:
    for case in GOLDEN_CASES:
        scored = []
        min_score = min(2, len(case["match_any"]))
        for it in items:
            blob = card_blob(it)
            score = sum(1 for term in case["match_any"] if term in blob)
            if score >= min_score:
                scored.append((score, it))
        if not scored:
            continue
        best = max(scored, key=lambda row: row[0])[1]
        if case.get("headline_contains") and case["headline_contains"] not in norm(best.get("headline", "")):
            add_issue(issues, "error", -1, "golden_headline", f"Golden case failed: {case['name']}", best)
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
