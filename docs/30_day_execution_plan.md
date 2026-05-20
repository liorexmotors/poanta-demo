# Poanta — תוכנית ביצוע 30 יום לאפליקציה אמיתית

עודכן: 2026-05-20

## יעד 30 יום
בסוף 30 יום צריך להיות:
- Backend staging עובד.
- API שמגיש פיד מ־DB, לא רק קובץ סטטי.
- Worker שמריץ איסוף/עריכה/QA/מבקר.
- אפליקציית Expo בסיסית מחוברת ל־API.
- Build פנימי ל־Android ו־iOS.
- מסמכי Privacy/Terms ראשוניים.
- מוכנות ל־TestFlight ו־Google Internal Testing.

## שבוע 1 — יסודות מוצר ותשתית

### יום 1–2: החלטות מוצר
- לסגור שם עבודה: Pointa / Poanta / פואנטה.
- לסגור MVP 1.0.
- לסגור פיצ׳רים שלא נכנסים עכשיו.
- להחליט: device id אנונימי או משתמשים עם login.

### יום 2–3: Repo structure
להוסיף מבנה Production ליד הדמו הקיים:

```text
projects/poanta-demo/
  apps/
    mobile/
  services/
    api/
    worker/
  packages/
    schemas/
  infra/
  docs/
```

### יום 3–5: Backend skeleton
- FastAPI health endpoint.
- Docker compose מקומי: api + postgres + redis.
- DB migrations ראשונות.
- `GET /v1/feed` מחזיר פיד sample.
- Sentry/logging בסיסי.

### תוצר שבוע 1
- Backend מקומי עובד.
- מסמך החלטות חתום.
- תשתית repo מוכנה.

## שבוע 2 — Feed Service ו־Jobs

### Feed DB
- טבלאות: sources, raw_candidates, feed_items, feed_versions.
- import ראשוני מ־feed.json הקיים.
- API מחזיר פיד מ־DB.

### Workers
- העברת איסוף RSS/Telegram למסלול worker.
- שמירת raw candidates.
- יצירת draft feed.
- Quality gate כשלב חובה.
- publish יוצר feed_version.

### Auditor/Repair
- המבקר רץ מול API/staging.
- repair queue שקט.
- logs במקום הצפה לליאור.

### תוצר שבוע 2
- Staging feed API עובד.
- ניתן לפרסם feed_version ולבצע rollback.
- המבקר בודק את ה־API החדש.

## שבוע 3 — Mobile App MVP

### הקמת Expo
- יצירת `apps/mobile`.
- RTL עברית.
- Theme ראשוני לפי הדמו.
- fetch ל־`/v1/feed`.

### מסכים
- Feed screen.
- Card component.
- Preferences screen.
- Saved screen.
- More screen.

### Local persistence
- device id.
- preferences.
- read/saved state.

### תוצר שבוע 3
- אפליקציה רצה בסימולטור/מכשיר.
- Android APK פנימי.
- iOS simulator/TestFlight prep.

## שבוע 4 — Beta readiness

### תשתית
- Deploy staging cloud.
- CDN/DNS.
- Monitoring.
- Backups.
- Load test בסיסי.

### חנויות
- Apple Developer / Google Play Developer.
- Bundle ID / Package name.
- Privacy Policy.
- Terms.
- App screenshots.
- Store descriptions.

### בדיקות
- QA תוכן.
- QA UI RTL.
- בדיקת טעינה.
- בדיקת offline/שגיאות רשת.
- בדיקת שמורים/העדפות.

### תוצר שבוע 4
- TestFlight candidate.
- Google Internal Testing candidate.
- רשימת Beta testers.
- החלטת Go/No-Go ל־חנויות.

## משימות מיידיות — עכשיו

### טכני
1. ליצור מבנה תיקיות Production.
2. לכתוב DB schema ראשוני.
3. להקים FastAPI skeleton.
4. להוסיף docker-compose מקומי.
5. לכתוב importer מ־feed.json ל־Postgres.

### מוצר
1. לסגור שם סופי.
2. לסגור אם יש login ב־1.0.
3. לסגור תקציב hosting התחלתי.
4. לסגור אם push נדחה או נכנס ל־Beta.

### משפטי/חנויות
1. להחליט על שם חשבונות Apple/Google.
2. להכין Privacy Policy.
3. להכין Terms.
4. להכין App Store copy ראשוני.

## החלטות שאני ממליצה לקבל עכשיו

### שם
לא לנעול שם כרגע. להשתמש ב־working name פנימי בלבד עד החלטה של ליאור.

### Login
לא ב־1.0.
להתחיל עם device id אנונימי.
סיבה: פחות friction, פחות privacy burden, פחות סיכוי לדחייה/מורכבות.

### Push
לא בגרסה הראשונה.
להוסיף אחרי Beta.
סיבה: עדיף לא לשלוח התראות לפני שהאלגוריתם יודע מה באמת חשוב למשתמש.

### Hosting
להתחיל עם:
- Render/Fly.io ל־API/worker
- Neon/Supabase Postgres
- Upstash Redis
- Cloudflare

### Mobile
Expo / React Native.

## Go/No-Go לפני חנויות

מותר להגיש לחנויות רק אם:
- הפיד יציב 7 ימים.
- אין שגיאות תוכן קריטיות פתוחות.
- זמן טעינה טוב.
- Beta testers לא מדווחים על בלבול/חוסר אמון.
- Privacy/Terms מוכנים.
- rollback עובד.

## סיכום
הצעד הראשון אינו “להגיש אפליקציה”.
הצעד הראשון הוא להפוך את Poanta ממערכת דמו חכמה למערכת Production:
Backend, API, DB, jobs, QA, monitoring — ואז Mobile app מעל זה.
