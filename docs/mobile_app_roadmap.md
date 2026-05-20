# תוכנית עבודה — מעבר Poanta לאפליקציה אמיתית

עודכן: 2026-05-20

## מטרת השלב
להעביר את Poanta ממוצר דמו סטטי/פיד חי למוצר Production מלא:
- אפליקציה אמיתית ל־iOS ו־Android.
- Backend יציב שמייצר, מאחסן ומגיש פיד למשתמשים רבים.
- תשתית אחסון/שרתים שיכולה לגדול.
- הכנה לפרסום ב־App Store וב־Google Play.
- שמירה על איכות התוכן, המבקר, השוער והעורך כמנגנוני Production ולא כטלאים ידניים.

## עקרונות
1. לא קופצים ישר לחנויות לפני שה־Backend והאיכות יציבים.
2. האפליקציה הראשונה צריכה להיות פשוטה, מהירה ואמינה — לא עמוסה בפיצ׳רים.
3. כל מה שעובד היום בדמו צריך להפוך לשירות מסודר: feed API, jobs, logs, monitoring, QA gates.
4. ליאור צריך לקבל החלטות מוצר/עסק, לא שגיאות תפעול.
5. כל שלב צריך להסתיים בגרסה שאפשר לבדוק בפועל.

## שלב 0 — הקפאת MVP והגדרת מוצר
משך משוער: 2–4 ימים

### החלטות מוצר
- שם סופי: פתוח בדיון. אין לנעול שם ציבורי/חנויות בשלב זה.
- שפת ברירת מחדל: עברית.
- קהל יעד ראשון: ישראלים שרוצים חדשות קצרות וברורות.
- פיצ׳רי MVP:
  - פיד חדשות חכם.
  - כותרת + תמצית + הפואנטה.
  - סינון לפי תחומי עניין ומקורות.
  - שמירה לקריאה חוזרת.
  - שיתוף לאפליקציה/שיתוף כתבה.
  - התראות פוש רק בהמשך, לא בהכרח בגרסה הראשונה.

### תוצרים
- מסמך אפיון MVP קצר.
- רשימת פיצ׳רים שנכנסים לגרסה 1.0 ורשימת Not now.
- החלטה על שם/מיתוג ראשוני.

## שלב 1 — ארכיטקטורת Production
משך משוער: 3–5 ימים

### המלצת ארכיטקטורה
- Frontend app: React Native / Expo.
- Backend API: Node.js/NestJS או Python/FastAPI.
- DB: PostgreSQL.
- Cache: Redis.
- Queue/jobs: BullMQ / Celery / Cloud Tasks.
- Object storage: S3-compatible storage לתמונות/לוגים/ארכיונים.
- CDN: Cloudflare.
- Hosting ראשוני מומלץ:
  - אופציה פשוטה: Render/Fly.io/Railway + Supabase/Neon + Cloudflare.
  - אופציה חזקה יותר: AWS/GCP עם managed Postgres, Redis, autoscaling.

### למה לא להישאר רק GitHub Pages
GitHub Pages מתאים לדמו, לא ל־Production עם:
- משתמשים רבים.
- פידים אישיים.
- התראות.
- לוגים ומוניטורינג.
- API מאובטח.
- תורים ועבודות רקע.

### תוצרים
- דיאגרמת מערכת.
- בחירת stack.
- סביבת staging ראשונה.

## שלב 2 — Backend Feed Service
משך משוער: 1–2 שבועות

### רכיבים
- API ציבורי/מאובטח:
  - `GET /feed`
  - `GET /feed/personalized`
  - `GET /sources`
  - `POST /events/read`
  - `POST /events/save`
- מנגנון משתמשים אנונימי בהתחלה: device id + preferences.
- שמירת פידים היסטוריים וגרסאות.
- הפרדה בין:
  - raw candidates
  - editor output
  - approved feed items
  - live published feed

### העברת הסוכנים ל־Production
- האספן: job שמביא RSS/מקורות.
- העורך: job שמייצר כרטיסים.
- השוער: quality gate לפני publish.
- המבקר: live audit קבוע.
- המתקן: repair queue שקט.

### תוצרים
- API עובד ב־staging.
- פיד חי שיוצא מה־Backend ולא מקובץ סטטי בלבד.
- dashboard/log בסיסי למצב הפיד.

## שלב 3 — אפליקציית Mobile MVP
משך משוער: 2–4 שבועות

### בחירת טכנולוגיה
המלצה: Expo / React Native.

סיבות:
- פיתוח מהיר ל־iOS ו־Android יחד.
- קל לבנות גרסאות TestFlight ו־Google Internal Testing.
- אפשר לשמור UI קרוב לדמו הנוכחי.
- תומך בהמשך בפוש, analytics, deep links.

### מסכים ראשונים
1. פיד ראשי.
2. כרטיס כתבה.
3. העדפות — מקורות, תחומי עניין, טווח ימים.
4. שמורים.
5. עוד — שיתוף אפליקציה, אודות, פרטיות.

### תוצרים
- APK/Test build לאנדרואיד.
- TestFlight build לאייפון.
- חיבור ל־Backend staging.

## שלב 4 — תשתית עומסים ואמינות
משך משוער: 1–2 שבועות

### יעדי Production ראשונים
- 1,000–10,000 משתמשים פעילים בלי שינוי ארכיטקטורה גדול.
- Cache לפידים נפוצים.
- CDN לתמונות/נכסים.
- DB backups יומיים.
- ניטור שגיאות.
- alerting שקט: רק תקלות שדורשות החלטה/התערבות.

### כלים מומלצים
- Cloudflare CDN + DNS.
- Sentry לשגיאות אפליקציה/API.
- UptimeRobot/BetterStack לניטור uptime.
- PostHog/Firebase Analytics לאנליטיקה.
- Grafana/managed metrics בהמשך.

### תוצרים
- Monitoring dashboard.
- Load test בסיסי.
- Runbook לתקלות.

## שלב 5 — App Store / Google Play Readiness
משך משוער: 1–3 שבועות, תלוי חשבונות ואישורים

### Apple
- פתיחת Apple Developer Account.
- Bundle ID.
- App Store Connect.
- TestFlight.
- Privacy Nutrition Labels.
- Screenshots בגדלים הנדרשים.
- טקסטים: שם, subtitle, description, keywords.
- Privacy Policy URL.
- Support URL.

### Google Play
- Google Play Developer Account.
- Package name.
- Internal testing track.
- Data safety form.
- Screenshots.
- Short/long description.
- Privacy Policy URL.

### מסמכים נדרשים
- Privacy Policy.
- Terms of Use.
- Content disclaimer: סיכום חדשות מבוסס AI, ייתכנו טעויות, המקורות המקוריים זמינים.
- DMCA/זכויות יוצרים/מדיניות מקורות — לבדיקה משפטית.

### תוצרים
- TestFlight פעיל.
- Google internal testing פעיל.
- חבילות מוכנות להגשה.

## שלב 6 — Beta סגורה
משך משוער: 1–2 שבועות

### קהל
- 20–100 משתמשים ראשונים.

### מדדים
- זמן טעינה.
- כמה כרטיסים נקראים בסשן.
- כמה פותחים מקור מקורי.
- כמה שומרים/משתפים.
- באילו כרטיסים אנשים נתקעים.
- שגיאות תוכן שנתפסו על ידי משתמשים מול המבקר.

### תוצרים
- רשימת תיקוני Beta.
- החלטה אם מוכנים ל־Public launch.

## שלב 7 — השקה ציבורית
משך משוער: 1 שבוע

### לפני השקה
- Backend production.
- App approved בשתי החנויות.
- דף נחיתה.
- לינק שיתוף חכם שמפנה לפי מכשיר.
- מערכת תמיכה/פידבק.

### אחרי השקה
- ניטור עומסים.
- ניטור איכות תוכן.
- שיפור onboarding.
- Push notifications רק אחרי שמבינים מה באמת חשוב למשתמשים.

## החלטות שצריך מליאור
1. שם סופי ומיתוג: Pointa / Poanta / פואנטה.
2. האם רוצים אפליקציה Native/React Native או קודם PWA משודרג.
3. תקציב שרתים חודשי התחלתי.
4. האם פותחים חשבונות Apple/Google על שם עסק/חברה או אישי.
5. האם רוצים משתמשים והרשמה כבר ב־1.0 או מכשיר אנונימי בלבד.
6. האם יש כוונה למודל עסקי: חינם, פרסומות, פרימיום, B2B, או קודם צמיחה.

## המלצה שלי
לא לדלג ישר לחנויות.

המסלול הנכון:
1. להקים Backend staging אמיתי.
2. להעביר את הפיד והסוכנים לשירות Production מסודר.
3. לבנות אפליקציית Expo שמעתיקה את חוויית הדמו אבל מתחברת ל־API.
4. להוציא TestFlight/Internal Testing.
5. רק אחרי שבוע Beta נקי — להגיש לחנויות.

## תוכנית 30 יום מוצעת

### שבוע 1
- אפיון MVP.
- בחירת stack.
- הקמת repo/סביבת backend staging.
- DB schema ראשוני.

### שבוע 2
- Feed API.
- Jobs לאיסוף/עריכה/QA.
- Dashboard/log בסיסי.
- Monitoring ראשוני.

### שבוע 3
- אפליקציית Expo MVP.
- חיבור ל־API.
- העדפות/שמורים/שיתוף.
- builds פנימיים.

### שבוע 4
- TestFlight + Google Internal Testing.
- Privacy/Terms/App Store assets.
- Beta סגורה.
- תיקוני יציבות ואיכות.

## סיכונים מרכזיים
- איכות תוכן לא יציבה תחת קצב גבוה.
- זכויות יוצרים/שימוש בתוכן מקורות.
- עומס jobs על מודלים/עלויות AI.
- דחיות בחנויות בגלל privacy/content policy.
- התראות פוש לא מדויקות שיכולות לגרום לנטישה.

## מנגנוני הגנה
- Quality gates לפני publish.
- המבקר ב־quiet mode עם escalation רק כשצריך החלטה.
- rollback feed מהיר.
- cache/CDN.
- limits על מקורות/קצב.
- מדיניות תוכן ופרטיות ברורה לפני הגשה לחנויות.
