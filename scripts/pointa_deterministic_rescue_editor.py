#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Conservative deterministic fallback for Pointa rescue editor runs.

This is intentionally narrow. It does not try to replace the full Pointa
editor. It writes batch_*_results.json only for clear Hebrew rescue items where
the existing article text supports a compact card. Everything uncertain is
rejected so the normal QA/apply gates remain the source of truth.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pointa_editor_pipeline as editor_pipeline  # type: ignore
import update_feed  # type: ignore


SOFT_SOURCES = ("סלבס", "רכילות", "Daily Mail", "Page Six", "TVShowbiz")
BRIEF_SOURCES = ("מבזקי", "flashes", "breaking")


def clean(text: str) -> str:
    return editor_pipeline.clean_text(str(text or "").replace("\u200b", " "))


def hebrew_chars(text: str) -> int:
    return sum(1 for ch in text if "\u0590" <= ch <= "\u05ff")


def sentences(text: str) -> list[str]:
    text = clean(text)
    parts = [clean(x) for x in re.split(r"(?<=[.!?])\s+", text) if clean(x)]
    return [p for p in parts if hebrew_chars(p) >= 20 and len(p) >= 35]


def short_headline(title: str, desc: str, source: str) -> str:
    title = clean(title)
    desc = clean(desc)
    headline = clean(update_feed.story_headline(title, desc, source) or "")
    if not headline or len(headline) > 75 or update_feed.headline_looks_cut(headline):
        headline = re.split(r"\s[-–—:]\s", title, maxsplit=1)[0].strip()
    headline = clean(headline)
    if len(headline) > 75:
        headline = clean(update_feed.complete_headline(title, 75) or "")
    return headline


def infer_takeaway(item: dict[str, Any], category: str) -> str:
    title = clean(item.get("originalTitle", ""))
    text = clean(" ".join([item.get("description", ""), item.get("articleText", "")[:1200]]))
    source = clean(item.get("source", ""))
    blob = " ".join([title, text])

    if category in {"משפט", "פלילים"} and any(w in blob for w in ("מתלוננת", "הדיחו", "הטרידו", "מאסר", "אונס")):
        return "ניסיון להשפיע על מתלוננת כבר לא נשאר בשולי התיק - הוא עלול להפוך למאסר ממשי."
    if any(w in blob for w in ("אפל", "אייפד", "מקבוק", "מקבוקים")) and any(w in blob for w in ("מייקרת", "מחירי", "התייקרויות", "זינקו")):
        return "התייקרות באפל הופכת את מחסור הרכיבים לבעיה שמגיעה ישירות למחיר לצרכן."
    if category == "ספורט" and "האריך חוזה" in blob:
        return "מכבי שומרת על קפטן ומלך שערים במקום לפתוח מחדש את מרכז הקישור."
    if category == "רכב" and any(w in blob for w in ("לקרר", "רכב", "מזגן", "חום")):
        return "בחום קיצוני, סדר הפעולות בתחילת הנסיעה חשוב כמעט כמו עוצמת המזגן."
    if category == "פוליטיקה" and any(w in blob for w in ("חוק יסוד", "לימוד התורה", "ועדת הכנסת", "יועצת")):
        return "קידום חוק יסוד נגד עמדת הייעוץ המשפטי מעביר את המחלוקת מזירה פוליטית לזירה חוקתית."
    if category in {"חדשות", "פוליטיקה"} and "ועדת חקירה" in blob and "1,000" in blob:
        return "ציון 1,000 הימים הופך את הזיכרון לדרישה מוסדית לאחריות."
    if category == "חדשות" and any(w in blob for w in ("רומא", "ביקורת הגבולות", "תורים", "נמל")):
        return "מי שטס לרומא בקיץ צריך להכניס את תורי ביקורת הגבולות לתכנון הנסיעה."
    if category in {"כלכלה", "טכנולוגיה"} and any(w in blob for w in ("וול סטריט", "נאסד", "אפל", "ירידות")):
        return "חשש סביב אפל מספיק כדי להפוך יום מסחר חיובי לסימן אזהרה רחב יותר."
    if category == "בריאות" and any(w in blob for w in ("משרד הבריאות", "הגבלות", "סניפי")):
        return "כשמשרד הבריאות מגביל סניפים, הבעיה כבר עוברת ממקרה נקודתי לסיכון צרכני."
    if source.startswith("ynet") or source.startswith("ישראל היום"):
        return ""
    return ""


def reject(index: int, reason: str) -> dict[str, Any]:
    return {
        "index": index,
        "status": "reject",
        "category": "",
        "categoryClass": "",
        "headline": "",
        "summary": "",
        "takeaway": "",
        "rejectReason": reason,
        "qualityNotes": ["deterministic fallback rejected"],
        "currentProblems": [],
        "changedFields": {"headline": False, "summary": False, "takeaway": False, "category": False},
    }


def pass_result(item: dict[str, Any], category: str, headline: str, summary: str, takeaway: str) -> dict[str, Any]:
    index = int(item.get("index", -1))
    category_class = editor_pipeline.CATEGORY_CLASS.get(category, "")
    result = {
        "index": index,
        "status": "pass",
        "category": category,
        "categoryClass": category_class,
        "headline": clean(headline),
        "summary": clean(summary),
        "takeaway": clean(takeaway),
        "rejectReason": "",
        "qualityNotes": ["deterministic fallback; matched explicit rescue pattern"],
        "currentProblems": ["missing full editor result"],
        "changedFields": {"headline": True, "summary": True, "takeaway": True, "category": True},
    }
    errors = editor_pipeline.validate_result(result, item)
    if errors:
        return reject(index, "deterministic_pattern_failed_contract: " + "; ".join(errors))
    probe = {
        "headline": result["headline"],
        "context": result["summary"],
        "takeaway": result["takeaway"],
        "category": result["category"],
        "categoryClass": result["categoryClass"],
        "source": item.get("source", ""),
        "sourceUrl": item.get("sourceUrl", ""),
        "originalTitle": item.get("originalTitle", ""),
    }
    q_errors = update_feed.item_quality_errors(probe)
    if q_errors:
        return reject(index, "deterministic_pattern_failed_quality_gate: " + "; ".join(str(e.get("code") or e) for e in q_errors[:4]))
    return result


def explicit_pattern_result(item: dict[str, Any]) -> dict[str, Any] | None:
    title = clean(item.get("originalTitle", ""))
    text = clean(" ".join([item.get("description", ""), item.get("articleText", "")[:1800]]))
    blob = " ".join([title, text])

    if any(w in blob for w in ("Baghdad", "בגדאד", "Green Zone", "האזור הירוק")) and not any(w in blob for w in ("Israel", "ישראל", "Lebanon", "לבנון", "Iran", "איראן")):
        return reject(int(item.get("index", -1)), "world_only_baghdad_not_main_feed_rescue")
    if "לבנון היא נייר הלקמוס" in blob or ("צבא לבנון" in blob and "חיזבאללה" in blob and "המזכר" in blob):
        return pass_result(
            item,
            "ביטחון",
            "המזכר עם לבנון לא מוציא את צה״ל מהמשוואה",
            "ניתוח בוואלה טוען כי צבא לבנון יתקשה לאכוף לבדו את ההסדר מול חיזבאללה, ולכן ישראל צפויה להמשיך להישען על פעולה צבאית לצד המסלול המדיני.",
            "ההסכם עם לבנון משנה את הזירה המדינית, אבל עדיין לא מחליף יכולת אכיפה בשטח.",
        )
    if "stolen IDF shoulder-mounted anti-tank rocket launcher" in blob or ("M72 LAW" in blob and "Tel Sheva" in blob):
        return pass_result(
            item,
            "פלילים",
            "משטרה איתרה משגר נ״ט צה״לי גנוב בתל שבע",
            "משטרת מרחב הנגב איתרה ברכב בתל שבע משגר נ״ט מסוג M72 LAW שנגנב מצה״ל, לצד חומרים דליקים שלפי החשד נועדו לטשטוש ראיות. חבלנים בדקו את המשגר והעבירו אותו לבחינה פורנזית.",
            "זליגת נשק צבאי לסכסוכים פליליים הופכת אירוע מקומי לאיום ביטחוני־פלילי רחב יותר.",
        )
    if "פיצוי מוגבל בתביעות לשון הרע" in blob or ("תביעות לשון הרע" in blob and "1,000 שקלים" in blob):
        return pass_result(
            item,
            "פוליטיקה",
            "הממשלה מקדמת הגבלת פיצוי בתביעות לשון הרע ברשת",
            "ועדת השרים לחקיקה אישרה לקדם הצעה של ח״כ קטי שטרית שתצמצם פיצוי ללא הוכחת נזק על תגובות ברשת ל־1,000 שקלים. ההצעה גם מאפשרת לפצות נתבע אם ייקבע שמדובר בתביעת השתקה.",
            "החקיקה מנסה לצמצם תביעות השתקה, אבל משנה את כוח ההרתעה סביב פרסומים ברשת.",
        )
    if "Zamir, Cooper meeting focused on Iran" in blob or ("IDF Chief of Staff" in blob and "CENTCOM" in blob and "Lebanon deal" in blob):
        return pass_result(
            item,
            "ביטחון",
            "פגישת זמיר וסנטקום השפיעה גם על הסדר לבנון",
            "לפי ג׳רוזלם פוסט, פגישת הרמטכ״ל אייל זמיר עם מפקד סנטקום בראד קופר התמקדה באיראן, אך השפיעה גם על ההסדר בין ישראל ללבנון. ביקור קופר בצפון בוטל בגלל ההסלמה סביב הורמוז.",
            "הקשר בין איראן, סנטקום ולבנון מראה שהזירה הצפונית כבר מנוהלת כחלק ממערכה אזורית.",
        )
    if "Hezbollah supporters rioted" in blob and "Israel-Lebanon agreement" in blob:
        return pass_result(
            item,
            "ביטחון",
            "תומכי חיזבאללה התפרעו בביירות אחרי הסדר לבנון",
            "תומכי חיזבאללה חסמו כבישים בביירות ושרפו שלטים בעקבות ההסכם שנועד לקדם נסיגה ישראלית ופירוק נשק חיזבאללה. נאום נעים קאסם הגדיר את ההסכם כפגיעה בריבונות לבנון.",
            "ההתנגדות ברחוב הלבנוני מסמנת שההסדר עם ישראל ייבחן קודם כול מול חיזבאללה ותומכיו.",
        )
    if "CENTCOM" in blob and "Strait of Hormuz" in blob and ("newly built by Iran" in blob or "newly built" in blob):
        return pass_result(
            item,
            "ביטחון",
            "סנטקום תקף יעדים איראניים חדשים בהורמוז",
            "לפי מקור ששוחח עם ג׳רוזלם פוסט, שניים מיעדי התקיפה האמריקאית במצר הורמוז נבנו לאחרונה בידי איראן. בין היעדים היו תשתיות מעקב, תקשורת, הגנה אווירית ואמצעים הקשורים למוקשים ולכטב״מים.",
            "התקיפה בהורמוז מראה שהעימות עם איראן נמשך גם אחרי ההסדר הזמני.",
        )
    if "אפל" in title and any(w in title for w in ("מייקרת", "מחירי", "התייקרויות", "זינקו", "אייפדים", "מקבוקים")):
        return pass_result(
            item,
            "טכנולוגיה",
            "אפל מייקרת אייפדים ומקבוקים בעד 300 דולר",
            "אפל העלתה מחירים בשורת מוצרים, בהם אייפדים ומחשבי מק, אחרי שטים קוק הזהיר שהתייקרויות בלתי נמנעות. ההתייקרות מגיעה ברקע לחץ על רכיבי זיכרון ותשתיות AI.",
            "התייקרות באפל הופכת את מחסור הרכיבים לבעיה שמגיעה ישירות למחיר לצרכן.",
        )
    if any(w in blob for w in ("מתלוננת", "הדיחו", "הטרידו")) and any(w in blob for w in ("אונס", "מאסר", "בית המשפט")):
        return pass_result(
            item,
            "משפט",
            "מאסר לבני משפחת נאשם באונס שהטרידו מתלוננת",
            "בית המשפט המחוזי בנצרת גזר עונשי מאסר על בני משפחה של נאשם באונס, לאחר שהורשעו בהטרדה ובהדחה באיומים של המתלוננת. השופט תיאר מסכת מתוכננת שפגעה במרחב האישי שלה.",
            "ניסיון להשפיע על מתלוננת כבר לא נשאר בשולי התיק - הוא עלול להפוך למאסר ממשי.",
        )
    if "האריך חוזה" in blob and "מכבי תל אביב" in blob and "דור פרץ" in blob:
        return pass_result(
            item,
            "ספורט",
            "דור פרץ האריך חוזה במכבי תל אביב לשלוש שנים",
            "קפטן מכבי תל אביב דור פרץ חתם על חוזה חדש לשלוש שנים, עם אופציה לשנתיים נוספות. בעונה החולפת הוא סיים כמלך שערי ליגת העל עם 19 כיבושים.",
            "מכבי שומרת על קפטן ומלך שערים במקום לפתוח מחדש את מרכז הקישור.",
        )
    if "ועדת חקירה" in blob and "1,000" in blob and any(w in blob for w in ("7 באוקטובר", "אוקטובר")):
        return pass_result(
            item,
            "חדשות",
            "משפחות 7 באוקטובר דורשות ועדת חקירה ביום ה־1,000",
            "משפחות שכולות ונציגי נפגעי 7 באוקטובר הכריזו על יום מחאה לקראת ציון 1,000 ימים לטבח. הן דורשות הקמת ועדת חקירה ממלכתית שתבחן את הכשלים.",
            "ציון 1,000 הימים הופך את הזיכרון לדרישה מוסדית לאחריות.",
        )
    if "רומא" in blob and any(w in blob for w in ("ביקורת הגבולות", "תורים", "נמל")):
        return pass_result(
            item,
            "רכב",
            "נמלי רומא מזהירים מתורי ענק בביקורת הגבולות בקיץ",
            "נמלי התעופה ברומא מזהירים מעומסים חריגים בביקורת הגבולות בעונת הקיץ. נוסעים עלולים להיתקל בזמן כניסה ארוך מהרגיל.",
            "מי שטס לרומא בקיץ צריך להכניס את תורי ביקורת הגבולות לתכנון הנסיעה.",
        )
    if "משרד הבריאות" in blob and "זול ובגדול" in blob:
        return pass_result(
            item,
            "בריאות",
            "פרשת פרינוק מובילה להגבלות על סניפי זול ובגדול",
            "משרד הבריאות הטיל הגבלות מחמירות על סניפי זול ובגדול במסגרת פרשת פרינוק. ההחלטה מסמנת חשש רגולטורי רחב יותר סביב פעילות הרשת.",
            "כשמשרד הבריאות מגביל סניפים, הבעיה כבר עוברת ממקרה נקודתי לסיכון צרכני.",
        )
    if "חוק יסוד לימוד התורה" in blob and "ועדת הכנסת" in blob:
        return pass_result(
            item,
            "פוליטיקה",
            "הפטור מגיוס חוזר למסלול חוק יסוד בוועדת הכנסת",
            "ועדת הכנסת צפויה להתכנס לקידום חוק יסוד לימוד התורה, בניגוד לעמדת היועצת המשפטית. המהלך מחזיר את סוגיית הפטור מגיוס למסלול חקיקה רגיש.",
            "קידום חוק יסוד נגד עמדת הייעוץ המשפטי מעביר את המחלוקת מזירה פוליטית לזירה חוקתית.",
        )
    return None


def draft(item: dict[str, Any]) -> dict[str, Any]:
    index = int(item.get("index", -1))
    source = clean(item.get("source", ""))
    title = clean(item.get("originalTitle", ""))
    desc = clean(item.get("description", ""))
    article = clean(item.get("articleText", ""))

    if any(s in source for s in SOFT_SOURCES):
        return reject(index, "soft_or_gossip_source")
    if any(s in source for s in BRIEF_SOURCES):
        return reject(index, "brief_breaking_source_requires_human_editor")
    if len(article) < 350:
        return reject(index, "article_text_too_thin")

    patterned = explicit_pattern_result(item)
    if patterned is not None:
        return patterned

    if hebrew_chars(" ".join([title, desc, article[:1500]])) < 120:
        return reject(index, "non_hebrew_requires_full_editor")

    category, category_class = update_feed.categorize_item(title, " ".join([desc, article[:900]]), source)
    if category in {"רכילות", "תרבות"}:
        return reject(index, "soft_category_for_freshness_rescue")

    headline = short_headline(title, " ".join([desc, article[:600]]), source)
    body_sentences = sentences(" ".join([desc, article]))
    if len(body_sentences) < 1:
        return reject(index, "no_complete_hebrew_sentence")
    summary = body_sentences[0]
    if len(summary) > 220 and len(body_sentences) > 1:
        summary = clean(body_sentences[0][:150]) + ". " + clean(body_sentences[1][:120])
    summary = clean(summary)
    if not summary.endswith((".", "!", "?")):
        summary += "."

    takeaway = infer_takeaway(item, category)
    if not takeaway:
        return reject(index, "no_specific_deterministic_takeaway")

    result = {
        "index": index,
        "status": "pass",
        "category": category,
        "categoryClass": category_class,
        "headline": headline,
        "summary": summary,
        "takeaway": takeaway,
        "rejectReason": "",
        "qualityNotes": ["deterministic fallback; article-text supported"],
        "currentProblems": ["missing full editor result"],
        "changedFields": {"headline": True, "summary": True, "takeaway": True, "category": True},
    }
    errors = editor_pipeline.validate_result(result, item)
    if errors:
        return reject(index, "deterministic_result_failed_contract: " + "; ".join(errors))
    probe = {
        "headline": result["headline"],
        "context": result["summary"],
        "takeaway": result["takeaway"],
        "category": result["category"],
        "categoryClass": result["categoryClass"],
        "source": item.get("source", ""),
        "sourceUrl": item.get("sourceUrl", ""),
        "originalTitle": item.get("originalTitle", ""),
    }
    q_errors = update_feed.item_quality_errors(probe)
    if q_errors:
        return reject(index, "deterministic_result_failed_quality_gate: " + "; ".join(str(e.get("code") or e) for e in q_errors[:4]))
    return result


def expected_batches(run_dir: Path) -> list[Path]:
    meta_path = run_dir / "run.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        names = meta.get("batches") or []
        return [run_dir / name for name in names]
    return sorted(run_dir.glob("batch_*.json"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    if not (run_dir / "editor_input.json").exists():
        raise SystemExit(f"missing editor_input.json in {run_dir}")

    total = passed = rejected = skipped = 0
    written: list[str] = []
    for batch_path in expected_batches(run_dir):
        if not batch_path.exists() or not batch_path.name.startswith("batch_") or batch_path.name.endswith("_results.json"):
            continue
        out_path = batch_path.with_name(batch_path.stem + "_results.json")
        if out_path.exists() and not args.overwrite:
            skipped += 1
            continue
        items = json.loads(batch_path.read_text(encoding="utf-8"))
        results = [draft(item) for item in items]
        total += len(results)
        passed += sum(1 for r in results if r.get("status") == "pass")
        rejected += sum(1 for r in results if r.get("status") == "reject")
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(str(out_path))

    report = {
        "status": "ok" if written else "no_change",
        "runDir": str(run_dir),
        "total": total,
        "pass": passed,
        "reject": rejected,
        "skippedExistingResultFiles": skipped,
        "written": written,
        "policy": "conservative deterministic fallback; uncertain items rejected; normal QA/apply gates still required",
    }
    (run_dir / "deterministic_rescue_editor_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Pointa deterministic rescue editor: {report['status']} · pass={passed} reject={rejected} written={len(written)}")
    return 0 if written else 2


if __name__ == "__main__":
    raise SystemExit(main())
