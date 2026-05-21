# Poanta Mobile Store Readiness

עודכן: 2026-05-21

## מצב נוכחי
- נוצר שלד Expo / React Native ב־`apps/mobile`.
- האפליקציה מחוברת כרגע לפיד החי הסטטי: `https://liorexmotors.github.io/poanta-demo/feed.json`.
- השפה הוויזואלית הראשונה הותאמה לפיד: רקע כהה, צהוב Pointa, כרטיסי חדשות קומפקטיים, RTL עברי.
- זה עדיין לא build חנות; זה בסיס טכני ל־MVP.

## יעד MVP ראשון לבדיקה
1. פיד ראשי עובד Native.
2. כרטיסים עם תמונה, כותרת, תקציר, פואנטה, מקור וזמן.
3. שמירה מקומית של כתבות.
4. פילטר תחומים בסיסי.
5. פתיחת מקור מקורי בדפדפן פנימי/חיצוני.
6. מסך עוד: אודות, פרטיות, תמיכה, שיתוף אפליקציה.
7. חיבור ל־Feed API staging במקום קובץ GitHub Pages לפני Beta.

## Not now לגרסה הראשונה
- הרשמה/לוגין מלאים.
- פוש נוטיפיקיישנס.
- פרסומות/תשלומים.
- פרסונליזציה מורכבת.
- תגובות/קהילה.

## דרישות לפני Google Play / App Store
### טכני
- `android.package` ו־`ios.bundleIdentifier` סופיים.
- אייקון, splash, adaptive icon אמיתיים.
- EAS Build מוגדר.
- build פנימי לאנדרואיד.
- TestFlight build לאייפון.
- staging API יציב + ניטור.

### מוצר/משפטי
- שם ציבורי סופי: Pointa / Poanta / פואנטה.
- Privacy Policy URL.
- Support URL.
- Terms / disclaimer לתוכן חדשות מסוכם AI.
- טקסטים לחנויות: short description, long description, subtitle, keywords.
- Screenshots לפי גדלים.
- Google Data Safety + Apple Privacy Nutrition Labels.

## החלטות שנצטרך מליאור, אבל לא עכשיו
- חשבון Apple/Google אישי או חברה.
- שם סופי לחנות.
- האם ה־MVP הראשון חינם בלבד.
- תקציב backend חודשי ראשוני.

## שער איכות לפני Beta
- TypeScript נקי.
- build Android פנימי עובר.
- build iOS/TestFlight עובר.
- 0 קריסות במסלול טעינה בסיסי.
- זמן טעינה סביר על רשת סלולרית.
- הפיד לא מציג כרטיסים ריקים/שבורים.
