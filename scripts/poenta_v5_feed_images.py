#!/usr/bin/env python3
"""Assign reviewed V5 image-bank assets to newly published feed cards.

Production policy:
* exact domain match is mandatory;
* prefer 4/4, then 3/4, then temporary 2/4 or 1/4;
* never use the original article image;
* every temporary assignment immediately creates a replacement-image demand;
* use a same-domain general fallback when no tag overlaps;
* rotate away from images already assigned four times in the last 24 hours;
* copy only selected, QA-approved files into the public assets tree.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import fcntl
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
V5_ROOT = ROOT / "generated/poenta-image-bank-v2/unified-image-sets-v5"
SETS_PATH = V5_ROOT / "sets-and-images.json"
STATE_PATH = V5_ROOT / "generation-state.json"
LIVE_DEMAND_PATH = V5_ROOT / "live-image-demand.json"
LIVE_DEMAND_LOCK = V5_ROOT / "live-image-demand.lock"
PUBLIC_DIR = ROOT / "assets/poenta-image-bank-v5"
PUBLIC_BASE = "https://poanta-demo.pages.dev/assets/poenta-image-bank-v5"
POENTA_WATERMARK = ROOT / "assets/poenta-logo-watermark-transparent.png"
POENTA_WATERMARK_SUFFIX = "-poenta-v1"
DOMAIN_DEFAULT_DIR = ROOT / "assets/poenta-domain-defaults"
EMERGENCY_FALLBACK_FILE = ROOT / "assets/feed-defaults/news.png"
DOMAIN_DEFAULT_FILES = {
    "אקטואליה בעולם": "world.png",
    "ביטחון": "security.png",
    "בריאות": "health.png",
    "חדשות": "news.png",
    "חינוך": "education.png",
    "טכנולוגיה": "tech.png",
    "כלכלה": "economy.png",
    "מזג אוויר": "weather.png",
    "משפט": "law.png",
    'נדל"ן': "real-estate.png",
    "ספורט": "sports.png",
    "פוליטיקה": "politics.png",
    "פלילים": "crime.png",
    "צרכנות": "consumer.png",
    "רכב": "cars.png",
    "רכילות": "gossip.png",
    "תחבורה": "transport.png",
    "תרבות": "culture.png",
}

SPORT_SUBTYPE_TERMS = {
    "football": ("כדורגל", "מונדיאל", "ליגת האלופות", "פיפא", "פיפ״א", "פיפ\"א"),
    "basketball": ("כדורסל", "nba", "יורוליג", "נקודות", "ריבאונדים", "לברון"),
    "tennis": ("טניס", "ווימבלדון", "רולאן גארוס", "ג׳וקוביץ", "סינר", "אלקראס"),
    "motorsport": ("פורמולה", "גרנד פרי", "פול פוזישן", "מרצדס", "מקלארן"),
    "cycling": ("אופניים", "טור דה פראנס", "פוגצ׳אר"),
    "swimming": ("שחייה", "שחיין", "שחיינית", "מטר חופשי"),
    "water_polo": ("כדורמים",),
    "hockey": ("הוקי",),
}


def canonical(value: Any) -> str:
    return " ".join(str(value or "").strip().replace("״", '"').split()).lower()


def unique_tags(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        tag = canonical(value)
        if tag and tag not in out:
            out.append(tag)
    return out


def sport_subtype_from_text(value: Any) -> str:
    text = canonical(value)
    for subtype, terms in SPORT_SUBTYPE_TERMS.items():
        if any(canonical(term) in text for term in terms):
            return subtype
    return ""


def article_sport_subtype(item: dict[str, Any]) -> str:
    return sport_subtype_from_text(
        " ".join(
            str(item.get(key) or "")
            for key in ("headline", "title", "originalTitle", "context", "summary", "imageTags")
        )
    )


def image_sport_subtype(image: dict[str, Any]) -> str:
    return sport_subtype_from_text(
        " ".join(
            [
                str(image.get("tags") or ""),
                str(image.get("file") or ""),
                str(image.get("setCode") or ""),
            ]
        )
    )


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _approved_image(
    *,
    image_id: str,
    set_code: str,
    domain: Any,
    tags: Any,
    source: Any,
    origin: str,
) -> dict[str, Any] | None:
    file_path = Path(str(source or ""))
    clean_tags = unique_tags(tags or [])
    clean_domain = canonical(domain)
    if not image_id or not clean_domain or not 1 <= len(clean_tags) <= 4 or not file_path.is_file():
        return None
    return {
        "imageId": image_id,
        "setCode": set_code,
        "domain": clean_domain,
        "tags": clean_tags,
        "file": str(file_path.resolve()),
        "origin": origin,
        "status": "approved",
    }


def build_catalog() -> list[dict[str, Any]]:
    """Return the current reviewed catalog from the 1,638-set V5 source."""
    sets_payload = _read(SETS_PATH, {})
    state_payload = _read(STATE_PATH, {})
    catalog: list[dict[str, Any]] = []
    seen: set[str] = set()

    for image_set in sets_payload.get("sets", []):
        set_code = str(image_set.get("setCode") or "")
        for index, image in enumerate(image_set.get("images") or [], start=1):
            if image.get("status") not in {None, "", "approved"}:
                continue
            image_id = str(image.get("imageId") or f"{set_code}-EX-{index:02d}")
            row = _approved_image(
                image_id=image_id,
                set_code=set_code,
                domain=image_set.get("domain"),
                tags=image.get("tags") or image_set.get("tags"),
                source=image.get("file") or image.get("source"),
                origin="existing-v5",
            )
            if row and image_id not in seen:
                seen.add(image_id)
                catalog.append(row)

    for set_code, item in state_payload.get("items", {}).items():
        if item.get("status") != "approved" or item.get("qaDecision") != "approved":
            continue
        image_id = "V5-" + hashlib.sha256(str(set_code).encode()).hexdigest()[:14].upper()
        row = _approved_image(
            image_id=image_id,
            set_code=str(set_code),
            domain=item.get("domain"),
            tags=item.get("tags"),
            source=item.get("file"),
            origin="generated-v5",
        )
        if row and image_id not in seen:
            seen.add(image_id)
            catalog.append(row)
    return sorted(catalog, key=lambda row: row["imageId"])


def usage_counts(feed_items: Iterable[dict[str, Any]], now: datetime | None = None) -> Counter[str]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    counts: Counter[str] = Counter()
    for item in feed_items:
        image_id = str(item.get("poentaImageId") or "")
        if not image_id:
            continue
        try:
            published = datetime.fromisoformat(str(item.get("publishedAt") or "").replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if published >= cutoff:
            counts[image_id] += 1
    return counts


def find_match(
    item: dict[str, Any],
    catalog: list[dict[str, Any]],
    feed_items: Iterable[dict[str, Any]] = (),
) -> dict[str, Any] | None:
    domain = canonical(item.get("imageDomain") or item.get("category"))
    tags = unique_tags(item.get("imageTags") or [])
    if not domain or len(tags) != 4:
        return None
    tag_set = set(tags)
    is_sport = domain == canonical("ספורט")
    required_sport_subtype = article_sport_subtype(item) if is_sport else ""
    counts = usage_counts(feed_items)
    candidates: list[tuple[int, bool, int, str, dict[str, Any], list[str]]] = []
    for image in catalog:
        if image["domain"] != domain:
            continue
        if is_sport:
            candidate_sport_subtype = image_sport_subtype(image)
            if required_sport_subtype:
                if candidate_sport_subtype != required_sport_subtype:
                    continue
            elif candidate_sport_subtype:
                continue
        matched = sorted(tag_set & set(image["tags"]))
        score = len(matched)
        if score < 1:
            continue
        uses = counts[image["imageId"]]
        candidates.append((-score, uses >= 4, uses, image["imageId"], image, matched))
    if not candidates:
        return None
    neg_score, rotation_due, uses, _, image, matched = min(candidates)
    return {
        **image,
        "matchScore": -neg_score,
        "matchedTags": matched,
        "articleTags": tags,
        "uses24h": uses,
        "rotationDue": rotation_due,
    }


def find_domain_fallback(
    item: dict[str, Any],
    catalog: list[dict[str, Any]],
    feed_items: Iterable[dict[str, Any]] = (),
) -> dict[str, Any] | None:
    """Choose the fixed general asset for the article domain."""
    domain = canonical(item.get("imageDomain") or item.get("category"))
    tags = unique_tags(item.get("imageTags") or [])
    filename = DOMAIN_DEFAULT_FILES.get(domain)
    if not filename:
        return None
    source = DOMAIN_DEFAULT_DIR / filename
    if not source.is_file():
        return None
    return {
        "imageId": f"DOMAIN-{Path(filename).stem.upper()}",
        "setCode": f"DOMAIN-DEFAULT-{Path(filename).stem.upper()}",
        "domain": domain,
        "tags": [],
        "file": str(source.resolve()),
        "origin": "poenta-domain-default",
        "status": "approved",
        "matchScore": 0,
        "matchedTags": [],
        "articleTags": tags,
        "uses24h": 0,
        "rotationDue": False,
        "domainFallback": True,
    }


def emergency_fallback(item: dict[str, Any]) -> dict[str, Any]:
    """Return a prevalidated local Poenta asset that can never be an RSS image."""
    return {
        "imageId": "EMERGENCY-POENTA-NEWS",
        "setCode": "EMERGENCY-POENTA-NEWS",
        "domain": canonical(item.get("imageDomain") or item.get("category") or "חדשות"),
        "tags": [],
        "file": str(EMERGENCY_FALLBACK_FILE.resolve()),
        "origin": "poenta-emergency-local",
        "status": "approved",
        "matchScore": 0,
        "matchedTags": [],
        "articleTags": unique_tags(item.get("imageTags") or []),
        "uses24h": 0,
        "rotationDue": False,
        "domainFallback": True,
        "emergencyFallback": True,
    }


def enqueue_live_demand(
    item: dict[str, Any],
    *,
    match: dict[str, Any] | None,
    reason: str,
) -> dict[str, Any]:
    """Record an exact four-tag replacement request for the live feed."""
    domain = canonical(item.get("imageDomain") or item.get("category"))
    tags = unique_tags(item.get("imageTags") or [])
    demand_key = hashlib.sha256(
        json.dumps([domain, sorted(tags)], ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16].upper()
    demand_id = f"LIVE-{demand_key}"
    now = datetime.now(timezone.utc).isoformat()
    LIVE_DEMAND_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LIVE_DEMAND_LOCK.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        payload = _read(
            LIVE_DEMAND_PATH,
            {"schemaVersion": 1, "source": "live-feed-temporary-matches", "items": {}},
        )
        previous = payload.setdefault("items", {}).get(demand_id, {})
        payload["items"][demand_id] = {
            "demandId": demand_id,
            "domain": domain,
            "tags": tags,
            "status": previous.get("status", "queued"),
            "priority": "P0",
            "reason": reason,
            "temporaryImageId": (match or {}).get("imageId"),
            "temporaryMatchScore": (match or {}).get("matchScore", 0),
            "firstQueuedAt": previous.get("firstQueuedAt", now),
            "lastQueuedAt": now,
            "articleCount": int(previous.get("articleCount") or 0) + 1,
            "latestArticleUrl": str(item.get("sourceUrl") or ""),
            "latestHeadline": str(item.get("headline") or ""),
        }
        payload["updatedAt"] = now
        tmp = LIVE_DEMAND_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(LIVE_DEMAND_PATH)
    return payload["items"][demand_id]


def publish_asset(match: dict[str, Any]) -> str:
    source = Path(match["file"])
    filename = f"{match['imageId'].lower()}{POENTA_WATERMARK_SUFFIX}.png"
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    target = PUBLIC_DIR / filename
    source_mtime = source.stat().st_mtime
    watermark_mtime = POENTA_WATERMARK.stat().st_mtime
    if not target.exists() or target.stat().st_mtime < max(source_mtime, watermark_mtime):
        with Image.open(source) as base_source, Image.open(POENTA_WATERMARK) as logo_source:
            base = base_source.convert("RGBA")
            logo = logo_source.convert("RGBA")
            target_width = max(64, round(base.width * 0.10))
            target_height = max(1, round(logo.height * target_width / logo.width))
            logo = logo.resize((target_width, target_height), Image.Resampling.LANCZOS)
            margin = max(12, round(min(base.width, base.height) * 0.025))
            base.alpha_composite(logo, (margin, margin))
            tmp = target.with_suffix(".tmp.png")
            base.convert("RGB").save(tmp, format="PNG", optimize=True)
            tmp.replace(target)
    return f"{PUBLIC_BASE}/{filename}"


def apply_to_new_item(
    item: dict[str, Any],
    existing_feed_items: Iterable[dict[str, Any]],
    catalog: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    # Images are enrichment only. Any failure in catalog loading, matching,
    # asset copying, or demand telemetry must leave the article publishable.
    try:
        catalog = catalog if catalog is not None else build_catalog()
        match = find_match(item, catalog, existing_feed_items)
        if not match:
            match = find_domain_fallback(item, catalog, existing_feed_items)
    except Exception:
        match = None
    if not match:
        match = emergency_fallback(item)
    out = dict(item)
    try:
        out["imageUrl"] = publish_asset(match)
    except Exception:
        match = emergency_fallback(item)
        try:
            out["imageUrl"] = publish_asset(match)
        except Exception:
            # The emergency file normally gets copied into the public V5 tree.
            # If even that copy fails, use the already-public local feed asset.
            out["imageUrl"] = "/assets/feed-defaults/news.png"
    out["poentaImageId"] = match["imageId"]
    out["poentaImageSetCode"] = match["setCode"]
    out["poentaImageMatchScore"] = match["matchScore"]
    out["poentaImageMatchedTags"] = match["matchedTags"]
    out["poentaImageOrigin"] = match["origin"]
    out["poentaImageAssignedAt"] = datetime.now(timezone.utc).isoformat()
    temporary = match["matchScore"] < 3
    demand = None
    if temporary:
        try:
            demand = enqueue_live_demand(
                item,
                match=match,
                reason=(
                    "emergency_local_fallback"
                    if match.get("emergencyFallback")
                    else "domain_general_fallback"
                    if match["matchScore"] == 0
                    else f"temporary_{match['matchScore']}_of_4_match"
                ),
            )
        except Exception:
            demand = None
        out["poentaImageTemporary"] = True
        if demand:
            out["poentaImageReplacementDemandId"] = demand["demandId"]
        else:
            out["poentaImageDemandTelemetryPending"] = True
    return out, {
        "status": (
            "assigned_emergency_fallback"
            if match.get("emergencyFallback")
            else "assigned_domain_fallback"
            if match["matchScore"] == 0
            else "assigned_temporary"
            if temporary
            else "assigned"
        ),
        "imageId": match["imageId"],
        "setCode": match["setCode"],
        "score": match["matchScore"],
        "matchedTags": match["matchedTags"],
        "uses24hBeforeAssignment": match["uses24h"],
        "demandId": demand["demandId"] if demand else None,
    }
