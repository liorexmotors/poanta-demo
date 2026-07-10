#!/usr/bin/env python3
"""Poenta image-bank matching helpers.

The image bank is intentionally illustrative.  Matching is based on the spirit
of the article: category, summary, headline, original title, and bank metadata.
It does not use or preserve RSS source images.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "assets" / "poenta-image-bank" / "catalog.json"
DEFAULT_PUBLIC_BASE = "https://poanta-demo.pages.dev/assets/poenta-image-bank/"

STOPWORDS = {
    "של",
    "על",
    "את",
    "עם",
    "לא",
    "כי",
    "זה",
    "זו",
    "הוא",
    "היא",
    "הם",
    "הן",
    "גם",
    "או",
    "אם",
    "כל",
    "יש",
    "אין",
    "אל",
    "עד",
    "בו",
    "בה",
    "בין",
    "אחרי",
    "לפני",
    "יותר",
    "פחות",
    "היום",
    "מחר",
    "אתמול",
    "חדש",
    "חדשה",
    "כתבה",
    "דיווח",
    "לפי",
    "פורסם",
    "מקור",
    "חדשות",
    "פואנטה",
    "אילוסטרציה",
}

CATEGORY_HINTS = {
    "ביטחון": ["ביטחון", "מלחמה", "גבול", "עורף", "ים", "סייבר"],
    "פלילים": ["פלילים", "משטרה", "חקירה", "משפט"],
    "משפט": ["משפט", "בית משפט", "חקירה", "מסמכים"],
    "פוליטיקה": ["פוליטיקה", "כנסת", "ממשלה", "ועדה"],
    "כלכלה": ["כלכלה", "מחירים", "עסקים", "בורסה", "כסף"],
    "צרכנות": ["צרכנות", "סופר", "קניות", "מחירים"],
    "טכנולוגיה": ["טכנולוגיה", "סייבר", "דיגיטל", "AI", "מסכים"],
    "רכב": ["תחבורה", "רכב", "כביש", "פקקים"],
    "תחבורה": ["תחבורה", "כביש", "רכבת", "פקקים"],
    "בריאות": ["בריאות", "רפואה", "בית חולים", "תרופה"],
    "מזג אוויר": ["מזג אוויר", "גשם", "חום", "סערה"],
    "ספורט": ["ספורט", "אצטדיון", "מגרש", "אימון"],
    "תרבות": ["תרבות", "מוזיקה", "קולנוע", "במה"],
    "רכילות": ["תרבות", "אולפן", "בידור", "מדיה"],
    "נדל״ן": ["נדל", "דיור", "בנייה", "רחוב"],
    "נדל\"ן": ["נדל", "דיור", "בנייה", "רחוב"],
    "אקטואליה בעולם": ["עולם", "ביטחון", "מדיניות", "עיר"],
    "חדשות": ["מהיר", "עיר", "זירה ציבורית", "חדשות"],
}


def _normalize(text: Any) -> str:
    text = str(text or "").lower()
    text = text.replace("״", '"').replace("׳", "'")
    text = re.sub(r"[^\w\u0590-\u05ff\"'-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: Any) -> set[str]:
    words = re.findall(r"[a-z][a-z0-9'-]{2,}|[\u0590-\u05ff][\u0590-\u05ff\"'-]{2,}", _normalize(text))
    return {w.strip("\"'-") for w in words if len(w.strip("\"'-")) >= 3 and w not in STOPWORDS}


def item_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in (
            "category",
            "categoryClass",
            "headline",
            "title",
            "originalTitle",
            "summary",
            "context",
            "takeaway",
            "source",
        )
    )


def record_text(record: dict[str, Any]) -> str:
    return " ".join(
        str(record.get(key) or "")
        for key in (
            "speed_he",
            "domain_he",
            "topic_he",
            "title_he",
            "description_he",
            "keywords_he",
        )
    )


@lru_cache(maxsize=4)
def load_catalog(path: str | None = None) -> tuple[dict[str, Any], ...]:
    catalog_path = Path(path) if path else DEFAULT_CATALOG
    if not catalog_path.exists():
        return ()
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return ()
    out: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        if not row.get("file_name"):
            continue
        row = dict(row)
        row["_tokens"] = tokens(record_text(row))
        out.append(row)
    return tuple(out)


def _category_terms(category: str) -> set[str]:
    hints = CATEGORY_HINTS.get(category or "", [])
    return tokens(" ".join([category or "", *hints]))


def default_image_kind(item: dict[str, Any]) -> str:
    blob = _normalize(item_text(item))
    if "מזג" in blob:
        return "weather"
    if any(term in blob for term in ("ביטחון", "צבא", "חמאס", "איראן", "חיזבאללה", "עזה")):
        return "security"
    if any(term in blob for term in ("פוליט", "ממשלה", "כנסת", "בגץ", "בג\"ץ")):
        return "politics"
    if any(term in blob for term in ("כלכלה", "בורסה", "עסקים", "נדל")):
        return "economy"
    if any(term in blob for term in ("טכנולוג", "הייטק", "ai")):
        return "tech"
    if "ספורט" in blob:
        return "sports"
    if any(term in blob for term in ("תרבות", "בידור", "רכילות")):
        return "culture"
    if any(term in blob for term in ("עולם", "global", "jazeera", "bbc", "reuters", "france24")):
        return "world"
    if any(term in blob for term in ("מקומי", "עירוני", "רכב", "תחבורה")):
        return "local"
    return "news"


def match_image_bank_item(
    item: dict[str, Any],
    catalog: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
    *,
    min_score: float = 4.0,
) -> dict[str, Any] | None:
    catalog = catalog if catalog is not None else load_catalog()
    if not catalog:
        return None

    category = str(item.get("category") or "")
    source_tokens = tokens(item_text(item))
    category_tokens = _category_terms(category)
    query_tokens = source_tokens | category_tokens
    if not query_tokens:
        return None

    best: tuple[float, dict[str, Any], list[str]] | None = None
    for record in catalog:
        record_tokens = set(record.get("_tokens") or tokens(record_text(record)))
        overlap = query_tokens & record_tokens
        if not overlap:
            continue
        score = float(len(overlap))
        domain = str(record.get("domain_he") or "")
        topic = str(record.get("topic_he") or "")
        title = str(record.get("title_he") or "")
        if category and category in domain:
            score += 5
        if category and category in topic:
            score += 3
        if category_tokens & record_tokens:
            score += min(5, len(category_tokens & record_tokens))
        if source_tokens & tokens(title):
            score += 4
        if "ביטחון" in category and "ביטחון" not in domain:
            score -= 3
        if "ספורט" in category and "ספורט" not in record_text(record):
            score -= 3
        if "רכילות" in category and not any(x in record_text(record) for x in ("תרבות", "בידור", "מדיה", "אולפן")):
            score -= 2
        if best is None or score > best[0]:
            best = (score, record, sorted(overlap)[:12])

    if best is None or best[0] < min_score:
        return None
    score, record, overlap = best
    result = dict(record)
    result["matchScore"] = round(score, 2)
    result["matchSignals"] = overlap
    return result


def image_url_for_record(record: dict[str, Any], public_base: str = DEFAULT_PUBLIC_BASE) -> str:
    explicit = str(record.get("image_url") or "").strip()
    if explicit:
        return explicit
    return public_base.rstrip("/") + "/" + str(record.get("file_name") or "").strip()


def apply_image_bank_to_item(
    item: dict[str, Any],
    catalog: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
    *,
    min_score: float = 4.0,
    public_base: str = DEFAULT_PUBLIC_BASE,
) -> tuple[dict[str, Any], dict[str, Any]]:
    fixed = dict(item)
    match = match_image_bank_item(fixed, catalog, min_score=min_score)
    if match:
        fixed["imageUrl"] = image_url_for_record(match, public_base)
        fixed["imageBankKey"] = match.get("key")
        fixed["imageBankTitle"] = match.get("title_he")
        fixed["imageBankMatchScore"] = match.get("matchScore")
        fixed["imageBankMatchSignals"] = match.get("matchSignals")
        fixed.pop("imageFallbackKind", None)
        return fixed, {"status": "matched", "match": match}

    kind = default_image_kind(fixed)
    fixed["imageUrl"] = f"https://poanta-demo.pages.dev/assets/feed-defaults/{kind}.png"
    fixed["imageFallbackKind"] = kind
    fixed["imageBankMissing"] = True
    return fixed, {"status": "missing", "fallbackKind": kind}
