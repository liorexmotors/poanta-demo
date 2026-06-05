# Stage 4 domain rescue blocked — חדשות — 2026-06-05 21:30

סטטוס: חסום / deploy=no

## מה נמצא
- Autopilot עבר אחרי תיקון Stage 3 ל־`domain_sla_breach` עבור `חדשות`.
- נוצר run: `tmp/editor-runs/domain-חדשות-20260605-213004`.
- `run.json`:
  - `items`: 4
  - `usableArticleText`: 0
  - `selectedUsable`: 0
  - `selectedThin`: 4
  - `domainFilteredOutAfterExtraction`: 14
- כל הפריטים שנבחרו הם Google News/AP/Reuters bridge rows ללא `articleText` שמיש.

## החלטה
לא נכתבו תוצאות עורך, לא בוצע apply, ולא בוצע deploy.
לפי כללי משה/Pointa, לא מפרסמים כרטיסי title-only/description-only ולא מורידים סף איכות כדי לסגור SLA דומיין.

## מצב ציבורי נפרד
- Stage 3 תיקן ופרסם את הפיד הראשי הציבורי: top item `ארגון חרדי מזהיר שמעצרי משתמטים פוגעים בגיוס חרדים` ב־`2026-06-05T21:13:00+03:00`.
- מבזקים פורסמו בנפרד עם top `עשרות חרדים מפגינים מול תחנת משטרה בירושלים - ומנסים לשבור את השער`.

## נדרש בהמשך
לחזק source acquisition / extraction / selection עבור דומיין `חדשות`, כדי שלא ייבחרו bridge-thin rows ללא טקסט כתבה שמיש.
