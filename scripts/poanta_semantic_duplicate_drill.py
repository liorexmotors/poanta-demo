#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression drill for semantic duplicate story filtering.

This drill covers cases where two cards are the same news event from different
sources but wording overlap is too low for exact/title-only dedupe.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pointa_live_auditor import likely_duplicate_story  # noqa: E402
import update_feed  # noqa: E402


CASES = [
    (
        "israel_lebanon_hezbollah_ceasefire_litani_live_regression_20260604",
        True,
        {
            "source": "The Jerusalem Post - Israel News",
            "category": "ביטחון",
            "categoryClass": "security",
            "headline": "ישראל ולבנון קידמו הפסקת אש שמותנית בהרחקת חיזבאללה",
            "originalTitle": "Israel, Lebanon agree to ceasefire on condition of end to Hezbollah fire, US State Department says",
            "context": "ישראל ולבנון קידמו הבנות להפסקת אש בתיווך אמריקני, בתנאי שחיזבאללה יורחק מהאזור המאיים על הצפון.",
            "sourceUrl": "https://www.jpost.com/israel-news/defense-news/article-898323",
        },
        {
            "source": "מעריב - חדשות",
            "category": "ביטחון",
            "categoryClass": "security",
            "headline": "ישראל ולבנון קושרות הפסקת אש לנסיגת חיזבאללה מהליטני",
            "originalTitle": "הפסקת אש מותנית בין ישראל ללבנון: תלויה בפריסת חיזבאללה מדרום לליטני",
            "context": "הפסקת האש בין ישראל ללבנון מותנית בהרחקת חיזבאללה מדרום לליטני ובמניעת ירי נוסף לעבר הצפון.",
            "sourceUrl": "https://www.maariv.co.il/news/politics/article-1329059",
        },
    ),
    (
        "israel_lebanon_hezbollah_ceasefire_walla_jpost_visible_regression_20260604",
        True,
        {
            "source": "The Jerusalem Post - Israel News",
            "category": "ביטחון",
            "categoryClass": "security",
            "headline": "ישראל ולבנון קידמו אזורי פיילוט בלי חיזבאללה בדרום",
            "originalTitle": "Israel, Lebanon agree to ceasefire on condition of end to Hezbollah fire, US State Department says",
            "context": "ישראל ולבנון קידמו אזורי פיילוט להפסקת אש בדרום, בתנאי שחיזבאללה יורחק והצבא הלבנוני ייכנס לאזור.",
            "sourceUrl": "https://www.jpost.com/israel-news/defense-news/article-898323",
        },
        {
            "source": "וואלה חדשות - חדשות בעולם",
            "category": "ביטחון",
            "categoryClass": "security",
            "headline": "ישראל ולבנון קידמו הפסקת אש בתנאי שחיזבאללה יורחק",
            "originalTitle": "\"הפסקת האש - תמורת הפסקת ירי חיזבאללה\": סיכומי סבב שיחות השלום בין ישראל ללבנון",
            "context": "ישראל ולבנון קידמו הפסקת אש בתיווך אמריקני, כאשר התנאי המרכזי הוא הפסקת ירי חיזבאללה והרחקתו מדרום לבנון.",
            "sourceUrl": "https://news.walla.co.il/item/3843087",
        },
    ),
    (
        "israel_lebanon_hezbollah_ceasefire_guardian_globes_inn_visible_regression_20260604",
        True,
        {
            "source": "גלובס - בארץ",
            "category": "ביטחון",
            "categoryClass": "security",
            "headline": "הפסקת אש בין ישראל ללבנון הותנתה בנסיגת חיזבאללה",
            "originalTitle": "בתום סבב השיחות: ישראל ולבנון הסכימו על הפסקת אש מלאה",
            "context": "ישראל, לבנון וארה״ב הגיעו להסכם הפסקת אש, בכפוף לנסיגת פעילי חיזבאללה מהשטח שמדרום לליטני.",
            "sourceUrl": "https://www.globes.co.il/news/article.aspx?did=1001544930#utm_source=RSS",
        },
        {
            "source": "The Guardian Middle East",
            "category": "ביטחון",
            "categoryClass": "security",
            "headline": "הסכם ביטחוני חדש בגבול לבנון",
            "originalTitle": "Netanayahu’s been ‘a great partner’, says Trump – as it happened",
            "context": "ישראל ולבנון הסכימו בתיווך אמריקני לחדש את הפסקת האש ולהקים אזורי ביטחון ניסיוניים בדרום לבנון, שבהם יורחקו פעילי חיזבאללה והצבא הלבנוני יקבל אחריות מלאה מדרום לליטני.",
            "sourceUrl": "https://www.theguardian.com/world/live/2026/jun/03/us-israel-iran-war-lebanon-trump-khamenei-netanyahu-hormuz-latest-news-updates",
        },
    ),
    (
        "israel_lebanon_iran_out_inn_globes_visible_regression_20260604",
        True,
        {
            "source": "ערוץ 7 / INN עברית",
            "category": "ביטחון",
            "categoryClass": "security",
            "headline": "לייטר: ישראל, לבנון וארה״ב פועלות להרחיק את איראן",
            "originalTitle": "שגריר ישראל בארה\"ב: ישראל, לבנון ואמריקה מאוחדות כדי להשאיר את איראן בחוץ",
            "context": "שגריר ישראל בארה״ב יחיאל לייטר הציג את הרחקת איראן כיעד מרכזי במגעים סביב הפסקת האש בין ישראל ללבנון.",
            "takeaway": "המסר מציב את חיזבאללה ואיראן כקו אדום גם אם מתקדם הסדר בחסות אמריקנית.",
            "sourceUrl": "https://www.inn.co.il/flashes/1116165",
        },
        {
            "source": "גלובס - בארץ",
            "category": "ביטחון",
            "categoryClass": "security",
            "headline": "הפסקת אש בין ישראל ללבנון הותנתה בנסיגת חיזבאללה",
            "originalTitle": "בתום סבב השיחות: ישראל ולבנון הסכימו על הפסקת אש מלאה",
            "context": "ישראל, לבנון וארה״ב הגיעו להסכם הפסקת אש, בכפוף לנסיגת פעילי חיזבאללה מהשטח שמדרום לליטני.",
            "sourceUrl": "https://www.globes.co.il/news/article.aspx?did=1001544930#utm_source=RSS",
        },
    ),
    (
        "fox_noy_hasadeh_business_live_regression_20260603",
        True,
        {
            "source": "גלובס - שוק ההון",
            "category": "כלכלה",
            "categoryClass": "money",
            "headline": "הראל ויזל בוחן כניסה לשוק המזון דרך נוי השדה",
            "originalTitle": "הראל ויזל בוחן כניסה לשוק המזון דרך רכישת נוי השדה",
            "context": "קבוצת פוקס של הראל ויזל בוחנת רכישת פעילות נוי השדה כדי להיכנס לשוק המזון הטרי.",
            "sourceUrl": "https://www.globes.co.il/news/article.aspx?did=1001544823#utm_source=RSS",
        },
        {
            "source": "דה מרקר - שוק ההון",
            "category": "כלכלה",
            "categoryClass": "money",
            "headline": "פוקס בוחנת רכישת רשת נוי השדה",
            "originalTitle": "פוקס בוחנת רכישת רשת נוי השדה",
            "context": "פוקס בוחנת עסקה לרכישת רשת המזון נוי השדה כחלק מהרחבת הפעילות הקמעונאית שלה.",
            "sourceUrl": "https://www.themarker.com/markets/2026-06-03/ty-article/.premium/0000019e-8c29-d0a9-a7df-bdbb2e500000",
        },
    ),
    (
        "israir_slovenia_landing_diversion_live_regression_20260603",
        True,
        {
            "source": "ynet - מבזקי החדשות",
            "category": "פוליטיקה",
            "categoryClass": "security",
            "headline": "טיסת ישראייר הוסטה מלובליאנה לזאגרב",
            "originalTitle": "טיסת ישראייר ללובליאנה הוסטה לזאגרב",
            "context": "טיסת ישראייר לא הורשתה לנחות בלובליאנה והוסטה לזאגרב בעקבות החלטת הרשויות בסלובניה.",
            "sourceUrl": "https://www.ynet.co.il/news/article/hjmahpteme",
        },
        {
            "source": "N12 - בעולם",
            "category": "פוליטיקה",
            "categoryClass": "security",
            "headline": "סלובניה חסמה נחיתה לישראייר",
            "originalTitle": "סלובניה חסמה נחיתה לטיסת ישראייר",
            "context": "הרשויות בסלובניה חסמו נחיתה של טיסת ישראייר בלובליאנה, והמטוס נחת לבסוף בזאגרב.",
            "sourceUrl": "https://www.mako.co.il/news-world/2026_q2/Article-58489083cac8e91026.htm",
        },
    ),
    (
        "us_iran_tanker_hellfire_live_regression_20260603",
        True,
        {
            "source": "וואלה חדשות - חדשות בעולם",
            "category": "ביטחון",
            "headline": "ארה״ב השביתה מכלית בדרך לאיראן בטיל הלפייר",
            "originalTitle": "המתיחות נמשכת: ארה\"ב ניטרלה מכלית נפט שהייתה בדרכה לאיראן",
            "context": "כוחות אמריקניים השביתו במפרץ הפרסי את מכלית M/T Lexie אחרי שהתעלמה במשך יממה מהוראות בדרכה למסוף הנפט ח׳ארג באיראן.",
            "sourceUrl": "https://news.walla.co.il/item/3842812",
        },
        {
            "source": "BBC World",
            "category": "ביטחון",
            "headline": "ארה״ב שיתקה מכלית בדרך לאיראן כחלק מהמצור במצר הורמוז",
            "originalTitle": "US says it fired missile at Iran-bound oil tanker",
            "context": "הכוחות האמריקניים ירו על מכלית שהייתה בדרכה לאיראן כחלק מאכיפת המצור הימי במצר הורמוז.",
            "sourceUrl": "https://www.bbc.com/news/articles/c5yx135yg53o",
        },
    ),
    (
        "us_iran_tanker_guardian_walla_live_regression_20260603",
        True,
        {
            "source": "The Guardian Middle East",
            "category": "ביטחון",
            "headline": "ארה״ב השביתה מכלית בדרך לאיראן והחריפה את משבר הורמוז",
            "originalTitle": "Guardian US fires missile at tanker attempting to reach Iran amid strait of Hormuz standoff",
            "context": "כוחות אמריקניים ירו על מכלית שניסתה להגיע לאיראן במסגרת העימות סביב מצר הורמוז.",
            "sourceUrl": "https://www.theguardian.com/world/2026/jun/03/us-fires-missile-tanker-strait-of-hormuz",
        },
        {
            "source": "וואלה חדשות - חדשות בעולם",
            "category": "ביטחון",
            "headline": "ארה״ב השביתה מכלית בדרך לאיראן בטיל הלפייר",
            "originalTitle": "המתיחות נמשכת: ארה\"ב ניטרלה מכלית נפט שהייתה בדרכה לאיראן",
            "context": "כוחות אמריקניים השביתו במפרץ הפרסי מכלית שהייתה בדרכה למסוף הנפט ח׳ארג באיראן.",
            "sourceUrl": "https://news.walla.co.il/item/3842812",
        },
    ),
    (
        "us_iran_tanker_guardian_current_headline_url_20260603",
        True,
        {
            "source": "The Guardian Middle East",
            "category": "ביטחון",
            "headline": "ארה״ב ואיראן חידשו תקיפות סביב מצר הורמוז והמפרץ",
            "originalTitle": "US and Iran launch fresh strikes amid stalled ceasefire talks",
            "context": "ארה״ב השביתה מכלית שהתקרבה לאיראן, תקפה מטרות בקשם והדפה טילים וכטב״מים לעבר כוויית ובחריין.",
            "sourceUrl": "https://www.theguardian.com/world/2026/jun/03/us-fires-missile-tanker-strait-of-hormuz",
        },
        {
            "source": "וואלה חדשות - מבזקים",
            "category": "ביטחון",
            "headline": "מטוס אמריקני השבית מכלית בדרך למסוף הנפט באיראן",
            "originalTitle": "פיקוד המרכז של ארה״ב: מכלית נפט שהייתה בדרכה לאיראן נוטרלה באמצעות טיל הלפייר",
            "context": "המכלית M/T Lexie המשיכה לעבר האי ח'ארג אחרי אזהרות אמריקניות, וטיל הלפייר פגע בחדר המנוע והשבית את הספינה.",
            "sourceUrl": "https://news.walla.co.il/break/3842815",
        },
    ),
    (
        "us_iran_gulf_exchange_kuwait_bahrain_20260603",
        True,
        {
            "source": "BBC World",
            "category": "ביטחון",
            "headline": "ארה״ב תקפה עמדת שליטה איראנית בקשם אחרי ירי למפרץ",
            "originalTitle": "US says it launched 'self-defense' strikes on Iranian island",
            "context": "פיקוד המרכז האמריקני תקף באי קשם תחנת שליטה איראנית, לאחר שטילים וכטב״מים שוגרו לעבר כלי שיט ומדינות מפרץ כמו כווית ובחריין.",
            "sourceUrl": "https://www.bbc.com/news/articles/c5yx135yg53o?at_medium=RSS&at_campaign=rss",
        },
        {
            "source": "מעריב - חדשות",
            "category": "ביטחון",
            "headline": "איראן הרחיבה את תגובת המפרץ לכווית ולבחריין",
            "originalTitle": "לילה סוער במפרץ: ארה\"ב פעלה בהורמוז - איראן תקפה בכווית ובחריין",
            "context": "אחרי פעולה אמריקנית נגד מכלית שניסתה להגיע לאיראן, כווית ובחריין הפעילו מערכי הגנה והתרעות מפני טילים וכטב״מים.",
            "sourceUrl": "https://www.maariv.co.il/news/world/article-1328648",
        },
    ),
    (
        "north_reconstruction_13b_live_regression_20260603",
        True,
        {
            "source": "וואלה חדשות",
            "category": "ביטחון",
            "headline": "הממשלה אישרה תוכנית מיגון ושיקום של 13 מיליארד שקל לצפון",
            "originalTitle": "הממשלה אישרה 13 מיליארד ש\"ח לשיקום הצפון",
            "context": "הממשלה אישרה תוכנית מיגון ושיקום ליישובי קו העימות בצפון, כולל ממ״דים, מקלטים, כבישים ושירותי רפואה.",
            "sourceUrl": "https://news.walla.co.il/item/3842802",
        },
        {
            "source": "The Jerusalem Post - Israel News",
            "category": "ביטחון",
            "headline": "הממשלה אישרה תוספת של 13 מיליארד שקל ליישובי הצפון",
            "originalTitle": "Gov't greenlights NIS 13b. for shelters, infrastructure in Israel's North",
            "context": "הממשלה אישרה תוספת של 13 מיליארד שקל למקלטים, תשתיות ושיקום יישובי הצפון סמוך לגבול לבנון.",
            "sourceUrl": "https://www.jpost.com/israel-news/politics-and-diplomacy/article-898166",
        },
    ),
    (
        "idf_south_lebanon_village_evacuation_live_regression_20260603",
        True,
        {
            "source": "וואלה חדשות - מבזקים",
            "category": "ביטחון",
            "headline": "צה״ל הזהיר שישה כפרים בדרום לבנון להתפנות לפני תקיפה",
            "context": "דובר צה״ל בערבית פרסם אזהרת פינוי דחופה לתושבי שישה כפרים בדרום לבנון לפני תקיפה",
            "sourceUrl": "https://news.walla.co.il/break/3842848",
        },
        {
            "source": "ynet - מבזקי החדשות",
            "category": "ביטחון",
            "headline": "צה״ל קרא לפינוי כפרים בדרום לבנון",
            "context": "צה״ל פרסם אזהרת פינוי לשני כפרים באזור צידון ולכפר מצפון לצור",
            "sourceUrl": "https://www.ynet.co.il/news/article/hkeqhstgzg",
        },
    ),
    (
        "netanyahu_hezbollah_drone_solution_north_live_regression_20260603",
        True,
        {
            "source": "The Jerusalem Post - Israel News",
            "category": "ביטחון",
            "headline": "נתניהו מבטיח פתרון קרוב לאיום רחפני חיזבאללה",
            "context": "נתניהו אמר לראשי מועצות בצפון שפתרון לאיום רחפני חיזבאללה ייושם בימים הקרובים",
            "sourceUrl": "https://www.jpost.com/israel-news/article-898177",
        },
        {
            "source": "ישראל היום - כל הכתבות",
            "category": "ביטחון",
            "headline": "נתניהו הבטיח ליישובי הצפון פתרון קרוב לרחפני הנפץ",
            "context": "ראש הממשלה אמר לתושבי הצפון שהמערכת להתמודדות עם רחפני הנפץ של חיזבאללה צפויה להיות מיושמת בקרוב",
            "sourceUrl": "https://www.israelhayom.co.il/news/defense/article/20678235",
        },
    ),
    (
        "trump_netanyahu_beirut_strike_cancelled_cross_source",
        True,
        {
            "source": "The Jerusalem Post - Israel News",
            "category": "פוליטיקה",
            "headline": "נתניהו ביטל תקיפה בביירות בלחץ טראמפ ועורר ביקורת בישראל",
            "originalTitle": "'Time to say no to Trump': Israeli officials condemn Netanyahu's decision to cancel Lebanon strike",
            "context": "נתניהו ביטל תוכנית לתקיפה ישראלית בביירות לאחר שטראמפ דרש לעצור את המהלך. פוליטיקאים ואנשי ביטחון בישראל טענו שההחלטה מצמצמת את חופש הפעולה מול חיזבאללה ומחזקת תלות בוושינגטון.",
            "sourceUrl": "https://www.jpost.com/israel-news/politics-and-diplomacy/article-898056",
        },
        {
            "source": "וואלה חדשות - חדשות בעולם",
            "category": "ביטחון",
            "headline": "טראמפ בלם תוכנית ישראלית לתקוף בביירות",
            "originalTitle": "\"אתה משוגע וכפוי טובה\": שיחת הקללות בין טראמפ לנתניהו",
            "context": "טראמפ גער בנתניהו בשיחה חריפה על רקע ההסלמה בלבנון והחשש מפגיעה במגעים עם איראן. בעקבות הלחץ האמריקני, ישראל ויתרה בשלב זה על תקיפה שתוכננה בביירות.",
            "sourceUrl": "https://news.walla.co.il/item/3842531",
        },
    ),
    (
        "trump_netanyahu_beirut_strike_cancelled_be7_ynet_live_regression",
        True,
        {
            "source": "בשבע - מגזין ודעות",
            "category": "ביטחון",
            "headline": "טראמפ בלם תקיפה ישראלית בדאחייה אחרי איום איראני",
            "originalTitle": "טראמפ מנע תקיפה ישראלית בדאחייה בעקבות איומי איראן",
            "context": "איראן איימה להפסיק את השיחות עם ארה״ב ולשקול חסימת מצרים ימיים; בעקבות זאת טראמפ דרש מנתניהו לעצור את הפעולה בביירות.",
            "sourceUrl": "https://be7.co.il/23947",
        },
        {
            "source": "ynet - מבזקי החדשות",
            "category": "ביטחון",
            "headline": "ביקורת בליכוד על ביטול התקיפה בביירות",
            "originalTitle": "ביקורת בליכוד על ביטול התקיפה בביירות",
            "context": "ח״כ משה סעדה תקף את ביטול התקיפות בדאחייה בעקבות הנחיית דונלד טראמפ, וטען כי מדיניות ההכלה מול האיום בלבנון מסוכנת לישראל.",
            "sourceUrl": "https://www.ynet.co.il/news/article/hjwesghlge",
        },
    ),
    (
        "attorney_general_split_bill_cross_source",
        True,
        {
            "source": "The Jerusalem Post - Israel News",
            "category": "פוליטיקה",
            "headline": "חוק פיצול היועמ״שית עבר בקריאה ראשונה בכנסת",
            "originalTitle": "Bill that would split role of attorney-general passes first Knesset reading",
            "context": "הכנסת אישרה בקריאה ראשונה הצעה לפצל את תפקיד היועץ המשפטי לממשלה ליועץ משפטי ולתובע כללי, ולהרחיב את יכולת הממשלה לקבוע מינוי וייצוג משפטי.",
            "sourceUrl": "https://www.jpost.com/israel-news/politics-and-diplomacy/article-898054",
        },
        {
            "source": "וואלה חדשות - פוליטי-מדיני",
            "category": "משפט",
            "headline": "חוק פיצול היועמ״שית עבר בקריאה ראשונה למרות אזהרות מערכת המשפט",
            "originalTitle": "בקריאה ראשונה: מליאת הכנסת אישרה את הצעת החוק לפיצול תפקיד היועמ\"שית",
            "context": "מליאת הכנסת אישרה בקריאה ראשונה את הצעת החוק לפיצול תפקיד היועץ המשפטי לממשלה, ברוב של 65 תומכים מול 47 מתנגדים.",
            "sourceUrl": "https://news.walla.co.il/item/3842526",
        },
    ),
    (
        "attorney_general_split_bill_ynet_jpost_live_regression",
        True,
        {
            "source": "ynet - כל ערוץ החדשות",
            "category": "פוליטיקה",
            "headline": "הכנסת אישרה בקריאה ראשונה את פיצול תפקיד היועמ״ש",
            "originalTitle": "הכנסת אישרה בקריאה ראשונה את פיצול תפקיד היועמ\"ש",
            "context": "הכנסת אישרה בקריאה ראשונה את פיצול תפקיד היועץ המשפטי לממשלה ליועץ משפטי ולתובע כללי. המהלך הוא נדבך מרכזי בתוכנית הקואליציה לשינוי יחסי הממשלה ומערכת המשפט.",
            "sourceUrl": "https://www.ynet.co.il/news/article/hjmply3efe",
        },
        {
            "source": "The Jerusalem Post - Israel News",
            "category": "פוליטיקה",
            "headline": "חוק פיצול היועמ״שית עבר בקריאה ראשונה בכנסת",
            "originalTitle": "Bill that would split role of attorney-general passes first Knesset reading",
            "context": "הכנסת אישרה בקריאה ראשונה הצעה לפצל את תפקיד היועץ המשפטי לממשלה ליועץ משפטי ולתובע כללי, ולהרחיב את יכולת הממשלה לקבוע מינוי וייצוג משפטי.",
            "sourceUrl": "https://www.jpost.com/israel-news/politics-and-diplomacy/article-898054",
        },
    ),
    (
        "us_southern_iran_strikes_cross_language",
        True,
        {
            "source": "New York Times Middle East",
            "category": "ביטחון",
            "headline": "ארה״ב ביצעה תקיפות הגנה עצמית בדרום איראן",
            "originalTitle": "U.S. Carries Out Renewed Strikes in Southern Iran",
            "context": "פיקוד המרכז האמריקני מסר כי תקף אתרי שיגור טילים וסירות איראניות שניסו להניח מוקשים, כדי להגן על כוחותיו בזמן הפסקת האש. התקיפות ליד בנדר עבאס הגיעו במקביל לשיחות בדוחא על סיום המלחמה ועל פתיחת מצר הורמוז.",
            "sourceUrl": "https://www.nytimes.com/example-us-iran-strikes",
        },
        {
            "source": "וואלה חדשות - מבזקים",
            "category": "ביטחון",
            "headline": "ארה״ב אישרה תקיפות הגנתיות בתוך איראן",
            "originalTitle": "ארה\"ב אישרה כי כוחותיה ביצעו הלילה תקיפות \"להגנה עצמית\" בשטח איראן",
            "context": "פיקוד המרכז האמריקני אישר שכוחות ארה״ב תקפו בתוך איראן אתרי שיגור טילים וסירות שניסו להניח מוקשים. הפיקוד הציג את הפעולה כהגנה עצמית במהלך הפסקת האש.",
            "sourceUrl": "https://news.walla.co.il/break/example-us-iran-strikes",
        },
    ),
    (
        "hormuz_talks_background_not_same_as_strike",
        False,
        {
            "source": "The Guardian Middle East",
            "category": "ביטחון",
            "headline": "רוביו מאיים לפתוח את הורמוז בזמן שיחות עם איראן",
            "originalTitle": "Tehran expresses ‘resolute support’ for Hezbollah – as it happened",
            "context": "שר החוץ האמריקני מרקו רוביו אמר שמצר הורמוז חייב להיפתח כך או אחרת, אחרי תקיפות אמריקניות בדרום איראן. במקביל, נציגים איראניים הגיעו לדוחא לשיחות על הסכם אפשרי.",
            "sourceUrl": "https://www.theguardian.com/example-hormuz-talks",
        },
        {
            "source": "New York Times Middle East",
            "category": "ביטחון",
            "headline": "ארה״ב ביצעה תקיפות הגנה עצמית בדרום איראן",
            "originalTitle": "U.S. Carries Out Renewed Strikes in Southern Iran",
            "context": "פיקוד המרכז האמריקני מסר כי תקף אתרי שיגור טילים וסירות איראניות שניסו להניח מוקשים ליד בנדר עבאס.",
            "sourceUrl": "https://www.nytimes.com/example-us-iran-strikes",
        },
    ),
    (
        "weather_shavuot_rain_wind",
        True,
        {
            "source": "וואלה חדשות",
            "category": "חדשות",
            "headline": "גשם ורוחות ילוו את ערב שבועות בצפון ובמרכז",
            "originalTitle": "חג שבועות חורפי: גשם מקומי ורוחות ערות ברחבי הארץ",
            "context": "היום ומחר צפויה ירידה בטמפרטורות, עם גשם מקומי בצפון ובמרכז ורוחות ערות.",
            "sourceUrl": "https://news.walla.co.il/item/3839781",
        },
        {
            "source": "מעריב - חדשות",
            "category": "חדשות",
            "headline": "גשם ורוחות צפויים בערב חג השבועות",
            "originalTitle": "רגע לפני ערב חג השבועות - שינוי מפתיע במזג האוויר",
            "context": "בערב חג השבועות צפויה ירידה נוספת בטמפרטורות. בצפון ובמרכז צפויים גשמים ורוחות.",
            "sourceUrl": "https://www.maariv.co.il/news/weather/article-1323962",
        },
    ),
    (
        "same_concert_move",
        True,
        {
            "source": "וואלה חדשות",
            "category": "תרבות",
            "headline": "נשף רוק של אביב גפן הוקדם ל־17 ביוני",
            "context": "המופע הוקדם בגלל שלוש הופעות ענק באזור גוש דן באותו שבוע.",
            "sourceUrl": "https://news.walla.co.il/example-a",
        },
        {
            "source": "ישראל היום - כל הכתבות",
            "category": "תרבות",
            "headline": "נשף רוק הוקדם בגלל שלוש הופעות ענק בגוש דן",
            "context": "אביב גפן הזיז את הנשף ל־17 ביוני כדי לא להתנגש עם עומס מופעים גדול בגוש דן.",
            "sourceUrl": "https://www.israelhayom.co.il/example-b",
        },
    ),
    (
        "lod_residential_fire_cross_category",
        True,
        {
            "source": "חדשות 12",
            "category": "חדשות",
            "headline": "18 דיירים חולצו משריפה בבניין בלוד",
            "originalTitle": "18 דיירים חולצו משריפה בבניין מגורים בלוד",
            "context": "צוותי כבאות חילצו 18 דיירים מבניין מגורים בלוד לאחר שפרצה בו שריפה.",
            "sourceUrl": "https://www.mako.co.il/news-example-lod-fire",
        },
        {
            "source": "מעריב - חדשות",
            "category": "פלילים",
            "headline": "שריפה בבניין בלוד הסתיימה בחילוץ דיירים",
            "originalTitle": "שריפה פרצה בבניין מגורים בלוד; דיירים חולצו מהמקום",
            "context": "כוחות הכיבוי פינו דיירים מבניין בלוד בעקבות שריפה שפרצה במקום.",
            "sourceUrl": "https://www.maariv.co.il/news/israel/example-lod-fire",
        },
    ),
    (
        "kiryat_shmona_rocket_cross_source",
        True,
        {
            "source": "וואלה חדשות",
            "category": "ביטחון",
            "headline": "רקטה פגעה במרכז קריית שמונה וגרמה נזק כבד לעסקים",
            "originalTitle": "לילה לא שקט בצפון: פגיעה ישירה בקריית שמונה - נזק כבד לעסקים, אין נפגעים",
            "context": "במהלך הלילה נורו עשרה שיגורים מלבנון לעבר קריית שמונה והגליל העליון, ותשעה מהם יורטו.",
            "sourceUrl": "https://news.walla.co.il/item/example-k8",
        },
        {
            "source": "הארץ - חדשות",
            "category": "ביטחון",
            "headline": "רקטה נפלה במרכז קריית שמונה אחרי מטח מלבנון",
            "originalTitle": "ירי בלתי פוסק לעבר הצפון: רקטה נפלה בקריית שמונה",
            "context": "רקטה ששוגרה מלבנון נפלה בקריית שמונה וגרמה נזק לחנויות ולעסקים, ללא נפגעים.",
            "sourceUrl": "https://www.haaretz.co.il/example-k8",
        },
    ),
    (
        "yirka_samer_halabi_murder_cross_source",
        True,
        {
            "source": "ynet - מבזקי החדשות",
            "category": "פלילים",
            "headline": "סאמר חלבי בן ה־24 נרצח בירכא במהלך חגיגת יום הולדת",
            "originalTitle": "הנרצח בירכא: תושב היישוב סאמר חלבי",
            "context": "סאמר חלבי, בן 24 מירכא, נורה למוות במהלך חגיגת יום הולדת ביישוב.",
            "sourceUrl": "https://www.ynet.co.il/news/article/example-yirka",
        },
        {
            "source": "וואלה חדשות - מבזקים",
            "category": "פלילים",
            "headline": "בן 24 נרצח בירכא והירי נשאר ללא חשודים",
            "originalTitle": "בן 24 נורה למוות בירכא; המשטרה פתחה בחקירה",
            "context": "גבר בן 24 מירכא נורה למוות, והמשטרה טרם איתרה חשודים בירי.",
            "sourceUrl": "https://news.walla.co.il/break/example-yirka",
        },
    ),
    (
        "iran_hardliners_against_us_deal_cross_source",
        True,
        {
            "source": "ynet - כל ערוץ החדשות",
            "category": "ביטחון",
            "headline": "הקיצונים באיראן לוחצים על חמינאי לבלום הסכם עם ארה״ב",
            "originalTitle": "עצרות המונים ומכתב מתריס למנהיג העליון: הקיצונים באיראן שפועלים נגד ההסכם",
            "context": "פלג קיצוני בהנהגה האיראנית מפעיל לחץ על חמינאי נגד הסכם עם ארה״ב, כולל עצרות ומכתב שמאשים את צוות המשא ומתן בפיוס יתר.",
            "sourceUrl": "https://www.ynet.co.il/news/article/example-iran-hardliners",
        },
        {
            "source": "N12 - בעולם",
            "category": "ביטחון",
            "headline": "המחנה הקיצוני באיראן לוחץ נגד הסכם עם ארה״ב",
            "originalTitle": "המאבק בתוך איראן נגד ההסכם: טראמפ חייב לדעת, טהראן קובעת את התנאים",
            "context": "גורמים במחנה הקיצוני בטהראן דורשים להקשיח תנאים מול טראמפ ולמנוע פשרה מהירה במשא ומתן עם ארה״ב.",
            "sourceUrl": "https://www.mako.co.il/news-world/example-iran-hardliners",
        },
    ),
    (
        "zaporizhzhia_drone_nuclear_plant_cross_category",
        True,
        {
            "source": "מעריב - מבזקים",
            "category": "אקטואליה בעולם",
            "headline": "כטב״ם פגע במבנה טורבינה בתחנת הכוח הגרעינית זפוריז׳יה",
            "originalTitle": "הסוכנות הבינלאומית לאנרגיה אטומית: כטב\"ם פגע במבנה טורבינה בתחנת כוח גרעינית באוקראינה",
            "context": "סבא״א קיבלה עדכון מתחנת הכוח הגרעינית זפוריז׳יה באוקראינה שלפיו כטב״ם פגע במבנה טורבינה וגרם לחור בקיר.",
            "sourceUrl": "https://www.maariv.co.il/breaking-news/article-1327267",
        },
        {
            "source": "וואלה חדשות - מבזקים",
            "category": "ביטחון",
            "headline": "כטב״ם אוקראיני פגע בתחנת הכוח הגרעינית בזפוריז׳יה",
            "originalTitle": "כטב\"ם אוקראיני פגע בתחנת כוח רוסית",
            "context": "כטב״ם אוקראיני פגע בתחנת הכוח הגרעינית בזפוריז׳יה והעלה חשש סביב בטיחות המתקן.",
            "sourceUrl": "https://news.walla.co.il/break/3841879",
        },
    ),
    (
        "trump_iran_nuclear_agreement_terms_cross_source",
        True,
        {
            "source": "ישראל היום - כל הכתבות",
            "category": "ביטחון",
            "headline": "טראמפ עצר את הסכם איראן ודרש פיקוח גרעיני הדוק יותר",
            "originalTitle": "בלם את ההסכם ברגע האחרון: הדרישות החדשות שהציב טראמפ לאיראנים",
            "context": "טראמפ בלם את החתימה על מזכר ההבנות עם איראן ודרש להקשיח סעיפים על פיקוח גרעיני ועל פתיחת מצר הורמוז.",
            "sourceUrl": "https://www.israelhayom.co.il/example-trump-iran-terms",
        },
        {
            "source": "וואלה חדשות - מבזקים",
            "category": "ביטחון",
            "headline": "טראמפ טוען שאיראן הסכימה לוותר על נשק גרעיני",
            "originalTitle": "טראמפ לרשת פוקס: איראן הסכימה לא לפתח ולא לרכוש נשק גרעיני",
            "context": "טראמפ אמר שהסכם איראן יתקדם רק אם טהרן תוותר גם על רכישה עתידית של נשק גרעיני ותעמוד בתנאי הגרעין האמריקניים.",
            "sourceUrl": "https://news.walla.co.il/break/example-trump-iran-nuclear",
        },
    ),
    (
        "us_iran_hormuz_base_attacks_cross_source",
        True,
        {
            "source": "BBC World",
            "category": "ביטחון",
            "headline": "ארה״ב תקפה מכ״מים איראניים אחרי ירי באזור הורמוז",
            "context": "ארה״ב תקפה מכ״מים וסוללות באזור הורמוז לאחר ירי לעבר כוחות אמריקניים במפרץ.",
            "sourceUrl": "https://www.bbc.com/news/articles/crlpy8n7pr6o",
        },
        {
            "source": "The Guardian Middle East",
            "category": "ביטחון",
            "headline": "איראן טוענת שתקפה בסיס אמריקאי באזור המפרץ",
            "context": "איראן הציגה את הירי באזור המפרץ כתגובה לעימות עם ארה״ב סביב הורמוז והתקיפות האמריקניות.",
            "sourceUrl": "https://www.theguardian.com/world/2026/jun/01/iran-strikes-us-military-base-kuwait-iranian-air-defences",
        },
    ),
    (
        "kahlon_unetcredit_conviction_cross_category",
        True,
        {
            "source": "The Jerusalem Post - Israel News",
            "category": "כלכלה",
            "headline": "משה כחלון הורשע בעבירת דיווח בפרשת יונט קרדיט",
            "originalTitle": "Former finance minister Kahlon convicted of reporting offense in UnetCredit collapse case",
            "context": "משה כחלון הורשע במסגרת הסדר טיעון בכך שלא דאג שחריגות כספיות חמורות ביונט קרדיט ידווחו לציבור כשכיהן כיו״ר החברה.",
            "sourceUrl": "https://www.jpost.com/israel-news/politics-and-diplomacy/article-897837",
        },
        {
            "source": "דה מרקר - כל הכתבות",
            "category": "משפט",
            "headline": "משה כחלון הורשע בהסתרת מידע בפרשת יונט קרדיט",
            "context": "גם שר אוצר לשעבר נבחן כחוסם מידע לציבור כשהוא יושב בראש חברה ציבורית.",
            "sourceUrl": "https://www.themarker.com/law/example-unetcredit-kahlon",
        },
    ),
    (
        "kahlon_unetcredit_walla_jpost_live_duplicate",
        True,
        {
            "source": "וואלה חדשות",
            "category": "משפט",
            "headline": "משה כחלון הורשע בפרשת יונט קרדיט",
            "originalTitle": "משה כחלון הורשע במסגרת הסדר טיעון: \"לא הביא את מלוא המידע לידיעת הדירקטוריון והציבור\"",
            "context": "משה כחלון הודה והורשע לפי חוק ניירות ערך על תקופתו כיו״ר יונט קרדיט. ההסדר מבקש מאסר על תנאי, קנס של 180 אלף שקל והגבלת כהונה בחברה ציבורית ל־18 חודשים.",
            "sourceUrl": "https://news.walla.co.il/item/3841967",
        },
        {
            "source": "The Jerusalem Post - Israel News",
            "category": "כלכלה",
            "headline": "משה כחלון הורשע בעבירת דיווח בפרשת יונט קרדיט",
            "originalTitle": "Former finance minister Kahlon convicted of reporting offense in UnetCredit collapse case",
            "context": "משה כחלון הורשע במסגרת הסדר טיעון על הסתרת מידע מיונט קרדיט מציבור המשקיעים בזמן שכיהן כיו״ר החברה.",
            "sourceUrl": "https://www.jpost.com/israel-news/politics-and-diplomacy/article-897837",
        },
    ),
    (
        "knesset_dissolution_first_reading_cross_source",
        True,
        {
            "source": "The Jerusalem Post - Israel News",
            "category": "פוליטיקה",
            "headline": "פיזור הכנסת עבר בקריאה ראשונה ללא מתנגדים",
            "originalTitle": "Bill to dissolve Knesset passes first reading, advancing process to move up elections",
            "context": "הצעת הקואליציה לפיזור הכנסת אושרה במליאה ברוב של 106 מול 0, על רקע המשבר מול המפלגות החרדיות סביב חוק הגיוס. מועד הבחירות ייקבע לפני הקריאות השנייה והשלישית.",
            "sourceUrl": "https://www.jpost.com/israel-news/politics-and-diplomacy/article-898048",
        },
        {
            "source": "הארץ - חדשות",
            "category": "פוליטיקה",
            "headline": "הכנסת אישרה בקריאה ראשונה את חוק פיזורה",
            "originalTitle": "הכנסת אישרה בקריאה ראשונה את הצעת החוק לפיזורה",
            "context": "הכנסת אישרה בקריאה ראשונה את הצעת חוק פיזורה ברוב של 106 תומכים וללא מתנגדים. מועד הבחירות האפשרי נע בין 8 בספטמבר ל־20 באוקטובר, והקואליציה תקבע תאריך סופי לפני הקריאות הבאות.",
            "sourceUrl": "https://www.haaretz.co.il/news/politi/2026-06-02/ty-article/0000019e-8470-da5c-a9bf-df7e038a0000",
        },
    ),
    (
        "trump_cancelled_beirut_strike_cross_source",
        True,
        {
            "source": "וואלה חדשות - חדשות בעולם",
            "category": "ביטחון",
            "headline": "טראמפ בלם תוכנית ישראלית לתקוף בביירות",
            "originalTitle": "\"אתה משוגע וכפוי טובה\": שיחת הקללות בין טראמפ לנתניהו",
            "context": "טראמפ עצר תוכנית ישראלית לתקוף בביירות במסגרת העימות מול חיזבאללה, אחרי שיחה קשה עם נתניהו ועל רקע המו״מ האמריקני עם איראן.",
            "sourceUrl": "https://news.walla.co.il/item/3842531",
        },
        {
            "source": "The Jerusalem Post - Israel News",
            "category": "ביטחון",
            "headline": "בכירים בישראל תקפו את ביטול התקיפה בביירות בלחץ טראמפ",
            "originalTitle": "Time to say no to Trump: Israeli officials condemn Netanyahu's decision to cancel Lebanon strike",
            "context": "בכירים בישראל מתחו ביקורת על החלטת נתניהו לבטל תקיפה בביירות בעקבות לחץ מטראמפ, כחלק מאותו אירוע ביטול תקיפה מול חיזבאללה.",
            "sourceUrl": "https://www.jpost.com/israel-news/politics-and-diplomacy/article-898056",
        },
    ),
    (
        "us_iran_tanker_not_kuwait_air_defense_20260603",
        False,
        {
            "source": "The Guardian Middle East",
            "category": "ביטחון",
            "headline": "ארה״ב השביתה מכלית בדרך לאיראן והחריפה את משבר הורמוז",
            "originalTitle": "US fires missile at tanker attempting to reach Iran amid strait of Hormuz standoff",
            "context": "כוחות אמריקניים ירו טיל הלפייר לעבר חדר המנוע של מכלית שניסתה להגיע לאיראן אחרי 24 שעות של אזהרות.",
            "sourceUrl": "https://www.theguardian.com/world/2026/jun/03/us-fires-missile-tanker-strait-of-hormuz",
        },
        {
            "source": "מעריב - מבזקים",
            "category": "ביטחון",
            "headline": "כווית הפעילה הגנה אווירית מול טילים וכטב״מים",
            "originalTitle": "צבא כווית: מערכות ההגנה פועלות שוב ליירוט מתקפת טילים וכטב\"מים",
            "context": "צבא כווית הודיע שמערכות ההגנה האווירית פועלות נגד טילים וכטב״מים עוינים כחלק מהסלמה אזורית במפרץ.",
            "sourceUrl": "https://www.maariv.co.il/breaking-news/article-1328644",
        },
    ),
    (
        "trump_hormuz_leverage_not_written_nuclear_terms_20260603",
        False,
        {
            "source": "New York Times Middle East",
            "category": "ביטחון",
            "headline": "טראמפ זלזל באיום האיראני לסגור את מצר הורמוז",
            "originalTitle": "Trump Underestimated Iran’s Threat to Close the Strait of Hormuz",
            "context": "ממשל טראמפ העריך בחסר את יכולת איראן להפוך את איום הורמוז למנוף אסטרטגי במגעים מול וושינגטון.",
            "sourceUrl": "https://www.nytimes.com/2026/06/02/us/politics/trump-iran-strait-of-hormuz.html",
        },
        {
            "source": "ישראל היום - כל הכתבות",
            "category": "ביטחון",
            "headline": "טראמפ דורש מאיראן התחייבויות גרעין כתובות לפני הסכם",
            "originalTitle": "טראמפ דורש התחייבויות כתובות מאיראן לפני הסכם גרעין",
            "context": "הבית הלבן דורש מאיראן ויתורים כתובים ומפורטים בנושא הגרעין לפני הסכם ראשוני ומסרב לשחרר נכסים לפני ביצוע התחייבויות.",
            "sourceUrl": "https://www.israelhayom.co.il/news/world-news/middle-east/article/20677467",
        },
    ),
    (
        "different_weather_city_forecast",
        False,
        {
            "source": "השירות המטאורולוגי",
            "category": "מזג אוויר",
            "headline": "מזג האוויר בירושלים: 12°–20°; עננות חלקית",
            "context": "בירושלים צפויה עננות חלקית וקרינה גבוהה בצהריים.",
            "sourceUrl": "https://ims.gov.il/jerusalem",
        },
        {
            "source": "וואלה חדשות",
            "category": "חדשות",
            "headline": "גשם ורוחות ילוו את ערב שבועות בצפון ובמרכז",
            "context": "בערב החג צפויים גשם ורוחות בצפון ובמרכז.",
            "sourceUrl": "https://news.walla.co.il/item/3839781",
        },
    ),
]


def main() -> int:
    failures = []
    for name, expected, a, b in CASES:
        got = likely_duplicate_story(a, b)
        if got != expected:
            failures.append(f"{name}: expected {expected}, got {got}")
    if failures:
        print("Semantic duplicate drill failed:")
        for failure in failures:
            print("-", failure)
        return 1

    older_detailed = {
        "source": "מקור א",
        "publishedAt": "2026-05-26T06:00:00+03:00",
        "headline": "ארה״ב תקפה בדרום איראן",
        "context": "פירוט ארוך מאוד על התקיפה, השיחות, הורמוז ובנדר עבאס " * 5,
        "takeaway": "טייקאוויי מפורט",
        "sourceUrl": "https://example.com/older",
    }
    newer_shorter = {
        "source": "מקור ב",
        "publishedAt": "2026-05-26T07:00:00+03:00",
        "headline": "ארה״ב תקפה באיראן",
        "context": "עדכון קצר אך מאוחר יותר",
        "takeaway": "",
        "sourceUrl": "https://example.com/newer",
    }
    preferred = update_feed.preferred_duplicate_item(older_detailed, newer_shorter)
    if preferred is not newer_shorter:
        print("Semantic duplicate drill failed:")
        print("- preferred_duplicate_item: expected freshest duplicate to win over older detailed card")
        return 1

    print(f"Semantic duplicate drill passed: {len(CASES)}/{len(CASES)} + freshest-preferred")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
