#!/usr/bin/env python3
"""Build Poanta's separate breaking-news feed from dedicated RSS sources."""
from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = ROOT / "breaking_sources.json"
DEFAULT_OUTPUT = ROOT / "breaking_feed.json"
USER_AGENT = "PoantaBreakingFeed/1.0 (+https://liorexmotors.github.io/poanta-demo/)"
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

DROP_PATTERNS = [
    r"פרסומת", r"תוכן שיווקי", r"בשיתוף", r"התחזית", r"מזג האוויר",
]

# רוטר useful but noisy; keep hard-news/security/public affairs language only.
ROTTER_KEEP = re.compile(
    r"(צה.?ל|משטרה|פיגוע|ירי|אזעק|כטב|חמאס|חיזבאללה|איראן|עזה|לבנון|סוריה|כנסת|ממשלה|בג.?ץ|נעצר|תאונ|נפצע|נהרג|נרצח|שריפה|חשד|חקירה|חטופ|מלחמה|ביטחון|מדיני|ארה.?ב|ממשל|טראמפ)",
    re.I,
)


def clean_text(value: str | None) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def collapse_repeated_breaking_title(value: str) -> str:
    """Remove accidental repeated source/title clauses from terse RSS titles."""
    title = clean_text(value)
    if not title:
        return ""
    # Rotter occasionally emits a title where a source prefix + sentence appears
    # twice in the same row. Keep the first complete occurrence so the card is a
    # complete thought without a visible stutter.
    for sep in (":", " - ", "–"):
        if sep in title:
            prefix, rest = title.split(sep, 1)
            prefix = prefix.strip()
            if len(prefix) >= 5:
                repeated = f"{prefix}{sep}"
                second = title.find(repeated, len(prefix) + len(sep))
                if second > 0:
                    return title[:second].strip()
    # If the second half repeats the first half exactly after whitespace, keep one.
    words = title.split()
    if len(words) >= 8 and len(words) % 2 == 0:
        mid = len(words) // 2
        if words[:mid] == words[mid:]:
            return " ".join(words[:mid])
    return title


def visible_text_key(value: str | None) -> str:
    """Normalize text for user-visible duplicate checks."""
    text = clean_text(value).lower()
    text = re.sub(r"[\"'׳״`]+", "", text)
    text = re.sub(r"[^0-9A-Za-z\u0590-\u05ff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def useful_context(title: str, description: str) -> str:
    """Return description only when it adds information beyond the title.

    Many breaking RSS feeds repeat the title in <description>. Showing that as
    a second line creates a fake "content" row.  If there is no extra detail,
    leave context empty and let the UI omit the row.
    """
    desc = clean_text(description)
    if not desc:
        return ""
    title_key = visible_text_key(title)
    desc_key = visible_text_key(desc)
    if not desc_key or desc_key == title_key:
        return ""
    if title_key and (desc_key.startswith(title_key) or title_key.startswith(desc_key)):
        return ""
    # Very short descriptions rarely add useful context in a breaking feed.
    if len(desc_key) < 18:
        return ""
    # Keep breaking context compact: more information, not a full article body.
    if len(desc) > 320:
        cut = max(desc.rfind(".", 0, 300), desc.rfind(";", 0, 300), desc.rfind(". ", 0, 300))
        if cut >= 90:
            desc = desc[: cut + 1]
        else:
            desc = desc[:300].rstrip()
    return desc


def parse_date(value: str | None, source: dict[str, Any] | None = None) -> str:
    if not value:
        return ""
    value = clean_text(value)
    source = source or {}
    treat_gmt_as_israel_local = bool(source.get("treatGmtAsIsraelLocal"))
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt.tzinfo is None:
            # Israeli breaking-news feeds that omit an offset normally publish
            # local Israel wall-clock time.  Treating it as UTC creates future
            # timestamps that look suspiciously "now" in the app.
            dt = dt.replace(tzinfo=ISRAEL_TZ)
        elif treat_gmt_as_israel_local and re.search(r"\b(?:GMT|UTC)\b|[+-]0000", value, re.I):
            # Walla's breaking RSS currently labels local Israel time as GMT.
            # Example: "15:20 GMT" arrives while Israel is 15:23, but parsing
            # it literally makes the item 3 hours in the future.  Preserve the
            # wall-clock components and attach Asia/Jerusalem instead.
            dt = dt.replace(tzinfo=ISRAEL_TZ)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ISRAEL_TZ)
            return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            continue
    return ""


def fetch_url(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read(2_000_000)


def decode_payload(data: bytes) -> str:
    head = data[:200].decode("ascii", "ignore").lower()
    if "windows-1255" in head:
        return data.decode("cp1255", "ignore")
    return data.decode("utf-8", "ignore")


def item_children(item: ET.Element) -> dict[str, str]:
    out: dict[str, str] = {}
    for child in list(item):
        tag = child.tag.split("}")[-1].lower()
        out[tag] = child.text or ""
    return out


def parse_rss(text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    text = re.sub(r"<\?xml[^>]*\?>", "", text, count=1).lstrip()
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    root = ET.fromstring(text.encode("utf-8"))
    rows: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        fields = item_children(item)
        title = collapse_repeated_breaking_title(fields.get("title"))
        if not title:
            continue
        link = clean_text(fields.get("link") or fields.get("guid"))
        desc = clean_text(fields.get("description"))
        context = useful_context(title, desc)
        published = parse_date(fields.get("pubdate") or fields.get("published") or fields.get("updated") or fields.get("dc:date"), source)
        rows.append(
            {
                "id": hashlib.sha1((link or title).encode("utf-8")).hexdigest()[:16],
                "category": source.get("categoryHint") or "מבזקים",
                "source": source.get("source") or source.get("logo") or source.get("name") or "מקור",
                "sourceLogo": source.get("logo") or source.get("source") or source.get("name") or "מקור",
                "sourceUrl": link,
                "sourceLinks": [{"name": source.get("source") or source.get("logo") or source.get("name") or "מקור", "url": link}],
                "headline": title,
                "originalTitle": title,
                "context": context,
                "publishedAt": published,
                "hasSourceDate": bool(published),
                "breaking": True,
            }
        )
    return rows


DUPE_STOPWORDS = {
    "של", "את", "על", "עם", "אל", "כי", "לא", "יש", "הוא", "היא", "זה", "זו", "עד", "ב", "ל", "ה",
    "היום", "הלילה", "דיווח", "דווח", "לאחר", "בשל", "חשש", "חדש", "חדשה", "חדשות",
    "the", "and", "for", "from", "with", "after", "amid", "says", "report",
}

# Terms that are too generic to prove two flashes describe the same event by
# themselves.  They still participate in the overlap score, but the lower
# threshold below requires shared distinctive tokens as well.
GENERIC_BREAKING_TOKENS = {
    "משטרה", "צה", "ישראל", "איראן", "ארה", "חמאס", "חיזבאללה", "לבנון",
    "תוקפים", "תקף", "תקיפה", "תקיפות", "נעצר", "נפצע", "פיגוע", "אזעקות",
    "police", "israel", "iran", "strike", "strikes", "attack", "attacks",
}


def normalize_token(token: str) -> str:
    token = token.strip()
    if len(token) > 3 and token[0] in "בלוהמ":
        token = token[1:]
    if len(token) > 3 and token.startswith("ה"):
        token = token[1:]
    # Normalize common terse-breaking synonyms so same diplomatic flashes from
    # Rotter/Ynet/Walla collapse even when one headline says "מו״מ" and another
    # says "עסקה", or "אקבל" vs "לקבל".  Keep this narrow to avoid merging
    # adjacent Iran/Trump analysis items such as oil-market or Hormuz impacts.
    synonym_map = {
        "אקבל": "קבל",
        "אקיים": "קיים",
        "לקבל": "קבל",
        "עסקה": "מומ",
        "העסקה": "מומ",
        # Breaking accident flashes often disagree on municipality wording or
        # early age reports.  Hosen is adjacent to Ma'alot-Tarshiha, and Hebrew
        # prefix stripping turns "מעלות" into "עלות"; normalize the locality so
        # updates from Ynet/Walla/Rotter about the same ATV incident collapse.
        "חוסן": "מעלות_חוסן",
        "תרשיחא": "מעלות_חוסן",
        "עלות": "מעלות_חוסן",
        # Fatal road-crash flashes around the same incident can move from
        # "Kochav Michael" to the nearby Givati junction and from "critically
        # injured" to "death determined".  Normalize the locality/status words
        # so מבזקים keeps one updated live card instead of parallel same-crash
        # cards from Ynet/Walla/Rotter.
        "כוכב": "כוכב_מיכאל_גבעתי",
        "מיכאל": "כוכב_מיכאל_גבעתי",
        "גבעתי": "כוכב_מיכאל_גבעתי",
        # Same fatal road crash near Kiryat Gat can be reported by exact junction
        # (Nir Banim) or nearby city/area. Normalize both so Rotter/Ynet/Maariv
        # flashes collapse into one live accident card instead of duplicates.
        "ניר": "ניר_בנים_קריית_גת",
        "נים": "ניר_בנים_קריית_גת",
        "בנים": "ניר_בנים_קריית_גת",
        "גת": "ניר_בנים_קריית_גת",
        "מותה": "מוות",
        "מותו": "מוות",
        "נהרגה": "מוות",
        "נהרג": "מוות",
        "הרוגה": "מוות",
        "הרוג": "מוות",
        "רוג": "מוות",
        # Building-fire flashes often split between rescue count and smoke-injury
        # count.  Normalize the inflected fire token so same-location building
        # fires collapse into one breaking card with source links.
        "שריפת": "שריפה",
        # Home Front Command education/activity restriction flashes can be
        # phrased as "אין לימודים" by one source and "ביטול פעילות חינוכית"
        # by another.  Normalize the education/action words so the narrow rule
        # below can merge same-event northern-front instruction updates.
        "לימודים": "חינוך_קו_עימות",
        "ימודים": "חינוך_קו_עימות",
        "פעיליות": "חינוך_קו_עימות",
        "פעילויות": "חינוך_קו_עימות",
        "חינוכית": "חינוך_קו_עימות",
        "חינוך": "חינוך_קו_עימות",
        # Iranian-president resignation flashes vary between transliteration,
        # first name, and verb forms (ביקש/מבקש/להתפטר/לסיים תפקיד).
        "פזשכיאן": "נשיא_איראן",
        "מסעוד": "נשיא_איראן",
        "איראן": "איראן",
        "איראנית": "איראן",
        "בקש": "התפטרות",
        "יקש": "התפטרות",
        "תפטר": "התפטרות",
        "סיים": "התפטרות",
        "תפקידו": "תפקיד",
        # Crime flashes around the same village can vary between the local
        # authority and the nearby city.  Normalize Kaabiya/Shfar'am so a terse
        # Walla/Rotter murder flash and a Ynet vehicle-shooting update collapse.
        "כעביה": "כעביה_שפרעם",
        "שפרעם": "כעביה_שפרעם",
        # Tiberias/northern-front alert follow-ups can shift from a siren alert
        # to MDA/no-casualty or rocket-impact status wording.  Normalize the
        # inflected launch terms for the narrow city-alert rule below.
        "שיגור": "שיגור",
        "שיגורים": "שיגור",
        "השיגורים": "שיגור",
        # Dahieh/Beirut evacuation warnings are often published as several
        # terse flashes within minutes: one says "אזהרת פינוי", another says
        # "קורא להתפנות", and Rotter/Walla disagree on דאחיה/דאחייה spelling.
        # Normalize these anchors so the breaking feed shows one live incident
        # with source links instead of three same-event cards.
        "דאחיה": "דאחייה_ביירות",
        "דאחייה": "דאחייה_ביירות",
        "ביירות": "דאחייה_ביירות",
        "יירות": "דאחייה_ביירות",
        "פקדות": "מפקדת_חיזבאללה",
        "פקדה": "מפקדת_חיזבאללה",
        "פקדת": "מפקדת_חיזבאללה",
        "מפקדות": "מפקדת_חיזבאללה",
        "מפקדה": "מפקדת_חיזבאללה",
        "מפקדת": "מפקדת_חיזבאללה",
        "זירת": "זירת_תקיפה",
        "התקיפה": "תקיפה_ביירות",
        "תקיפה": "תקיפה_ביירות",
        "התקיפות": "תקיפה_ביירות",
        "תקיפות": "תקיפה_ביירות",
        # Trump/Iran ceasefire-agreement flashes can arrive as ``הסכם עם איראן``
        # in one source and ``הארכת הפסקת האש עם איראן`` in another.  Normalize
        # only the agreement/ceasefire anchors; the near-duplicate rule below
        # still requires Trump + Iran + near-term timing so oil/sanctions/strike
        # items are not collapsed into the same live event.
        "הסכם": "הסכם_הפסקת_אש",
        "הסכמים": "הסכם_הפסקת_אש",
        "ארכת": "הסכם_הפסקת_אש",
        "הארכת": "הסכם_הפסקת_אש",
        "הפסקת": "הסכם_הפסקת_אש",
        # Trump/Netanyahu/Beirut flashes vary between the direct quote, a
        # paraphrase, and Bibi/Netanyahu naming.  Normalize the actors/action so
        # the same diplomatic update is shown once with multiple source links.
        "ביבי": "נתניהו",
        "יבי": "נתניהו",
        "פשיטה": "תקיפה_ביירות",
        "לתקוף": "תקיפה_ביירות",
        "תקיפה": "תקיפה_ביירות",
        "תקוף": "תקיפה_ביירות",
        "כניסה": "תקיפה_ביירות",
        "יקשתי": "ביקשתי",
        "פנה": "הפנה",
        "פינוי": "פינוי",
        "לפינוי": "פינוי",
        "להתפנות": "פינוי",
        "תפנות": "פינוי",
        # Yafia/Nazareth murder flashes can arrive as separate terse updates:
        # early shooting/injury near Nazareth, death determined, and a named
        # Yafia double-murder flash.  Normalize locality and casualty wording so
        # מבזקים shows one evolving incident with source links.
        "יפיע": "יפיע_נצרת",
        "נצרת": "יפיע_נצרת",
        "נורו": "ירי_מוות",
        "שנורו": "ירי_מוות",
        "נורה": "ירי_מוות",
        "נרצח": "ירי_מוות",
        "נרצחו": "ירי_מוות",
        "רצח": "ירי_מוות",
        "מותם": "ירי_מוות",
        "ותם": "ירי_מוות",
        # Northern UAV alert waves can appear first as a suspected infiltration
        # in the Galilee/Finger-of-Galilee and later as an interception/fallout
        # update naming Margaliot/Misgav Am. Normalize the locality and UAV
        # status anchors so מבזקים shows one evolving alert event.
        "אצבע": "אצבע_הגליל_כטבם",
        "הגליל": "אצבע_הגליל_כטבם",
        "גליל": "אצבע_הגליל_כטבם",
        "מרגליות": "אצבע_הגליל_כטבם",
        "משגב": "אצבע_הגליל_כטבם",
        "יורט": "יירוט_כטבם",
        "יורטו": "יירוט_כטבם",
        "התפוצצו": "יירוט_כטבם",
        "חדירת": "חדירת_כטבם",
        # Hormuz drone/radar escalation flashes can split between a Rotter-style
        # intercepted-drone report and a Walla/Ynet radar-site strike update.
        # Keep the anchors narrow: Hormuz + Iran + UAV/drone/interception.
        "הורמוז": "הורמוז_כטבם",
        "ורמוז": "הורמוז_כטבם",
        "מצר": "הורמוז_כטבם",
        "מכ\"ם": "מכמים",
        "מכמים": "מכמים",
        "יירטו": "יירוט_כטבם",
        # Trump/Iran missile-capability estimates may be phrased as 20%,
        # 21%-22%, or one fifth. Normalize percentage/capability anchors.
        "יכולות": "יכולת_טילים_כטבמים",
        "יכולת": "יכולת_טילים_כטבמים",
        "הטילים": "טילים",
        "טילים": "טילים",
        "20": "חמישית_יכולת",
        "21": "חמישית_יכולת",
        "22": "חמישית_יכולת",
        "חמישית": "חמישית_יכולת",
    }
    token = synonym_map.get(token, token)
    return token


def normalize_for_dupe(title: str) -> str:
    text = re.sub(r"[\"'׳״`]+", "", title.lower())
    text = re.sub(r"כטב[\"׳״]?ם", "כטבם", text)
    text = re.sub(r"[^0-9A-Za-z\u0590-\u05ff]+", " ", text)
    words = [normalize_token(w) for w in text.split()]
    return " ".join(w for w in words if len(w) > 1 and w not in DUPE_STOPWORDS)


def token_set(title: str) -> set[str]:
    return set(normalize_for_dupe(title).split())


def distinctive_overlap(ta: set[str], tb: set[str]) -> set[str]:
    return {t for t in (ta & tb) if t not in GENERIC_BREAKING_TOKENS and len(t) > 2}


def near_duplicate(a: str, b: str) -> bool:
    """Conservative semantic dedupe for breaking-news flashes.

    Breaking items are intentionally terse, so exact-title/URL dedupe misses the
    common case where Walla/Ynet/Rotter publish the same event with slightly
    different wording.  Use a high normal overlap first, then a lower threshold
    only when several distinctive tokens match.  This collapses same-event
    multi-source flashes while preserving adjacent developments.
    """
    ta, tb = token_set(a), token_set(b)
    if not ta or not tb:
        return False
    shared = ta & tb
    overlap = len(shared) / max(1, min(len(ta), len(tb)))
    if overlap >= 0.72:
        return True
    distinct = distinctive_overlap(ta, tb)
    if overlap >= 0.58 and len(distinct) >= 3:
        return True
    if overlap >= 0.44 and len(distinct) >= 4:
        return True
    # Same breaking accident/attack updates can change from an initial terse
    # alert to MDA casualty counts while preserving the concrete event.
    # Keep these narrow: shared locality + same event class + injury signal.
    if {"תאונת", "טרקטורון", "מעלות_חוסן"} <= shared and "בן" in shared:
        return True
    road_crash_terms = {"תאונה", "תאונת", "דרכים", "רכבים", "כביש", "כבישים", "צומת", "משאית", "שאית", "פגיעת"}
    casualty_update_terms = {"נפצעה", "נפצע", "נפצעו", "אנוש", "קשה", "מוות", "הרוגה", "פצועים"}
    if "כוכב_מיכאל_גבעתי" in shared and (ta & road_crash_terms) and (tb & road_crash_terms) and (ta & casualty_update_terms) and (tb & casualty_update_terms):
        return True
    if "ניר_בנים_קריית_גת" in shared and (ta & road_crash_terms) and (tb & road_crash_terms) and (ta & casualty_update_terms) and (tb & casualty_update_terms):
        return True
    gush_terms = {"גוש", "עציון", "צומת"}
    injury_terms = {"פצועים", "פצוע", "נפצעה", "נפצע", "קשה", "מחבל", "נוטרל"}
    ramming_terms = {"פיגוע", "דריסה"}
    if "גוש" in shared and (ta & ramming_terms) and (tb & ramming_terms) and (ta & injury_terms) and (tb & injury_terms):
        return True
    if "פיגוע" in shared and "גוש" in shared and ((ta & {"עציון", "צומת"}) or (tb & {"עציון", "צומת"})) and (ta & injury_terms) and (tb & injury_terms):
        return True
    # Follow-up Gush Etzion ramming flashes can split the event wording: one
    # source says the soldier neutralized the terrorist at ``צומת הגוש`` and a
    # second source gives the MDA injury status under ``פיגוע דריסה בגוש עציון``.
    # Treat shared Gush + terrorist/attack + casualty/status tokens as one live
    # incident, otherwise the breaking feed shows the same attack twice.
    attack_terms = {"פיגוע", "דריסה", "מחבל", "נטרל", "נוטרל"}
    if "גוש" in shared and (ta & {"צומת", "עציון"}) and (tb & {"צומת", "עציון"}) and (ta & attack_terms) and (tb & attack_terms) and (ta & injury_terms) and (tb & injury_terms):
        return True
    # Very short alert wording: one source may say "אזעקות בגליל המערבי" while
    # another adds the suspected drone and locality.  Shared location + alert
    # intent is enough, but only for this narrow alert/drone class.
    alert_terms = {"אזעק", "אזעקה", "אזעקות", "תרעות", "כטבם", "כטבמים", "חדירת", "גליל", "מערבי", "נטועה", "צפת"}
    if len(shared & alert_terms) >= 2 and ({"אזעק", "אזעקה", "אזעקות"} & shared):
        return True
    if ({"אזעק", "אזעקה", "אזעקות"} & shared) and ({"גליל", "מערבי"} <= ta or {"גליל", "מערבי"} <= tb) and ("נטועה" in ta or "נטועה" in tb or "כטבם" in ta or "כטבם" in tb):
        return True
    # Same-location northern alert updates can vary between "צה״ל נערך לירי"
    # and the concrete siren/drone/rocket wording.  Collapse only when the city
    # and alert+fire signal are both shared, so unrelated northern-security
    # analysis is not merged.
    city_alert_terms = {"אזעק", "אזעקה", "אזעקות", "תרעות", "התרעות", "חדירת", "כטבם", "כטבמים", "רקטות"}
    northern_alert_cities = {"צפת", "נהריה", "משגב", "מטולה", "שלומי", "קריית", "שמונה"}
    if (shared & northern_alert_cities) and (ta & city_alert_terms) and (tb & city_alert_terms):
        return True
    if "צפת" in shared and "ירי" in shared and (ta & city_alert_terms) and (tb & city_alert_terms):
        return True
    # "קריית שמונה" alerts and broader "אצבע הגליל" alerts often describe
    # the same siren wave minutes apart.  Collapse only when both sides are
    # alert flashes, not general northern-front analysis.
    if ({"אזעק", "אזעקה", "אזעקות"} & shared) and (({"קריית", "שמונה"} <= ta and {"אצבע", "גליל"} <= tb) or ({"קריית", "שמונה"} <= tb and {"אצבע", "גליל"} <= ta)):
        return True
    # Same Home Front Command restriction update can appear as schools canceled
    # in conflict-line towns vs educational activity canceled after escalation.
    if {"פיקוד", "עורף", "עימות", "חינוך_קו_עימות"} <= shared:
        return True
    # Same public-figure reaction to a northern-front escalation can arrive as
    # two terse flashes: one source quotes the accusation ("תושבי הצפון
    # מופקרים") and another quotes the demanded response ("הדאחייה צריכה
    # לרעוד").  Collapse only this narrow Bennett+north reaction shape so
    # unrelated political items by the same actor remain separate.
    north_terms = {"צפון", "צפוני", "צפונית"}
    if "בנט" in shared and (ta & north_terms) and (tb & north_terms):
        return True
    if {"נשיא", "איראן", "התפטרות"} <= (ta & tb) and ("תפקיד" in ta or "תפקיד" in tb):
        return True
    fire_terms = {"שריפה", "עשן", "לכודים", "נפגעים"}
    if "בניין" in shared and "לוד" in shared and bool((ta & fire_terms) and (tb & fire_terms)):
        return True
    # Same local murder/shooting near Kaabiya/Shfar'am can appear as a named
    # village death, a murder, or a nearby-city vehicle shooting.  Require the
    # normalized locality plus death/shooting terms so unrelated crime flashes
    # in the Galilee are not merged.
    death_terms = {"נהרג", "נרצח", "נורה", "מוות", "ירי_מוות"}
    if "כעביה_שפרעם" in shared and (ta & death_terms) and (tb & death_terms):
        return True
    # Same Yafia/Nazareth double-murder incident: one source may say two young
    # men were shot near Nazareth, another says their deaths were determined,
    # and a third names Yafia.  Collapse only when both sides share the
    # normalized locality and shooting/death anchor.
    if "יפיע_נצרת" in shared and (ta & death_terms) and (tb & death_terms):
        return True
    # Same Jerusalem crime/violence flash can split between one source reporting
    # a serious shooting injury and another reporting the MDA casualty count for
    # the same violent incident. Require Jerusalem + severe injury + explicit
    # crime/violence terms so unrelated municipal updates are not merged.
    jerusalem_terms = {"ירושלים", "צור", "באהר"}
    serious_injury_terms = {"נפצע", "נפצעו", "פצוע", "פצועים", "קשה"}
    violence_terms = {"ירי", "מירי", "אלימות", "פלילי", "פלילית"}
    if (shared & jerusalem_terms) and (ta & serious_injury_terms) and (tb & serious_injury_terms) and (ta & violence_terms) and (tb & violence_terms):
        return True
    # Northern UAV alert/interception same-event updates: early suspected
    # infiltration vs later interception/fallout wording. Require the normalized
    # Galilee locality plus UAV/alert/status terms so unrelated northern events
    # are not merged.
    uav_terms = {"כטבם", "כטבמים", "חדירת_כטבם", "יירוט_כטבם", "אזעק", "אזעקה", "אזעקות", "תרעות", "התרעות"}
    if "אצבע_הגליל_כטבם" in shared and (ta & uav_terms) and (tb & uav_terms):
        return True
    if ({"אזעק", "אזעקה", "אזעקות"} & (ta | tb)) and "אצבע_הגליל_כטבם" in (ta | tb) and (ta & uav_terms) and (tb & uav_terms) and ((ta & {"מערבי", "נטועה"}) or (tb & {"מערבי", "נטועה"}) or ({"קריית", "שמונה"} <= ta) or ({"קריית", "שמונה"} <= tb)):
        return True
    # Hormuz drone/radar escalation variants: one terse flash may mention only
    # UAVs intercepted over Hormuz while another includes U.S. radar strikes.
    if "הורמוז_כטבם" in shared and (ta & {"כטבם", "כטבמים", "יירוט_כטבם", "מכמים"}) and (tb & {"כטבם", "כטבמים", "יירוט_כטבם", "מכמים"}) and (("איראן" in (ta | tb)) or ("ארהב" in (ta | tb))):
        return True
    # Trump/Iran remaining missile/UAV capability estimates are one live quote
    # even when one source says 20% and another says 21%-22%.
    if {"טראמפ", "איראן", "טילים"} <= shared and (("יכולת_טילים_כטבמים" in ta or "יכולת_טילים_כטבמים" in tb) or ("חמישית_יכולת" in ta and "חמישית_יכולת" in tb)) and (("כטבם" in ta or "כטבמים" in ta or "כטבם" in tb or "כטבמים" in tb) or "חמישית_יכולת" in shared):
        return True
    # Tiberias rocket/siren waves often arrive first as an alert and then as an
    # MDA/no-casualty or impact-status flash.  Collapse only same-city northern
    # launch/alert updates, preserving separate analysis about Lebanon.
    tiberias_alert_terms = {"אזעק", "אזעקה", "אזעקות", "שיגור", "נפגעים", "מדא"}
    if "טבריה" in shared and (ta & tiberias_alert_terms) and (tb & tiberias_alert_terms):
        return True
    # Same IDF/Dahieh evacuation warning: collapse Walla/Ynet/Rotter variants
    # and same-source Rotter repeats while preserving later concrete strike or
    # casualty updates as separate flashes.
    dahiya_terms = {"דאחייה_ביירות", "פינוי"}
    idf_warning_terms = {"צה", "דובר", "אזהרת", "מזהיר", "קורא", "לראשונה", "הודעת"}
    if dahiya_terms <= shared and (ta & idf_warning_terms) and (tb & idf_warning_terms):
        return True
    # Same Dahieh strike wave: initial "IDF strikes", command-center target,
    # and scene-video flashes from the same source/source family are one live
    # breaking incident. Keep this narrow to Dahieh/Beirut + strike + Hezbollah/IDF
    # targeting language so evacuation warnings and later casualty updates can
    # remain separate when they add a distinct event.
    dahiya_strike_terms = {"תקיפה_ביירות", "תקף", "תוקף", "תוקפים", "זירת_תקיפה"}
    dahiya_target_terms = {"מפקדת_חיזבאללה", "חיזבאללה", "צה", "צהל"}
    if "דאחייה_ביירות" in shared and (ta & dahiya_strike_terms) and (tb & dahiya_strike_terms) and ((ta & dahiya_target_terms) or (tb & dahiya_target_terms)):
        return True
    # Same Trump/Iran near-term ceasefire/agreement flash: one source can report
    # ``הסכם עם איראן בשבוע הבא`` while another says ``הארכת הפסקת האש``.
    # Require Trump + Iran + the agreement anchor + near-term timing to avoid
    # collapsing distinct sanctions, oil-market, or military-strike developments.
    near_time_terms = {"שבוע", "הבא", "בקרוב"}
    if {"טראמפ", "איראן", "הסכם_הפסקת_אש"} <= shared and (ta & near_time_terms) and (tb & near_time_terms):
        return True
    # Israel/Lebanon ceasefire flashes can split between a concise Walla-style
    # agreement headline and a Ynet-style condition headline about Hezbollah
    # withdrawing/holding fire.  Collapse only when both sides share the Israel +
    # Lebanon + ceasefire/agreement anchors so unrelated Lebanon fighting or
    # diplomacy items remain separate.
    lebanon_ceasefire_terms = {"הסכם_הפסקת_אש", "סכם", "סכימו", "פסקת", "האש", "אש"}
    if {"ישראל", "לבנון"} <= shared and (ta & lebanon_ceasefire_terms) and (tb & lebanon_ceasefire_terms):
        return True
    # Ben-Gvir/Lebanon ceasefire reaction flashes can split between a short
    # Ynet quote ("צריך לומר לא") and a Rotter variant adding a cabinet vote.
    # They are still the same live political reaction, not two breaking events.
    if {"בן", "גביר", "פסקת", "טעות"} <= shared and (("לבנון" in ta or "בנון" in ta) and ("לבנון" in tb or "בנון" in tb)):
        return True
    # Same Trump/Netanyahu Beirut de-escalation flash, phrased as a direct quote
    # by Rotter and as a paraphrased Walla/Ynet-style headline/context elsewhere.
    if {"טראמפ", "נתניהו", "דאחייה_ביירות"} <= shared and ((ta & {"ביקשתי", "ביקש", "שוחחתי", "שוחח"}) or (tb & {"ביקשתי", "ביקש", "שוחחתי", "שוחח"})) and ((ta & {"תקיפה_ביירות", "כוחותיו", "הפנה"}) or (tb & {"תקיפה_ביירות", "כוחותיו", "הפנה"})):
        return True
    return False


def same_source_building_fire_update(a: str, b: str) -> bool:
    ta, tb = token_set(a), token_set(b)
    shared = ta & tb
    fire_terms = {"שריפה", "עשן", "לכודים", "נפגעים"}
    return "בניין" in shared and "לוד" in shared and bool((ta & fire_terms) and (tb & fire_terms))


def same_source_gush_etzion_attack_update(a: str, b: str) -> bool:
    """Collapse same-source status updates for the Gush Etzion ramming attack."""
    ta, tb = token_set(a), token_set(b)
    shared = ta & tb
    injury_terms = {"פצועים", "פצוע", "נפצעה", "נפצע", "קשה", "מחבל", "נוטרל", "נטרל"}
    attack_terms = {"פיגוע", "דריסה", "מחבל", "נטרל", "נוטרל"}
    return "גוש" in shared and (ta & {"צומת", "עציון"}) and (tb & {"צומת", "עציון"}) and (ta & attack_terms) and (tb & attack_terms) and (ta & injury_terms) and (tb & injury_terms)


def same_source_tiberias_alert_update(a: str, b: str) -> bool:
    """Collapse same-source Tiberias alert/status updates for the same siren wave."""
    ta, tb = token_set(a), token_set(b)
    shared = ta & tb
    tiberias_alert_terms = {"אזעק", "אזעקה", "אזעקות", "שיגור", "נפגעים", "מדא"}
    return "טבריה" in shared and (ta & tiberias_alert_terms) and (tb & tiberias_alert_terms)


def same_source_road_crash_status_update(a: str, b: str) -> bool:
    """Collapse same-source fatality/status updates for one road crash."""
    ta, tb = token_set(a), token_set(b)
    shared = ta & tb
    road_crash_terms = {"תאונה", "תאונת", "דרכים", "רכבים", "כביש", "כבישים", "צומת", "משאית", "שאית", "פגיעת"}
    casualty_update_terms = {"נפצעה", "נפצע", "נפצעו", "אנוש", "קשה", "מוות", "הרוגה", "פצועים"}
    return "כוכב_מיכאל_גבעתי" in shared and (ta & road_crash_terms) and (tb & road_crash_terms) and (ta & casualty_update_terms) and (tb & casualty_update_terms)


def same_source_trump_iran_agreement_update(a: str, b: str) -> bool:
    """Collapse same-source Trump/Iran agreement/ceasefire near-term updates."""
    ta, tb = token_set(a), token_set(b)
    shared = ta & tb
    near_time_terms = {"שבוע", "הבא", "בקרוב"}
    agreement_terms = {"הסכם_הפסקת_אש", "סכם", "פסקת", "האש", "אש"}
    return {"טראמפ", "איראן"} <= shared and (ta & near_time_terms) and (tb & near_time_terms) and (ta & agreement_terms) and (tb & agreement_terms)


def same_source_northern_uav_alert_update(a: str, b: str) -> bool:
    """Collapse same-source northern UAV alert/interception status updates."""
    ta, tb = token_set(a), token_set(b)
    shared = ta & tb
    uav_terms = {"כטבם", "כטבמים", "חדירת_כטבם", "יירוט_כטבם", "אזעק", "אזעקה", "אזעקות", "תרעות", "התרעות"}
    return "אצבע_הגליל_כטבם" in shared and (ta & uav_terms) and (tb & uav_terms)


def same_source_fallen_soldier_update(a: str, b: str) -> bool:
    """Collapse same-source municipal/unit notices for the same fallen soldier."""
    ta, tb = token_set(a), token_set(b)
    shared = ta & tb
    fall_terms = {"נפילתו", "נפילתה", "נפל", "נפלה", "נפילת", "ז״ל", "זל"}
    soldier_terms = {"לוחם", "קצין", "סרן", "סמל", "גדוד", "סיירת", "אגוז", "שקד"}
    # Same named casualty, sometimes one title names the municipality and the
    # other the unit. Require name overlap + Lebanon + fall/soldier framing.
    name_overlap = len(shared & {"שחר", "גמלא", "אהד", "יערי"}) >= 2
    return name_overlap and "לבנון" in shared and (ta & fall_terms) and (tb & fall_terms) and (ta & soldier_terms) and (tb & soldier_terms)


def same_source_reordered_title_update(a: str, b: str) -> bool:
    """Collapse same-source flashes that contain the same distinctive words in a different order.

    Rotter and similar breaking feeds sometimes publish the same quote/update twice
    with only attribution order changed (for example adding/removing parentheses
    around the speaker's role).  Cross-source semantic dedupe already handles this,
    but same-source rows were intentionally conservative; this guard only collapses
    near-identical same-source wording when the normalized token sets are equal and
    sufficiently specific.
    """
    ta, tb = token_set(a), token_set(b)
    if len(ta) < 6 or len(tb) < 6:
        return False
    return ta == tb and len(distinctive_overlap(ta, tb)) >= 5


def same_source_dahiya_strike_update(a: str, b: str) -> bool:
    """Collapse same-source Dahieh strike/target/scene status flashes."""
    ta, tb = token_set(a), token_set(b)
    shared = ta & tb
    strike_terms = {"תקיפה_ביירות", "תקף", "תוקף", "תוקפים", "זירת_תקיפה"}
    target_terms = {"מפקדת_חיזבאללה", "חיזבאללה", "צה", "צהל"}
    return "דאחייה_ביירות" in shared and (ta & strike_terms) and (tb & strike_terms) and ((ta & target_terms) or (tb & target_terms))


def weak_speaker_only_title(title: str, context: str) -> bool:
    """Drop breaking rows that name only a speaker, without the actual update.

    Some feeds, especially Rotter, occasionally emit a title like
    ``*השר לביטחון לאומי, איתמר בן גביר:*`` and put no useful body in the RSS
    row. Publishing that as the top breaking card creates a broken-looking
    headline rather than news.
    """
    clean = clean_text(title).strip(" *\u200f\u200e")
    if context.strip():
        return False
    if clean.endswith(":") and len(clean) <= 90:
        return True
    if re.search(r"^(?:השר|חה.?כ|ראש הממשלה|שר(?:ת)?|דובר|יו.?ר)\b", clean) and len(clean.split()) <= 8 and not re.search(r"(אמר|הודיע|קרא|תקף|דרש|הזהיר|מסר)", clean):
        return True
    return False


def weak_truncated_title(title: str, context: str) -> bool:
    """Drop source-truncated breaking rows that end in ellipsis without context.

    Rotter and similar feeds sometimes cut long forum titles with ``...``.  In a
    breaking feed that becomes the entire visible card, so it violates Pointa's
    complete-thought rule and should not outrank real complete flashes.
    """
    clean = clean_text(title).strip()
    if context.strip():
        return False
    return bool(re.search(r"(?:\.\.\.|…)$", clean))


def should_keep(row: dict[str, Any], source: dict[str, Any]) -> bool:
    text = f"{row.get('headline','')} {row.get('context','')}"
    if weak_speaker_only_title(str(row.get("headline", "")), str(row.get("context", ""))):
        return False
    if weak_truncated_title(str(row.get("headline", "")), str(row.get("context", ""))):
        return False
    if any(re.search(p, text, re.I) for p in DROP_PATTERNS):
        return False
    if source.get("needsStrictFiltering") and not ROTTER_KEEP.search(text):
        return False
    return True


def build(sources_path: Path, output_path: Path, limit: int) -> dict[str, Any]:
    cfg = json.loads(sources_path.read_text(encoding="utf-8"))
    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for source in cfg.get("active", []):
        url = source.get("rss")
        if not url:
            continue
        try:
            rows = parse_rss(decode_payload(fetch_url(url)), source)
            items.extend(row for row in rows if should_keep(row, source))
        except Exception as exc:
            errors.append({"source": source.get("name", url), "error": str(exc)[:240]})

    items.sort(key=lambda r: r.get("publishedAt") or "", reverse=True)
    deduped: list[dict[str, Any]] = []
    def dupe_text(row: dict[str, Any]) -> str:
        return " ".join(str(row.get(key, "")) for key in ("headline", "context", "originalTitle"))

    for row in items:
        row_dupe_text = dupe_text(row)
        match = next(
            (
                x
                for x in deduped
                if x.get("sourceUrl") != row.get("sourceUrl")
                and (
                    near_duplicate(row_dupe_text, dupe_text(x))
                    if normalize_for_dupe(str(row.get("headline", ""))) == normalize_for_dupe(str(x.get("headline", "")))
                    else (x.get("source") != row.get("source") and near_duplicate(row_dupe_text, dupe_text(x)))
                    or same_source_building_fire_update(row_dupe_text, dupe_text(x))
                    or same_source_gush_etzion_attack_update(row_dupe_text, dupe_text(x))
                    or same_source_tiberias_alert_update(row_dupe_text, dupe_text(x))
                    or same_source_road_crash_status_update(row_dupe_text, dupe_text(x))
                    or same_source_trump_iran_agreement_update(row_dupe_text, dupe_text(x))
                    or same_source_northern_uav_alert_update(row_dupe_text, dupe_text(x))
                    or same_source_fallen_soldier_update(row_dupe_text, dupe_text(x))
                    or same_source_reordered_title_update(row_dupe_text, dupe_text(x))
                    or same_source_dahiya_strike_update(row_dupe_text, dupe_text(x))
                )
            ),
            None,
        )
        if match:
            sources = match.setdefault("sources", [match.get("source")])
            links = match.setdefault("sourceLinks", [{"name": match.get("source") or "מקור", "url": match.get("sourceUrl") or ""}])
            row_url = row.get("sourceUrl") or ""
            if row.get("source") and row.get("source") not in sources:
                sources.append(row.get("source"))
            if row_url and not any(link.get("url") == row_url for link in links):
                links.append({"name": row.get("source") or "מקור", "url": row_url})
            continue
        deduped.append(row)
        if len(deduped) >= limit:
            break

    out = {
        "updatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "breaking",
        "ttlHours": 12,
        "items": deduped,
        "sources": [s.get("name") for s in cfg.get("active", [])],
        "errors": errors,
    }
    output_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=80)
    args = parser.parse_args(argv)
    out = build(args.sources, args.output, args.limit)
    print(f"breaking_feed: {len(out['items'])} items, {len(out['errors'])} source errors -> {args.output}")
    if out["errors"]:
        for err in out["errors"]:
            print(f"WARN {err['source']}: {err['error']}", file=sys.stderr)
    return 0 if out["items"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
