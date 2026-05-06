# Poanta RSS Research — 2026-05-06

מטרה: לבנות את פואנטה על RSS יציב בלבד בשלב הראשון, ללא סריקת HTML וללא fallback.

## מומלצים לשלב ראשון — RSS תקין בבדיקה חיה

| מקור | RSS | תוצאה |
|---|---|---|
| ynet חדשות | `https://www.ynet.co.il/Integration/StoryRss2.xml` | 30 פריטים, XML תקין |
| ynet מבזקים | `https://www.ynet.co.il/Integration/StoryRss1854.xml` | 30 פריטים, XML תקין |
| ynet ספורט | `https://www.ynet.co.il/Integration/StoryRss3.xml` | 30 פריטים, XML תקין |
| וואלה ראשי | `https://rss.walla.co.il/feed/1?type=main` | 30 פריטים, XML תקין |
| וואלה חדשות | `https://rss.walla.co.il/feed/22` | 60 פריטים, XML תקין |
| וואלה ספורט | `https://rss.walla.co.il/feed/3` | 30 פריטים, XML תקין |
| ישראל היום | `https://www.israelhayom.co.il/rss.xml` | 100 פריטים, XML תקין עם headers רגילים |
| הארץ ראשי/Feedly | `https://www.haaretz.co.il/srv/rss---feedly` | 100 פריטים, XML תקין |
| הארץ דעות | `https://www.haaretz.co.il/srv/rss-opinion` | 100 פריטים, XML תקין |
| הארץ ספורט | `https://www.haaretz.co.il/srv/%D7%A1%D7%A4%D7%95%D7%A8%D7%98--%D7%94%D7%90%D7%A8%D7%A5-rss` | 50 פריטים, XML תקין |
| גלובס שוק ההון | `https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=585` | 15 פריטים, עברית, XML תקין |

## לא מומלצים לשלב ראשון / דורשים טיפול נפרד

| מקור | מצב |
|---|---|
| N12 / mako | endpoints שנבדקו (`/rss`) מחזירים HTML ולא RSS נקי. לא מתאים לשלב RSS-only. |
| כלכליסט | endpoints נפוצים שנבדקו מחזירים 404. צריך למצוא endpoint עדכני אם קיים. |
| TheMarker | עמוד RSS קיים אבל הוא HTML; לא נמצא endpoint XML נקי בבדיקה ראשונה. |
| מעריב | endpoint שנבדק החזיר 403. |
| כאן | endpoint שנבדק החזיר 403. |
| ערוץ 14 | endpoint `/feed/` החזיר 403. |
| ספורט5 | endpoint שנבדק החזיר HTML ולא RSS תקין. |
| גלובס ראשי iID=1725 | XML תקין אבל באנגלית (`News - Globes`), לכן לא מתאים לפיד עברי כללי. להשתמש במדורים עבריים בלבד. |

## המלצה מקצועית

להתחיל עם RSS-only כדי שהמערכת תהיה יציבה, מהירה, חוקית ופשוטה לניטור:

1. שלב ראשון: ynet, וואלה, ישראל היום, הארץ, גלובס מדורים עבריים.
2. בלי scraping ובלי fallback אוטומטי.
3. אם מקור RSS נכשל — מסמנים אותו כתקלה ולא מחליפים בסריקה.
4. רק אחרי שהמוצר יציב, אפשר להוסיף מקורות חסומים דרך הסכם/API/RSS רשמי שמצאנו.

המשמעות: פחות מקורות בהתחלה, אבל איכות תפעולית גבוהה יותר ופחות תקלות.
