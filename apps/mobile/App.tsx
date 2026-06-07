import { StatusBar } from 'expo-status-bar';
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  ActivityIndicator,
  FlatList,
  Image,
  I18nManager,
  Linking,
  Platform,
  InteractionManager,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  useColorScheme,
} from 'react-native';
import Svg, { Circle, Path } from 'react-native-svg';
import { SafeAreaProvider, useSafeAreaInsets } from 'react-native-safe-area-context';
import { fetchBreakingFeed, fetchFeed } from './src/feed';
import { FeedItem } from './src/types';

I18nManager.allowRTL(true);
if (Platform.OS !== 'web') {
  I18nManager.forceRTL(true);
  I18nManager.swapLeftAndRightInRTL(false);
}

// Android RN/Fabric mirrors `textAlign: 'right'` under forced RTL, so Hebrew text
// can render physically left-aligned even though the style says "right".
// Keep writingDirection/direction RTL, but use the mirrored align value on Android
// so the visual result is physical right alignment.
const RTL_TEXT_ALIGN = (Platform.OS === 'android' ? 'left' : 'right') as 'left' | 'right';

type ViewMode = 'home' | 'breaking' | 'saved' | 'search' | 'settings' | 'more';
type MoreScreen = 'menu' | 'settings' | 'appearance' | 'about' | 'terms' | 'privacy' | 'contact';
type AppLanguage = 'he' | 'en' | 'ru' | 'ar';
type Prefs = { topics: string[]; sources: string[]; days: number; feedFilter: 'all' | 'unread'; language: AppLanguage };
type SavedArticleRecord = { item: FeedItem; savedAt: number; shared?: boolean };

const DEFAULT_TOPICS = ['ביטחון', 'פוליטיקה', 'אקטואליה בעולם', 'כלכלה', 'רכב', 'טכנולוגיה', 'צרכנות', 'תרבות', 'ספורט', 'בריאות', 'מזג אוויר'];
const DEFAULT_PREFS: Prefs = { topics: [], sources: [], days: 3, feedFilter: 'all', language: 'he' };
const LANGUAGE_OPTIONS: Array<{ code: AppLanguage; name: string; dir: 'rtl' | 'ltr' }> = [
  { code: 'he', name: 'עברית', dir: 'rtl' },
  { code: 'en', name: 'English', dir: 'ltr' },
  { code: 'ru', name: 'Русский', dir: 'ltr' },
  { code: 'ar', name: 'العربية', dir: 'rtl' },
];

function normalizeLanguage(value: unknown): AppLanguage {
  return LANGUAGE_OPTIONS.some(option => option.code === value) ? value as AppLanguage : 'he';
}

function languageName(code: AppLanguage) {
  return LANGUAGE_OPTIONS.find(option => option.code === code)?.name || 'עברית';
}


type ArticleText = { headline: string; summary: string; takeaway: string; topic: string };
const TRANSLATION_CACHE_PREFIX = 'poenta.native.translationCache.v2';
const TRANSLATE_STATIC_TEXTS = [
  'הכל','שמור','שמורים','שתף','חיפוש','הגדרות','מבזקים','עוד','חזרה','Poenta','רענן פיד','מדד החדשים שלך','הצג את כל הידיעות','סנן לחדשים',
  'כותרת המקור','פתח את כתבת המקור','שגיאה בטעינת הפיד','אין אייטמים להצגה כרגע.','הקלד לפחות 2 אותיות לחיפוש.','מה לחפש? למשל הופעות רוק',
  'הגדרות Poenta','תחומי עניין, מקורות וסינון אישי — כמו בגרסת ה־web שפיתחנו.','תחומי עניין','נשמר במכשיר','סמן הכל','בטל הכל','תחום אישי, למשל מיצרי הורמוז','הוסף','מקורות','סינון קריאה','יום אחד','ימים','שפת האפליקציה והפיד','בחר שפה','שינוי השפה מתרגם את כל ממשק Poenta ואת טקסטי הכתבות. כותרות המקור ושמות המקורות נשארים כפי שהמקור פרסם.',
  'חיפוש חכם בכתבות מהפיד ומהשמורים. אפשר לכתוב רעיון כמו “הופעות רוק”.','אפשר לשמור כתבות מהפיד בלחיצה על שמור.','כתבות שמורות',
  'מצב תצוגה','כהה, בהיר או לפי מערכת','התאמה אישית של חוויית השימוש.','בחר איך Poenta תיראה אצלך.','כהה','בהיר','לפי מערכת','נשמר','“לפי מערכת” מחליף אוטומטית בין לייט לדרק לפי הגדרת המכשיר.',
  'אודות Poenta','מה Poenta עושה ולמה היא נבנתה.','Poenta / פואנטה היא שירות חדשות אישי בעברית שמרכז, מסכם ומארגן ידיעות ממקורות חיצוניים לפי מקורות, תחומי עניין והעדפות שימוש.','המטרה: להבין מהר מה באמת קרה, למה זה חשוב ומה הפואנטה — בלי כותרות מטעות, רעש מיותר וגלילה אינסופית.','מה מוצג באפליקציה?','• פיד חדשות חכם ומותאם אישית\n• תקצירים, הקשרים וניסוחי פואנטה בעזרת AI ובקרות איכות\n• קישורים למקורות המקוריים\n• שמורים, מבזקים, מקורות ותחומי עניין','גרסה',
  'תנאי שימוש','המסמך המשפטי לשימוש ב־Poenta.','מדיניות פרטיות','איך Poenta מתייחסת למידע ולהעדפות המשתמש.','צור קשר','פניות, הצעות ושאלות על Poenta.','לדיווח על תקלה, בעיית טעינה, תוכן שגוי או שאלה כללית:','מומלץ לצרף צילום מסך, סוג מכשיר, מערכת הפעלה ותיאור קצר של הבעיה.',
  'שיתוף לאפליקציה','שלח קישור ל־Poenta ב־WhatsApp עם טקסט מוכן','משתמש','לא פעיל כרגע','מראה, מצב תצוגה והעדפות נוספות','אודות','מה Poenta עושה, מקורות, פרטיות וגרסה','המסמך הרשמי לשימוש באפליקציה','נוסח מדיניות הפרטיות של Poenta','פרטי קשר ותמיכה',
  'ביטחון','פוליטיקה','אקטואליה בעולם','כלכלה','רכב','טכנולוגיה','צרכנות','תרבות','ספורט','בריאות','פלילים','רכילות','נדל״ן','דעות','משפט','מזג אוויר','חדשות','עולם','תחבורה',
  'תאריך לא זמין','עכשיו','לפני יום','לפני שעה','לפני {n} דקות','לפני {n} שעות','לפני {n} ימים'
  ,'הגדרות ומידע נוסף על Poenta.','עדכון אחרון: 2026-06-01','Poenta היא שירות חדשות אישי שמרכז ידיעות ממקורות חיצוניים, מציג תקצירים, הקשרים, קישורים למקורות מקוריים וכלי סינון לפי מקורות ותחומי עניין.','התוכן מבוסס על מקורות חיצוניים. זכויות היוצרים בתוכן המקורי, בכותרות המקור, בתמונות ובחומרים המקוריים שייכות לבעליהן. Poenta אינה מחליפה את המקור המקורי ואינה טוענת לבעלות על תוכן צד שלישי.','חלק מהתקצירים, הכותרות, ההקשרים או ניסוחי “הפואנטה” עשויים להיווצר או להיערך בעזרת AI. ייתכנו טעויות, אי־דיוקים או השמטות; במקרה של סתירה המקור המקורי הוא נקודת הייחוס.','השירות מיועד למידע חדשותי וכללי בלבד ואינו מהווה ייעוץ משפטי, פיננסי, רפואי, ביטחוני או מקצועי. השימוש הוא באחריות המשתמש.','לפניות בנושא תנאי השימוש: support@poenta.app','בגרסה הראשונה, ללא הרשמה וללא התחברות, Poenta מיועדת לעבוד עם מידע מינימלי.','העדפות מקומיות כמו מקורות, תחומי עניין, פריטים שמורים והגדרות תצוגה עשויות להישמר במכשיר או בדפדפן.','ייתכן שייאסף מידע טכני בסיסי כמו IP, סוג דפדפן/מכשיר, זמני גישה ושגיאות לצורך אבטחה, תפעול ושיפור השירות.','Poenta אינה מוכרת מידע אישי. בגרסה הראשונה אין צורך בהרשאות מיקום, אנשי קשר, מצלמה או מיקרופון.','לפניות פרטיות ותמיכה: support@poenta.app','הסר משמור','שגיאה בטעינת הנתונים','טוען את כל האפליקציה בשפה החדשה…'
];
const BUILTIN_TRANSLATIONS: Record<AppLanguage, Record<string, string>> = {
  he: {},
  en: {
    "הכל":"All",
    "שמור":"Save",
    "שמורים":"Saved",
    "שתף":"Share",
    "חיפוש":"Search",
    "הגדרות":"Settings",
    "מבזקים":"Breaking",
    "עוד":"More",
    "חזרה":"Back",
    "Poenta":"Poenta",
    "רענן פיד":"Refresh feed",
    "מדד החדשים שלך":"Your new-items meter",
    "הצג את כל הידיעות":"Show all stories",
    "סנן לחדשים":"Show new only",
    "כותרת המקור":"Original headline",
    "פתח את כתבת המקור":"Open original article",
    "שגיאה בטעינת הפיד":"Feed loading error",
    "אין אייטמים להצגה כרגע.":"No items to show right now.",
    "הקלד לפחות 2 אותיות לחיפוש.":"Type at least 2 characters to search.",
    "מה לחפש? למשל הופעות רוק":"What to search? e.g. rock concerts",
    "הגדרות Poenta":"Poenta Settings",
    "תחומי עניין, מקורות וסינון אישי — כמו בגרסת ה־web שפיתחנו.":"Topics, sources and personal filtering — like the web version we built.",
    "תחומי עניין":"Topics",
    "נשמר במכשיר":"Saved on device",
    "סמן הכל":"Select all",
    "בטל הכל":"Clear all",
    "תחום אישי, למשל מיצרי הורמוז":"Custom topic, e.g. Strait of Hormuz",
    "הוסף":"Add",
    "מקורות":"Sources",
    "סינון קריאה":"Reading filter",
    "יום אחד":"One day",
    "ימים":"days",
    "שפת האפליקציה והפיד":"App and feed language",
    "בחר שפה":"Choose language",
    "שינוי השפה מתרגם את כל ממשק Poenta ואת טקסטי הכתבות. כותרות המקור ושמות המקורות נשארים כפי שהמקור פרסם.":"Changing the language translates the entire Poenta interface and article texts. Original source headlines and source names remain as published by the source.",
    "חיפוש חכם בכתבות מהפיד ומהשמורים. אפשר לכתוב רעיון כמו “הופעות רוק”.":"Smart search in feed and saved stories. You can type an idea like “rock concerts”.",
    "אפשר לשמור כתבות מהפיד בלחיצה על שמור.":"You can save stories from the feed by tapping Save.",
    "כתבות שמורות":"Saved stories",
    "מצב תצוגה":"Display mode",
    "כהה, בהיר או לפי מערכת":"Dark, light or system",
    "התאמה אישית של חוויית השימוש.":"Customize the app experience.",
    "בחר איך Poenta תיראה אצלך.":"Choose how Poenta looks for you.",
    "כהה":"Dark",
    "בהיר":"Light",
    "לפי מערכת":"System",
    "נשמר":"Saved",
    "“לפי מערכת” מחליף אוטומטית בין לייט לדרק לפי הגדרת המכשיר.":"“System” automatically switches between light and dark according to the device setting.",
    "אודות Poenta":"About Poenta",
    "מה Poenta עושה ולמה היא נבנתה.":"What Poenta does and why it was built.",
    "Poenta / פואנטה היא שירות חדשות אישי בעברית שמרכז, מסכם ומארגן ידיעות ממקורות חיצוניים לפי מקורות, תחומי עניין והעדפות שימוש.":"Poenta is a personal Hebrew news service that collects, summarizes and organizes stories from external sources by sources, interests and usage preferences.",
    "המטרה: להבין מהר מה באמת קרה, למה זה חשוב ומה הפואנטה — בלי כותרות מטעות, רעש מיותר וגלילה אינסופית.":"The goal: quickly understand what really happened, why it matters and what the point is — without misleading headlines, unnecessary noise and endless scrolling.",
    "מה מוצג באפליקציה?":"What is shown in the app?",
    "• פיד חדשות חכם ומותאם אישית\n• תקצירים, הקשרים וניסוחי פואנטה בעזרת AI ובקרות איכות\n• קישורים למקורות המקוריים\n• שמורים, מבזקים, מקורות ותחומי עניין":"• A smart personalized news feed\n• Summaries, context and Pointa takeaways with AI and quality controls\n• Links to original sources\n• Saved items, breaking news, sources and interests",
    "גרסה":"Version",
    "תנאי שימוש":"Terms of Use",
    "המסמך המשפטי לשימוש ב־Poenta.":"The legal document for using Poenta.",
    "מדיניות פרטיות":"Privacy Policy",
    "איך Poenta מתייחסת למידע ולהעדפות המשתמש.":"How Poenta handles user information and preferences.",
    "צור קשר":"Contact",
    "פניות, הצעות ושאלות על Poenta.":"Requests, suggestions and questions about Poenta.",
    "לדיווח על תקלה, בעיית טעינה, תוכן שגוי או שאלה כללית:":"To report a bug, loading issue, incorrect content or general question:",
    "מומלץ לצרף צילום מסך, סוג מכשיר, מערכת הפעלה ותיאור קצר של הבעיה.":"It is recommended to include a screenshot, device type, operating system and a short description of the issue.",
    "שיתוף לאפליקציה":"Share the app",
    "שלח קישור ל־Poenta ב־WhatsApp עם טקסט מוכן":"Send a Poenta link on WhatsApp with ready text",
    "משתמש":"User",
    "לא פעיל כרגע":"Not active now",
    "מראה, מצב תצוגה והעדפות נוספות":"Appearance, display mode and additional preferences",
    "אודות":"About",
    "מה Poenta עושה, מקורות, פרטיות וגרסה":"What Poenta does, sources, privacy and version",
    "המסמך הרשמי לשימוש באפליקציה":"The official app terms document",
    "נוסח מדיניות הפרטיות של Poenta":"Poenta privacy policy text",
    "פרטי קשר ותמיכה":"Contact and support details",
    "ביטחון":"Security",
    "פוליטיקה":"Politics",
    "אקטואליה בעולם":"World",
    "כלכלה":"Economy",
    "רכב":"Vehicles",
    "טכנולוגיה":"Technology",
    "צרכנות":"Consumer",
    "תרבות":"Culture",
    "ספורט":"Sports",
    "בריאות":"Health",
    "פלילים":"Crime",
    "רכילות":"Gossip",
    "נדל״ן":"Real Estate",
    "דעות":"Opinion",
    "משפט":"Legal",
    "מזג אוויר":"Weather",
    "חדשות":"News",
    "עולם":"World",
    "תחבורה":"Transportation",
    "תאריך לא זמין":"Date unavailable",
    "עכשיו":"Now",
    "לפני יום":"1 day ago",
    "לפני שעה":"1 hour ago",
    "לפני {n} דקות":"{n} minutes ago",
    "לפני {n} שעות":"{n} hours ago",
    "לפני {n} ימים":"{n} days ago",
    "הגדרות ומידע נוסף על Poenta.":"Settings and more information about Poenta.",
    "עדכון אחרון: 2026-06-01":"Last updated: 2026-06-01",
    "Poenta היא שירות חדשות אישי שמרכז ידיעות ממקורות חיצוניים, מציג תקצירים, הקשרים, קישורים למקורות מקוריים וכלי סינון לפי מקורות ותחומי עניין.":"Poenta is a personal news service that collects stories from external sources and displays summaries, context, links to original sources and filtering tools by sources and interests.",
    "התוכן מבוסס על מקורות חיצוניים. זכויות היוצרים בתוכן המקורי, בכותרות המקור, בתמונות ובחומרים המקוריים שייכות לבעליהן. Poenta אינה מחליפה את המקור המקורי ואינה טוענת לבעלות על תוכן צד שלישי.":"The content is based on external sources. Copyright in original content, source headlines, images and original materials belongs to their owners. Poenta does not replace the original source and does not claim ownership of third-party content.",
    "חלק מהתקצירים, הכותרות, ההקשרים או ניסוחי “הפואנטה” עשויים להיווצר או להיערך בעזרת AI. ייתכנו טעויות, אי־דיוקים או השמטות; במקרה של סתירה המקור המקורי הוא נקודת הייחוס.":"Some summaries, headlines, context or “Pointa” wording may be created or edited with AI. Errors, inaccuracies or omissions may occur; if there is a conflict, the original source is the reference point.",
    "השירות מיועד למידע חדשותי וכללי בלבד ואינו מהווה ייעוץ משפטי, פיננסי, רפואי, ביטחוני או מקצועי. השימוש הוא באחריות המשתמש.":"The service is intended for general news and information only and is not legal, financial, medical, security or professional advice. Use is at the user’s responsibility.",
    "לפניות בנושא תנאי השימוש: support@poenta.app":"For questions about the Terms of Use: support@poenta.app",
    "בגרסה הראשונה, ללא הרשמה וללא התחברות, Poenta מיועדת לעבוד עם מידע מינימלי.":"In the first version, without registration or login, Poenta is designed to work with minimal information.",
    "העדפות מקומיות כמו מקורות, תחומי עניין, פריטים שמורים והגדרות תצוגה עשויות להישמר במכשיר או בדפדפן.":"Local preferences such as sources, interests, saved items and display settings may be stored on the device or in the browser.",
    "ייתכן שייאסף מידע טכני בסיסי כמו IP, סוג דפדפן/מכשיר, זמני גישה ושגיאות לצורך אבטחה, תפעול ושיפור השירות.":"Basic technical information such as IP, browser/device type, access times and errors may be collected for security, operation and service improvement.",
    "Poenta אינה מוכרת מידע אישי. בגרסה הראשונה אין צורך בהרשאות מיקום, אנשי קשר, מצלמה או מיקרופון.":"Poenta does not sell personal information. In the first version, no location, contacts, camera or microphone permissions are required.",
    "לפניות פרטיות ותמיכה: support@poenta.app":"For privacy and support requests: support@poenta.app",
    "הסר משמור":"Remove from saved",
    "שגיאה בטעינת הנתונים":"Data loading error",
    "טוען את כל האפליקציה בשפה החדשה…":"Loading the entire app in the new language…"
  },
  ru: {}, ar: {},
};

const CORE_TRANSLATIONS: Record<AppLanguage, Record<string, string>> = {
  he: {},
  en: {
    'תחומי עניין, מקורות וסינון אישי — כמו בגרסת ה־web שפיתחנו.':'Topics, sources and personal filtering — like the web version we built.',
    'הגדרות ומידע נוסף על Poenta.':'Settings and more information about Poenta.',
    'שינוי השפה מתרגם את כל ממשק Poenta ואת טקסטי הכתבות. כותרות המקור ושמות המקורות נשארים כפי שהמקור פרסם.':'Changing the language translates the entire Poenta interface and article texts. Original source headlines and source names remain as published by the source.',
    'פלילים':'Crime','רכילות':'Gossip','נדל״ן':'Real Estate','דעות':'Opinion','משפט':'Legal','מזג אוויר':'Weather',
    'שיתוף לאפליקציה':'Share the app','שלח קישור ל־Poenta ב־WhatsApp עם טקסט מוכן':'Send a Poenta link on WhatsApp with ready text','משתמש':'User','לא פעיל כרגע':'Not active now','מראה, מצב תצוגה והעדפות נוספות':'Appearance, display mode and more preferences','מה Poenta עושה, מקורות, פרטיות וגרסה':'What Poenta does, sources, privacy and version','המסמך הרשמי לשימוש באפליקציה':'Official terms for using the app','נוסח מדיניות הפרטיות של Poenta':'Poenta privacy policy text','פרטי קשר ותמיכה':'Contact and support details','התאמה אישית של חוויית השימוש.':'Customize the app experience.','כהה, בהיר או לפי מערכת':'Dark, light or system',
    'שגיאה בטעינת הנתונים':'Data loading error','שגיאה בטעינת הפיד':'Feed loading error','הסר משמור':'Remove saved','גרסה':'Version','מה מוצג באפליקציה?':'What is shown in the app?','המסמך המשפטי לשימוש ב־Poenta.':'Legal terms for using Poenta.','איך Poenta מתייחסת למידע ולהעדפות המשתמש.':'How Poenta handles user data and preferences.','פניות, הצעות ושאלות על Poenta.':'Requests, suggestions and questions about Poenta.'
  },
  ru: {'הכל':'Все','שמור':'Сохранить','שמורים':'Сохранённые','שתף':'Поделиться','חיפוש':'Поиск','הגדרות':'Настройки','מבזקים':'Срочно','עוד':'Ещё','חזרה':'Назад','מדד החדשים שלך':'Индикатор новых','הצג את כל הידיעות':'Показать все','סנן לחדשים':'Только новые','ביטחון':'Безопасность','פוליטיקה':'Политика','אקטואליה בעולם':'Мир','כלכלה':'Экономика','רכב':'Транспорт','טכנולוגיה':'Технологии','צרכנות':'Потребители','תרבות':'Культура','ספורט':'Спорт','בריאות':'Здоровье','פלילים':'Криминал','רכילות':'Сплетни','נדל״ן':'Недвижимость','דעות':'Мнения','משפט':'Право'},
  ar: {'הכל':'الكل','שמור':'حفظ','שמורים':'المحفوظات','שתף':'مشاركة','חיפוש':'بحث','הגדרות':'الإعدادات','מבזקים':'عاجل','עוד':'المزيد','חזרה':'رجوع','מדד החדשים שלך':'مؤشر الأخبار الجديدة','הצג את כל הידיעות':'عرض الكل','סנן לחדשים':'الجديد فقط','ביטחון':'أمن','פוליטיקה':'سياسة','אקטואליה בעולם':'العالم','כלכלה':'اقتصاد','רכב':'مركبات','טכנולוגיה':'تكنولوجيا','צרכנות':'استهلاك','תרבות':'ثقافة','ספורט':'رياضة','בריאות':'صحة','פלילים':'جرائم','רכילות':'مشاهير','נדל״ן':'عقارات','דעות':'آراء','משפט':'قانون'},
};

function translationTarget(code: AppLanguage) { return code; }
function translationKey(lang: AppLanguage, text: string) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
  return `${lang}:${(h >>> 0).toString(36)}:${text.length}`;
}
async function translateRemote(text: string, lang: AppLanguage): Promise<string> {
  if (lang === 'he' || !text.trim()) return text;
  const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=he&tl=${encodeURIComponent(translationTarget(lang))}&dt=t&q=${encodeURIComponent(text)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`translate ${res.status}`);
  const data = await res.json();
  const translated = Array.isArray(data?.[0]) ? data[0].map((part: unknown[]) => String(part?.[0] || '')).join('') : '';
  return translated.trim() || text;
}

function sameList(a: string[], b: string[]) {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

function samePrefs(a: Prefs, b: Prefs) {
  return a.days === b.days && a.feedFilter === b.feedFilter && a.language === b.language && sameList(a.topics, b.topics) && sameList(a.sources, b.sources);
}
const APP_SHARE_TEXT = 'מצאתי אפליקציית חדשות מעולה — Poenta.\nחדשות בעברית עם תקציר ברור, הקשר והפואנטה.\nhttps://poenta.app/';
const APP_SHARE_URL = 'https://poenta.app/';
const SHARE_ARTICLES_URL = 'https://poenta.app/share/articles.json';
const POENTA_LOGO = require('./assets/poenta-logo.png');
const POENTA_LOGO_LIGHT = require('./assets/poenta-logo-light.png');
const POENTA_NAV_ICON = require('./assets/poenta-icon-64.png');

type AppColors = {
  bg: string; bottom: string; topbar: string; card: string; cardSoft: string; text: string; muted: string; secondary: string; faint: string;
  border: string; subtleBorder: string; surface: string; surfaceSoft: string; yellow: string; yellowSoft: string; yellowBg: string;
  sourceBg: string; iconMuted: string; textOnYellow: string; inputBg: string; heroBg: string; overlay: string; shadow: string; red: string; green: string;
};

const DARK_COLORS: AppColors = {
  bg: '#071015', bottom: '#050b0f', topbar: '#071015', card: 'rgba(255,255,255,0.022)', cardSoft: '#0b151a', text: '#F4F6F7',
  muted: 'rgba(255,255,255,0.52)', secondary: 'rgba(255,255,255,0.72)', faint: 'rgba(255,255,255,0.075)', border: 'rgba(255,255,255,0.07)',
  subtleBorder: 'rgba(255,255,255,0.05)', surface: 'rgba(255,255,255,0.03)', surfaceSoft: 'rgba(255,255,255,0.035)',
  yellow: '#FFC400', yellowSoft: '#E9B400', yellowBg: 'rgba(255,196,0,0.13)', sourceBg: 'rgba(255,196,0,0.07)',
  iconMuted: 'rgba(255,255,255,0.48)', textOnYellow: '#071015', inputBg: '#0b151a', heroBg: '#111a20', overlay: 'rgba(0,0,0,0.42)',
  shadow: '#000', red: '#ff6b6b', green: '#52d273',
};

const LIGHT_COLORS: AppColors = {
  bg: '#F7F0DF', bottom: '#FFF7E4', topbar: '#FFF6E1', card: '#FFFFFF', cardSoft: '#FFF9EF', text: '#172027',
  muted: 'rgba(23,32,39,0.68)', secondary: 'rgba(23,32,39,0.82)', faint: 'rgba(23,32,39,0.16)', border: 'rgba(23,32,39,0.18)',
  subtleBorder: 'rgba(23,32,39,0.14)', surface: 'rgba(255,255,255,0.86)', surfaceSoft: '#FFFDF8',
  yellow: '#FFC400', yellowSoft: '#8A5F00', yellowBg: 'rgba(255,196,0,0.22)', sourceBg: 'rgba(255,196,0,0.17)',
  iconMuted: 'rgba(23,32,39,0.72)', textOnYellow: '#101820', inputBg: '#FFFDF8', heroBg: '#E9DFCC', overlay: 'rgba(0,0,0,0.46)',
  shadow: 'rgba(87,64,12,0.36)', red: '#C33B3B', green: '#23834C',
};

let appColors = DARK_COLORS;

const STORAGE_KEYS = {
  prefs: 'poenta.native.prefs.v1',
  saved: 'poenta.native.saved.v1',
  savedItems: 'poenta.native.savedItems.v1',
  read: 'poenta.native.read.v1',
  appearance: 'poenta.native.appearance.v1',
  feedCache: 'poenta.native.feedCache.v1',
  breakingCache: 'poenta.native.breakingCache.v1',
  lastSync: 'poenta.native.lastSync.v1',
};

function canonicalSource(name?: string) {
  const s = String(name || '').trim();
  const low = s.toLowerCase();
  if (s.includes('דובר צה') || s.includes('צה״ל') || s.includes('צה"ל')) return 'דובר צה״ל';
  if (s.includes('משטרת ישראל') || s.includes('דוברות משטרת') || low.includes('israel police')) return 'דוברות משטרת ישראל';
  if (low.includes('cnn')) return 'CNN';
  if (low.includes('bbc')) return 'BBC';
  if (low.includes('sky news') || low.includes('sky')) return 'Sky News';
  if (low.includes('reuters')) return 'Reuters';
  if (low === 'ap' || low.includes('associated press')) return 'AP';
  if (low.includes('guardian')) return 'Guardian';
  if (low.includes('new york times') || low.includes('nyt')) return 'NYT';
  if (low.includes('bloomberg')) return 'Bloomberg';
  if (low.includes('al jazeera')) return 'Al Jazeera';
  if (s.includes('וואלה') || low.includes('walla')) return 'וואלה';
  if (low.includes('ynet')) return 'ynet';
  if (s.includes('גלובס')) return 'גלובס';
  if (s.includes('הארץ') || low.includes('haaretz')) return 'הארץ';
  if (s.includes('ישראל היום')) return 'ישראל היום';
  if (s.includes('מעריב') || low.includes('maariv')) return 'מעריב';
  if (s.includes('דה מרקר') || low.includes('themarker')) return 'דה מרקר';
  if (s.includes('N12') || low.includes('mako')) return 'N12';
  return s.split(' - ')[0].trim() || 'מקור';
}

function sourceName(item: FeedItem) {
  return canonicalSource(item.sourceName || item.sourceLogo || item.source || 'מקור');
}

function forcedFaviconDomain(name?: string) {
  const target = canonicalSource(name);
  const domains: Record<string, string> = {
    'Poenta': 'poenta.app', 'CNN': 'cnn.com', 'N12': 'n12.co.il', 'BBC': 'bbc.com', 'Sky News': 'news.sky.com',
    'Reuters': 'reuters.com', 'AP': 'apnews.com', 'Guardian': 'theguardian.com', 'NYT': 'nytimes.com',
    'Axios': 'axios.com', 'Politico': 'politico.com', 'Bloomberg': 'bloomberg.com', 'Al Jazeera': 'aljazeera.com',
    'ynet': 'ynet.co.il', 'וואלה': 'walla.co.il', 'גלובס': 'globes.co.il', 'הארץ': 'haaretz.co.il',
    'ישראל היום': 'israelhayom.co.il', 'מעריב': 'maariv.co.il', 'דה מרקר': 'themarker.com',
    'דובר צה״ל': 't.me', 'דוברות משטרת ישראל': 'police.gov.il', 'השירות המטאורולוגי': 'ims.gov.il',
  };
  return domains[target] || '';
}

function sourceUrlForName(name?: string) {
  const target = canonicalSource(name);
  const fallbacks: Record<string, string> = {
    'ynet': 'https://www.ynet.co.il', 'וואלה': 'https://news.walla.co.il', 'גלובס': 'https://www.globes.co.il',
    'הארץ': 'https://www.haaretz.co.il', 'ישראל היום': 'https://www.israelhayom.co.il', 'מעריב': 'https://www.maariv.co.il',
    'דה מרקר': 'https://www.themarker.com', 'N12': 'https://www.n12.co.il', 'BBC': 'https://www.bbc.com/news/world',
    'Sky News': 'https://news.sky.com/world', 'CNN': 'https://www.cnn.com/world', 'Reuters': 'https://www.reuters.com/world/middle-east/',
    'AP': 'https://apnews.com/hub/middle-east', 'Guardian': 'https://www.theguardian.com/world/middleeast',
    'NYT': 'https://www.nytimes.com/section/world/middleeast', 'Bloomberg': 'https://www.bloomberg.com',
    'Al Jazeera': 'https://www.aljazeera.com/middle-east/', 'דובר צה״ל': 'https://t.me/idf_telegram',
    'דוברות משטרת ישראל': 'https://t.me/Israel_Police_100',
  };
  return fallbacks[target] || '';
}

function faviconForSource(name?: string, item?: FeedItem) {
  const forced = forcedFaviconDomain(name);
  if (forced) return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(forced)}&sz=64`;
  const url = item?.sourceUrl || sourceUrlForName(name);
  try { return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(new URL(url).hostname)}&sz=64`; } catch { return ''; }
}

const SourceIcon = memo(function SourceIcon({ name, item, small = false, themeKey: _themeKey }: { name: string; item?: FeedItem; small?: boolean; themeKey?: string }) {
  const icon = faviconForSource(name, item);
  if (small && icon) return <Image source={{ uri: icon }} style={styles.sourceMiniImage as any} fadeDuration={0} />;
  if (small) return <View style={styles.sourceMiniFallback}><Text style={styles.sourceMiniFallbackText}>{name.slice(0, 1) || 'P'}</Text></View>;
  if (icon) return <Image source={{ uri: icon }} style={styles.sourceIconImage as any} fadeDuration={0} />;
  return <View style={styles.sourceIconFallback}><Text style={styles.sourceIconFallbackText}>{name.slice(0, 1) || 'P'}</Text></View>;
});

type IconName = 'bookmark' | 'share' | 'breaking' | 'settings' | 'search';
function WebIcon({ name, active = false, filled = false, size = 28 }: { name: IconName; active?: boolean; filled?: boolean; size?: number }) {
  const color = active ? appColors.yellow : appColors.iconMuted;
  const fill = filled || (active && (name === 'breaking' || name === 'search')) ? color : 'none';
  if (name === 'bookmark') return <Svg width={size} height={size} viewBox="0 0 24 24"><Path d="M6 4h12v17l-6-4-6 4V4Z" stroke={color} fill={fill} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" /></Svg>;
  if (name === 'share') return <Svg width={size} height={size} viewBox="0 0 24 24"><Path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7" stroke={color} fill="none" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" /><Path d="M12 16V4" stroke={color} fill="none" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" /><Path d="M7 9l5-5 5 5" stroke={color} fill="none" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" /></Svg>;
  if (name === 'breaking') return <Svg width={size} height={size} viewBox="0 0 24 24"><Path d="M13 2 5 13h6l-1 9 9-13h-6l1-7Z" stroke={color} fill={fill} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" /></Svg>;
  if (name === 'settings') return <Svg width={size} height={size} viewBox="0 0 24 24"><Path d="M6 4v16" stroke={color} strokeWidth={2} strokeLinecap="round" /><Path d="M12 4v16" stroke={color} strokeWidth={2} strokeLinecap="round" /><Path d="M18 4v16" stroke={color} strokeWidth={2} strokeLinecap="round" /><Circle cx="6" cy="9" r="2.15" stroke={color} fill={appColors.bottom} strokeWidth={2} /><Circle cx="12" cy="15" r="2.15" stroke={color} fill={appColors.bottom} strokeWidth={2} /><Circle cx="18" cy="7.5" r="2.15" stroke={color} fill={appColors.bottom} strokeWidth={2} /></Svg>;
  return <Svg width={size} height={size} viewBox="0 0 24 24"><Circle cx="11" cy="11" r="7" stroke={color} fill={fill} strokeWidth={2} /><Path d="M20 20l-4.4-4.4" stroke={color} fill="none" strokeWidth={2} strokeLinecap="round" /></Svg>;
}

function topicFor(item: FeedItem) {
  const c = String(item.topic || item.category || 'חדשות');
  if (c === 'תחבורה') return 'רכב';
  if (c === 'חדשות') return 'פוליטיקה';
  if (c === 'עולם') return 'אקטואליה בעולם';
  return c;
}

function displayHeadline(item: FeedItem) {
  const h = String(item.headline || '').trim();
  const o = String(item.originalTitle || '').trim().replace(/[?؟]+$/, '');
  if (/הפואנטה היא|הכותרת הכלכלית|הסיפור הנדלני|הפרסום הצרכני|החידוש הטכנולוגי|האירוע הביטחוני|מאחורי הכותרת/.test(h) && o) return o;
  return h || o || 'עדכון חדש בפואנטה';
}

function summaryFor(item: FeedItem) {
  const raw = String(item.context || item.summary || item.description || '').trim().replace(/…|\.\.\./g, '');
  if (!raw) return '';
  const title = displayHeadline(item).toLowerCase();
  const text = raw.toLowerCase();
  if (text === title || text.startsWith(title)) return '';
  return raw.length > 330 ? `${raw.slice(0, 320).trim()}…` : raw;
}

function itemKey(item: FeedItem) {
  return String(item.sourceUrl || `${item.originalTitle || item.headline}|${sourceName(item)}`).replace(/[?#].*$/, '').replace(/\/$/, '').toLowerCase();
}

function cleanShareIdentityUrl(raw?: string) {
  try {
    const url = new URL(String(raw || ''));
    url.hash = '';
    ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'fbclid', 'gclid'].forEach(param => url.searchParams.delete(param));
    return url.toString().replace(/\/$/, '');
  } catch {
    return '';
  }
}

function shareIdentity(item: FeedItem) {
  const url = cleanShareIdentityUrl(item.sourceUrl || item.shareUrl || '');
  if (url) return url;
  return normalizeText(`${sourceName(item)}|${item.sourceLogo || ''}|${item.originalTitle || ''}|${displayHeadline(item)}`).toLowerCase();
}

function utf8Bytes(text: string) {
  const encoderCtor = (globalThis as unknown as { TextEncoder?: new () => { encode: (value: string) => Uint8Array } }).TextEncoder;
  if (encoderCtor) return new encoderCtor().encode(text);
  return new Uint8Array(Array.from(unescape(encodeURIComponent(text))).map(ch => ch.charCodeAt(0)));
}

function shareIdForItem(item: FeedItem) {
  if (item.shareId) return item.shareId;
  if (item.shareUrl) {
    const match = String(item.shareUrl).match(/\/share\/([^/?#]+)\/?/);
    if (match?.[1]) return decodeURIComponent(match[1]);
  }
  let hash = 0xcbf29ce484222325n;
  utf8Bytes(shareIdentity(item)).forEach(byte => {
    hash ^= BigInt(byte);
    hash = (hash * 0x100000001b3n) & 0xffffffffffffffffn;
  });
  return `a-${hash.toString(16).padStart(16, '0')}`;
}

function articleShareUrl(item: FeedItem) {
  return `${APP_SHARE_URL}share/${encodeURIComponent(shareIdForItem(item))}/`;
}

function articleShareText(item: FeedItem, headline = displayHeadline(item), summary = summaryFor(item)) {
  return `${headline}\n\n${summary}\n\nפתחו בפואנטה: ${articleShareUrl(item)}`;
}

function sharedArticleIdFromUrl(raw?: string | null) {
  if (!raw) return '';
  try {
    const url = new URL(raw);
    const fromQuery = url.searchParams.get('share');
    if (fromQuery) return fromQuery;
    const match = url.pathname.match(/\/share\/([^/?#]+)\/?/);
    return match?.[1] ? decodeURIComponent(match[1]) : '';
  } catch {
    const match = String(raw).match(/[?&]share=([^&#]+)|\/share\/([^/?#]+)\/?/);
    return match ? decodeURIComponent(match[1] || match[2] || '') : '';
  }
}

function itemDate(item: FeedItem, index = 0) {
  const raw = item.publishedAt || item.pubDate || item.isoDate || item.date || item.updatedAt || '';
  const d = raw ? new Date(raw) : null;
  if (d && !Number.isNaN(d.getTime())) return d.getTime() > Date.now() + 5 * 60 * 1000 ? new Date() : d;
  return new Date(Date.now() - index * 45 * 60 * 1000);
}

function timeLabel(item: FeedItem, index = 0) {
  if (item.hasSourceDate === false) return 'תאריך לא זמין';
  const d = itemDate(item, index);
  const minutes = Math.max(0, Math.floor((Date.now() - d.getTime()) / 60000));
  if (minutes < 1) return 'עכשיו';
  if (minutes < 60) return `לפני ${minutes} דקות`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? 'לפני שעה' : `לפני ${hours} שעות`;
  const days = Math.floor(hours / 24);
  return days === 1 ? 'לפני יום' : `לפני ${days} ימים`;
}

function withinDays(item: FeedItem, index: number, days: number) {
  return Date.now() - itemDate(item, index).getTime() <= days * 24 * 60 * 60 * 1000;
}

function normalizeText(text: string) {
  return text.toLowerCase().replace(/[\"'׳״`]+/g, '').replace(/[^0-9a-zA-Z\u0590-\u05ff]+/g, ' ').trim();
}

function nearDuplicate(a: FeedItem, b: FeedItem) {
  const ta = new Set(normalizeText([a.headline, a.context, a.originalTitle].join(' ')).split(/\s+/).filter(w => w.length > 2));
  const tb = new Set(normalizeText([b.headline, b.context, b.originalTitle].join(' ')).split(/\s+/).filter(w => w.length > 2));
  if (!ta.size || !tb.size) return false;
  const shared = [...ta].filter(t => tb.has(t));
  return shared.length / Math.max(1, Math.min(ta.size, tb.size)) >= 0.58;
}

function dedupeItems(items: FeedItem[]) {
  const out: FeedItem[] = [];
  const seenIdentity = new Set<string>();
  const seenCluster = new Set<string>();
  items.forEach(item => {
    const identity = itemKey(item);
    const explicit = String(item.semanticClusterKey || item.storyClusterKey || item.clusterKey || item.dedupeKey || '').trim();
    if (seenIdentity.has(identity)) return;
    if (explicit && seenCluster.has(explicit)) return;
    seenIdentity.add(identity);
    if (explicit) seenCluster.add(explicit);
    out.push(item);
  });
  return out;
}

function allTopics(items: FeedItem[]) {
  return [...new Set([...DEFAULT_TOPICS, ...items.map(topicFor)])].filter(Boolean);
}

function allSources(items: FeedItem[]) {
  const defaults = [
    // Keep every approved active source selectable even when it has no currently
    // visible feed card after freshness, personalization, quality, or dedupe filters.
    'וואלה', 'ynet', 'גלובס', 'הארץ', 'ישראל היום', 'מעריב', 'דה מרקר', 'N12', 'כיפה',
    'סרוגים', 'כאן דרך Google News', 'ערוץ 14 דרך Google News', 'ערוץ 7 / INN עברית',
    'בשבע', 'מקור ראשון דרך Google News', 'ICE', 'זווית', 'מדע גדול בקטנה',
    'The Jerusalem Post', 'Israel National News English', 'JNS', 'The Media Line',
    'BBC', 'Sky News', 'CNN', 'Reuters', 'AP Middle East דרך Google News', 'Guardian',
    'Al Jazeera', 'NYT', 'Axios Israel/Iran דרך Google News', 'Politico Israel/Iran דרך Google News',
    'Bloomberg', 'Fox News World', 'Fox News Politics', 'France24 Middle East',
    'TMI', 'Pplus / פנאי פלוס דרך Google News', 'Page Six רכילות חו״ל',
    'Daily Mail TVShowbiz רכילות חו״ל', 'Mirror Celebs רכילות חו״ל',
    'דובר צה״ל', 'דוברות משטרת ישראל',
  ];
  return [...new Set([...items.map(sourceName), ...defaults])].filter(Boolean).sort((a, b) => a.localeCompare(b, 'he'));
}

type SourceGroupKey = 'israel' | 'world' | 'telegram';
function sourceGroupForName(name: string): SourceGroupKey {
  const source = canonicalSource(name);
  const low = source.toLowerCase();
  if (source.includes('דובר צה') || source.includes('משטרת ישראל') || low.includes('telegram') || low.includes('t.me')) return 'telegram';
  if (
    /וואלה|ynet|גלובס|הארץ|ישראל היום|מעריב|דה מרקר|כיפה|סרוגים|כאן|ערוץ 14|ערוץ 7|רוטר|mako|בשבע|מקור ראשון|ICE|זווית|מדע גדול/i.test(source) ||
    ['N12', 'The Jerusalem Post', 'Israel National News English', 'JNS'].includes(source)
  ) return 'israel';
  return 'world';
}

function sourceGroupLabel(group: SourceGroupKey) {
  if (group === 'israel') return 'מקורות ישראל';
  if (group === 'world') return 'מקורות חו״ל';
  return 'טלגרם';
}

function collectLanguageCandidates(feedItems: FeedItem[], breakingItems: FeedItem[], topics: string[]) {
  const candidates = new Set<string>();
  TRANSLATE_STATIC_TEXTS.forEach(text => candidates.add(text));
  DEFAULT_TOPICS.forEach(text => candidates.add(text));
  topics.forEach(text => { const clean = String(text || '').trim(); if (clean) candidates.add(clean); });
  [...feedItems, ...breakingItems].forEach(item => {
    [displayHeadline(item), summaryFor(item), String(item.takeaway || '').replace(/^💡\s*/, ''), topicFor(item)].forEach(text => {
      const clean = String(text || '').trim();
      if (clean) candidates.add(clean);
    });
  });
  return [...candidates];
}

async function translateAllMissing(lang: AppLanguage, texts: string[], existing: Record<string, string>, onBatch?: (additions: Record<string, string>) => void) {
  if (lang === 'he') return existing;
  const next: Record<string, string> = { ...existing };
  const missing = texts.filter(text => !BUILTIN_TRANSLATIONS[lang]?.[text] && !CORE_TRANSLATIONS[lang]?.[text] && !next[translationKey(lang, text)]);
  const concurrency = 10;
  let cursor = 0;
  let batch: Record<string, string> = {};
  async function worker() {
    while (cursor < missing.length) {
      const text = missing[cursor++];
      try {
        const key = translationKey(lang, text);
        const translated = await translateRemote(text, lang);
        next[key] = translated;
        batch[key] = translated;
        if (Object.keys(batch).length >= 20) {
          const flushed = batch;
          batch = {};
          onBatch?.(flushed);
        }
      } catch {
        // Keep original Hebrew fallback and retry next time.
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, Math.max(1, missing.length)) }, () => worker()));
  if (Object.keys(batch).length) onBatch?.(batch);
  return next;
}

function delay(ms: number) {
  return new Promise<void>(resolve => setTimeout(resolve, ms));
}

async function warmLanguageCache(lang: AppLanguage, texts: string[], existing: Record<string, string>, shouldStop: () => boolean, onBatch?: (cache: Record<string, string>) => void) {
  if (lang === 'he') return existing;
  const next: Record<string, string> = { ...existing };
  const missing = texts.filter(text => !BUILTIN_TRANSLATIONS[lang]?.[text] && !CORE_TRANSLATIONS[lang]?.[text] && !next[translationKey(lang, text)]);
  const batchSize = 18;
  for (let i = 0; i < missing.length && !shouldStop(); i += batchSize) {
    const slice = missing.slice(i, i + batchSize);
    const results = await Promise.all(slice.map(async text => {
      try { return [translationKey(lang, text), await translateRemote(text, lang)] as const; }
      catch { return null; }
    }));
    results.forEach(result => {
      if (result && result[1]) next[result[0]] = result[1];
    });
    onBatch?.(next);
    // Yield between small batches so Settings/source/topic taps stay responsive.
    await delay(320);
  }
  return next;
}


const SETTINGS_DAYS = [1, 2, 3, 4, 5, 6, 7] as const;

const Chip = memo(function Chip({ label, active, onPress, count, themeKey: _themeKey }: { label: string; active: boolean; onPress: () => void; count?: number; themeKey?: string }) {
  return <TouchableOpacity style={[styles.chip, active && styles.chipActive]} onPress={onPress} activeOpacity={0.82}>
    <Text style={[styles.chipText, active && styles.chipTextActive]} numberOfLines={1}>{label}</Text>
    {typeof count === 'number' && <Text style={[styles.chipCount, active && styles.chipCountActive]}>{count}</Text>}
  </TouchableOpacity>;
});

const SettingsTopicChip = memo(function SettingsTopicChip({ topic, label, active, onToggle, themeKey }: { topic: string; label: string; active: boolean; onToggle: (topic: string) => void; themeKey: string }) {
  const handlePress = useCallback(() => onToggle(topic), [onToggle, topic]);
  return <Chip label={label} active={active} onPress={handlePress} themeKey={themeKey} />;
});

const SettingsSourceRow = memo(function SettingsSourceRow({ source, active, onToggle, themeKey }: { source: string; active: boolean; onToggle: (source: string) => void; themeKey: string }) {
  const handlePress = useCallback(() => onToggle(source), [onToggle, source]);
  return <TouchableOpacity style={[styles.sourceRow, active && styles.sourceRowOn]} onPress={handlePress} activeOpacity={0.82}>
    <View style={styles.sourceRowLabel}><SourceIcon name={source} small themeKey={themeKey} /><Text style={[styles.sourceRowName, active && styles.sourceRowNameOn]}>{source}</Text></View>
    <View style={[styles.switchTrack, active && styles.switchTrackOn]}><View style={[styles.switchKnob, active && styles.switchKnobOn]} /></View>
  </TouchableOpacity>;
});

function SourceThumb({ item }: { item: FeedItem }) {
  if (item.imageUrl) return <Image source={{ uri: item.imageUrl }} style={styles.image as any} resizeMode="cover" fadeDuration={0} />;
  const label = sourceName(item).slice(0, 2) || 'P';
  return <View style={styles.placeholder}><Text style={styles.placeholderText}>{label}</Text></View>;
}

const ArticleCard = memo(function ArticleCard({ item, index, saved, onSave, onOpen, headline, summary, takeaway, topic, time, tr, themeKey }: { item: FeedItem; index: number; saved: boolean; onSave: () => void; onOpen: () => void; headline: string; summary: string; takeaway: string; topic: string; time: string; tr: (text: string) => string; themeKey: string }) {
  const shareText = articleShareText(item, headline, summary);
  const openSource = () => { onOpen(); if (item.sourceUrl) Linking.openURL(item.sourceUrl).catch(() => null); };
  const share = () => Linking.openURL(`https://wa.me/?text=${encodeURIComponent(shareText)}`).catch(() => null);
  return <View style={[styles.card, index < 3 && styles.unreadCard]}>
    <View style={styles.metaRow}>
      <View style={styles.metaActions}>
        <TouchableOpacity onPress={onSave} style={styles.iconAction} accessibilityLabel={saved ? tr('הסר משמור') : tr('שמור')}><WebIcon name="bookmark" active={saved} size={15} /></TouchableOpacity>
        <TouchableOpacity onPress={share} style={styles.iconAction} accessibilityLabel={tr('שתף')}><WebIcon name="share" active={false} size={15} /></TouchableOpacity>
        <Text style={styles.star}>✧</Text>
        <Text style={styles.catText}>{topic}</Text>
      </View>
      <Text style={styles.time}>{time}</Text>
    </View>
    <View style={styles.heroBox}>
      <SourceThumb item={item} />
      <View style={styles.heroShade} />
      <View style={styles.headlineWrap}><Text style={styles.headlineText}>{headline}</Text></View>
    </View>
    {!!summary && <Text style={styles.summary}>{summary}</Text>}
    {!!takeaway && <View style={styles.takeawayBox}><Text style={styles.takeaway}>■ {takeaway}</Text></View>}
    <TouchableOpacity onPress={openSource} activeOpacity={item.sourceUrl ? 0.78 : 1} accessibilityLabel={tr('פתח את כתבת המקור')}>
      <View style={styles.sourceBox}>
        <View style={styles.sourceAccent} />
        <View style={styles.sourceHead}>
          <Text style={styles.sourceLabel}>{tr('כותרת המקור')}</Text>
          <View style={styles.sourceBrand}><SourceIcon name={sourceName(item)} item={item} themeKey={themeKey} /><Text style={styles.sourceNameText} numberOfLines={1}>{sourceName(item)}</Text></View>
        </View>
        <Text style={styles.sourceText}>{String(item.originalTitle || sourceName(item))}</Text>
      </View>
    </TouchableOpacity>
  </View>;
});

function BreakingSourceLinks({ item }: { item: FeedItem }) {
  const links = Array.isArray(item.sourceLinks) && item.sourceLinks.length
    ? item.sourceLinks.map(link => ({ name: canonicalSource(link?.name || sourceName(item)), url: String(link?.url || '') }))
    : [{ name: sourceName(item), url: item.sourceUrl || '' }];
  const unique = links.filter((link, idx, arr) => link.name && arr.findIndex(other => other.name === link.name) === idx).slice(0, 3);
  return <View style={styles.breakingSourceList}>
    <Text style={styles.breakingDot}>•</Text>
    {unique.map((link, idx) => <View key={`${link.name}-${idx}`} style={styles.breakingSourceItem}>
      {idx > 0 && <Text style={styles.breakingSourceSep}>+</Text>}
      <TouchableOpacity disabled={!link.url} onPress={() => link.url && Linking.openURL(link.url).catch(() => null)} activeOpacity={link.url ? 0.78 : 1}>
        <Text style={styles.breakingSourceLink}>{link.name}</Text>
      </TouchableOpacity>
    </View>)}
  </View>;
}

const BreakingCard = memo(function BreakingCard({ item, headline, time, themeKey: _themeKey }: { item: FeedItem; index: number; headline: string; time: string; themeKey: string }) {
  return <View style={[styles.card, styles.breakingCard]}>
    <View style={styles.breakingMetaRow}>
      <BreakingSourceLinks item={item} />
      <Text style={styles.time}>{time}</Text>
    </View>
    <Text style={styles.breakingHeadline}>{headline}</Text>
  </View>;
});

const NavButton = memo(function NavButton({ label, icon, active, onPress, logo, filled = false, themeKey: _themeKey }: { label: string; icon?: IconName; active: boolean; onPress: () => void; logo?: boolean; filled?: boolean; themeKey: string }) {
  return <TouchableOpacity style={styles.navButton} onPress={onPress} accessibilityLabel={label}>
    {logo ? <View style={[styles.navLogoBadge, active && styles.navLogoBadgeActive]}><Image source={POENTA_NAV_ICON} style={styles.navLogo as any} /></View> : icon ? <WebIcon name={icon} active={active} filled={filled} size={28} /> : null}
  </TouchableOpacity>;
});

function PoentaApp() {
  const colorScheme = useColorScheme();
  const insets = useSafeAreaInsets();
  const topInset = Math.max(insets.top, 18);
  const bottomInset = Math.max(insets.bottom, 10);
  const [items, setItems] = useState<FeedItem[]>([]);
  const [breaking, setBreaking] = useState<FeedItem[]>([]);
  const [view, setView] = useState<ViewMode>('home');
  const showFreshnessMeter = view !== 'breaking';
  const topbarHeight = (showFreshnessMeter ? 150 : 108) + topInset;
  const navHeight = 58 + bottomInset;
  const [moreScreen, setMoreScreen] = useState<MoreScreen>('menu');
  const [appearance, setAppearance] = useState<'dark' | 'light' | 'system'>('system');
  const [activeFilter, setActiveFilter] = useState('all');
  const [savedKeys, setSavedKeys] = useState<string[]>([]);
  const [savedArticleRecords, setSavedArticleRecords] = useState<Record<string, SavedArticleRecord>>({});
  const [readKeys, setReadKeys] = useState<string[]>([]);
  const [unreadSessionKeys, setUnreadSessionKeys] = useState<string[]>([]);
  const [search, setSearch] = useState('');
  const [customTopic, setCustomTopic] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS);
  const [settingsPrefs, setSettingsPrefs] = useState<Prefs>(DEFAULT_PREFS);
  const [translationCache, setTranslationCache] = useState<Record<string, string>>({});
  const [languageLoading, setLanguageLoading] = useState<AppLanguage | null>(null);
  const storageReady = useRef(false);
  const prefsLoadedFromStorageRef = useRef(false);
  const warmupRunRef = useRef(0);
  const viewRef = useRef<ViewMode>('home');
  const feedFilterRef = useRef<Prefs['feedFilter']>('all');
  const readKeysRef = useRef<string[]>([]);
  const unreadSessionKeysRef = useRef<string[]>([]);
  const readFlushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const settingsCommitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isLight = appearance === 'light' || (appearance === 'system' && colorScheme === 'light');
  const colors = isLight ? LIGHT_COLORS : DARK_COLORS;
  const themeKey = isLight ? 'light' : 'dark';
  appColors = colors;
  styles = useMemo(() => createStyles(colors), [colors]);

  const knownTopics = useMemo(() => allTopics(items), [items]);
  const knownSources = useMemo(() => allSources([...items, ...breaking]), [items, breaking]);
  const savedKeySet = useMemo(() => new Set(savedKeys), [savedKeys]);
  const readKeySet = useMemo(() => new Set(readKeys), [readKeys]);
  const unreadSessionKeySet = useMemo(() => new Set(unreadSessionKeys), [unreadSessionKeys]);
  const prefTopicSet = useMemo(() => new Set(prefs.topics), [prefs.topics]);
  const prefSourceSet = useMemo(() => new Set(prefs.sources.length ? prefs.sources : knownSources), [prefs.sources, knownSources]);
  const settingsPrefTopicSet = useMemo(() => new Set(settingsPrefs.topics), [settingsPrefs.topics]);
  const settingsPrefSourceSet = useMemo(() => new Set(settingsPrefs.sources.length ? settingsPrefs.sources : knownSources), [settingsPrefs.sources, knownSources]);
  const groupedSources = useMemo(() => {
    const groups: Record<SourceGroupKey, string[]> = { israel: [], world: [], telegram: [] };
    knownSources.forEach(source => groups[sourceGroupForName(source)].push(source));
    return ([
      { key: 'israel' as const, label: sourceGroupLabel('israel'), sources: groups.israel },
      { key: 'world' as const, label: sourceGroupLabel('world'), sources: groups.world },
      { key: 'telegram' as const, label: sourceGroupLabel('telegram'), sources: groups.telegram },
    ]).filter(group => group.sources.length);
  }, [knownSources]);
  const savedItems = useMemo(() => {
    const records: Record<string, SavedArticleRecord> = { ...savedArticleRecords };
    items.forEach(item => {
      const key = itemKey(item);
      if (savedKeySet.has(key) && !records[key]) records[key] = { item, savedAt: 0 };
    });
    return savedKeys
      .map(key => records[key])
      .filter((record): record is SavedArticleRecord => !!record?.item)
      .sort((a, b) => Number(b.savedAt || 0) - Number(a.savedAt || 0))
      .map(record => record.item);
  }, [items, savedKeySet, savedKeys, savedArticleRecords]);


  const tr = useCallback((text: string, params?: Record<string, string | number>) => {
    if (prefs.language === 'he') {
      return params ? text.replace(/\{(\w+)\}/g, (_, key) => String(params[key] ?? '')) : text;
    }
    const raw = BUILTIN_TRANSLATIONS[prefs.language]?.[text] || CORE_TRANSLATIONS[prefs.language]?.[text] || translationCache[translationKey(prefs.language, text)] || text;
    return params ? raw.replace(/\{(\w+)\}/g, (_, key) => String(params[key] ?? '')) : raw;
  }, [prefs.language, translationCache]);

  const topicLabel = useCallback((topic: string) => tr(topic), [tr]);
  const translatedText = useCallback((text: string) => {
    if (prefs.language === 'he' || !text.trim()) return text;
    return translationCache[translationKey(prefs.language, text)] || text;
  }, [prefs.language, translationCache]);

  const articleHeadline = useCallback((item: FeedItem) => translatedText(displayHeadline(item)), [translatedText]);
  const articleSummary = useCallback((item: FeedItem) => translatedText(summaryFor(item)), [translatedText]);
  const articleTakeaway = useCallback((item: FeedItem) => translatedText(String(item.takeaway || '').replace(/^💡\s*/, '')), [translatedText]);
  const articleTopic = useCallback((item: FeedItem) => topicLabel(topicFor(item)), [topicLabel]);
  const articleTime = useCallback((item: FeedItem, index = 0) => {
    if (prefs.language === 'he') return timeLabel(item, index);
    if (item.hasSourceDate === false) return tr('תאריך לא זמין');
    const d = itemDate(item, index);
    const minutes = Math.max(0, Math.floor((Date.now() - d.getTime()) / 60000));
    if (minutes < 1) return tr('עכשיו');
    if (minutes < 60) return tr('לפני {n} דקות', { n: minutes });
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return hours === 1 ? tr('לפני שעה') : tr('לפני {n} שעות', { n: hours });
    const days = Math.floor(hours / 24);
    return days === 1 ? tr('לפני יום') : tr('לפני {n} ימים', { n: days });
  }, [prefs.language, tr]);

  useEffect(() => { viewRef.current = view; }, [view]);
  useEffect(() => {
    const previousFilter = feedFilterRef.current;
    if (previousFilter === 'unread' && prefs.feedFilter !== 'unread') flushUnreadSessionToRead();
    if (previousFilter !== 'unread' && prefs.feedFilter === 'unread') {
      unreadSessionKeysRef.current = [];
      setUnreadSessionKeys([]);
    }
    feedFilterRef.current = prefs.feedFilter;
  }, [prefs.feedFilter]);
  useEffect(() => { readKeysRef.current = readKeys; }, [readKeys]);
  useEffect(() => { unreadSessionKeysRef.current = unreadSessionKeys; }, [unreadSessionKeys]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [prefsRaw, savedRaw, savedItemsRaw, readRaw, appearanceRaw, feedRaw, breakingRaw, syncRaw] = await Promise.all([
          AsyncStorage.getItem(STORAGE_KEYS.prefs),
          AsyncStorage.getItem(STORAGE_KEYS.saved),
          AsyncStorage.getItem(STORAGE_KEYS.savedItems),
          AsyncStorage.getItem(STORAGE_KEYS.read),
          AsyncStorage.getItem(STORAGE_KEYS.appearance),
          AsyncStorage.getItem(STORAGE_KEYS.feedCache),
          AsyncStorage.getItem(STORAGE_KEYS.breakingCache),
          AsyncStorage.getItem(STORAGE_KEYS.lastSync),
        ]);
        if (!alive) return;
        if (prefsRaw) {
          prefsLoadedFromStorageRef.current = true;
          const parsed = JSON.parse(prefsRaw) as Partial<Prefs>;
          setPrefs(prev => ({
            ...prev,
            ...parsed,
            topics: Array.isArray(parsed.topics) ? parsed.topics : prev.topics,
            sources: Array.isArray(parsed.sources) ? parsed.sources : prev.sources,
            days: typeof parsed.days === 'number' ? Math.max(1, Math.min(7, Math.round(parsed.days))) : prev.days,
            feedFilter: parsed.feedFilter === 'unread' ? 'unread' : 'all',
            language: normalizeLanguage(parsed.language),
          }));
        }
        if (savedRaw) setSavedKeys(JSON.parse(savedRaw).filter((x: unknown) => typeof x === 'string').slice(0, 500));
        if (savedItemsRaw) {
          const parsed = JSON.parse(savedItemsRaw) as Record<string, SavedArticleRecord>;
          const clean = Object.fromEntries(Object.entries(parsed || {}).filter(([, record]) => record?.item)) as Record<string, SavedArticleRecord>;
          setSavedArticleRecords(clean);
        }
        if (readRaw) setReadKeys(JSON.parse(readRaw).filter((x: unknown) => typeof x === 'string').slice(0, 1200));
        if (appearanceRaw === 'dark' || appearanceRaw === 'light' || appearanceRaw === 'system') setAppearance(appearanceRaw);
        let restoredCachedFeed = false;
        if (feedRaw) {
          const cachedFeed = JSON.parse(feedRaw);
          if (Array.isArray(cachedFeed) && cachedFeed.length) {
            setItems(cachedFeed);
            restoredCachedFeed = true;
          }
        }
        if (breakingRaw) {
          const cachedBreaking = JSON.parse(breakingRaw);
          if (Array.isArray(cachedBreaking)) setBreaking(dedupeItems(cachedBreaking));
        }
        if (syncRaw) setLastSyncedAt(syncRaw);
        // Do not keep the first screen blank while the network refresh runs.
        // Cached feed should paint immediately and refresh in the background.
        if (restoredCachedFeed) setLoading(false);
      } catch {
        // Keep the app usable if device storage contains invalid stale data.
      } finally {
        storageReady.current = true;
      }
    })();
    return () => { alive = false; };
  }, []);

  useEffect(() => { if (storageReady.current) AsyncStorage.setItem(STORAGE_KEYS.prefs, JSON.stringify(prefs)).catch(() => null); }, [prefs]);
  useEffect(() => { setSettingsPrefs(prev => samePrefs(prev, prefs) ? prev : prefs); }, [prefs]);
  useEffect(() => { if (storageReady.current) AsyncStorage.setItem(STORAGE_KEYS.saved, JSON.stringify(savedKeys.slice(-500))).catch(() => null); }, [savedKeys]);
  useEffect(() => { if (storageReady.current) AsyncStorage.setItem(STORAGE_KEYS.savedItems, JSON.stringify(savedArticleRecords)).catch(() => null); }, [savedArticleRecords]);
  useEffect(() => { if (storageReady.current) AsyncStorage.setItem(STORAGE_KEYS.read, JSON.stringify(readKeys.slice(-1200))).catch(() => null); }, [readKeys]);
  useEffect(() => { if (storageReady.current) AsyncStorage.setItem(STORAGE_KEYS.appearance, appearance).catch(() => null); }, [appearance]);


  useEffect(() => {
    let alive = true;
    const lang = prefs.language;
    if (lang === 'he') { setTranslationCache({}); return; }
    const storageKey = `${TRANSLATION_CACHE_PREFIX}.${lang}`;
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(storageKey);
        if (alive && raw) setTranslationCache(JSON.parse(raw));
      } catch { if (alive) setTranslationCache({}); }
    })();
    return () => { alive = false; };
  }, [prefs.language]);

  useEffect(() => {
    let cancelled = false;
    const lang = prefs.language;
    if (lang === 'he' || languageLoading || view === 'settings') return;
    const storageKey = `${TRANSLATION_CACHE_PREFIX}.${lang}`;
    const candidates = collectLanguageCandidates(items, breaking, knownTopics);
    const missing = candidates.filter(text => !BUILTIN_TRANSLATIONS[lang]?.[text] && !CORE_TRANSLATIONS[lang]?.[text] && !translationCache[translationKey(lang, text)]).slice(0, 600);
    if (!missing.length) return;
    (async () => {
      const next = await warmLanguageCache(lang, missing, translationCache, () => cancelled || viewRef.current === 'settings', cache => {
        if (cancelled) return;
        AsyncStorage.setItem(storageKey, JSON.stringify(cache)).catch(() => null);
      });
      if (!cancelled) {
        setTranslationCache(next);
        AsyncStorage.setItem(storageKey, JSON.stringify(next)).catch(() => null);
      }
    })();
    return () => { cancelled = true; };
  }, [prefs.language, items, breaking, knownTopics, languageLoading, view]);

  useEffect(() => {
    if (loading || !items.length) return;
    const runId = ++warmupRunRef.current;
    const timer = setTimeout(() => {
      const priority: AppLanguage[] = ['en', 'ru', 'ar'];
      const candidates = collectLanguageCandidates(items, breaking, knownTopics);
      (async () => {
        for (const lang of priority) {
          if (warmupRunRef.current !== runId) return;
          if (lang === prefs.language) continue;
          // Never warm while the user is actively changing Settings; restart later.
          if (viewRef.current === 'settings') return;
          const storageKey = `${TRANSLATION_CACHE_PREFIX}.${lang}`;
          let existing: Record<string, string> = {};
          try {
            const raw = await AsyncStorage.getItem(storageKey);
            existing = raw ? JSON.parse(raw) : {};
          } catch { existing = {}; }
          await warmLanguageCache(lang, candidates, existing, () => warmupRunRef.current !== runId || viewRef.current === 'settings', cache => {
            AsyncStorage.setItem(storageKey, JSON.stringify(cache)).catch(() => null);
          });
          await delay(700);
        }
      })().catch(() => null);
    }, 2800);
    return () => { clearTimeout(timer); warmupRunRef.current += 1; };
  }, [loading, items, breaking, knownTopics, prefs.language, view]);

  const loadAll = async () => {
    setRefreshing(true);
    setError(null);
    try {
      const [feed, breakingFeed] = await Promise.all([fetchFeed(), fetchBreakingFeed()]);
      const feedItems = Array.isArray(feed.items) ? feed.items : [];
      const breakingItems = Array.isArray(breakingFeed.items) ? breakingFeed.items : [];
      const languageAtLoad = prefs.language;
      setItems(feedItems);
      setBreaking(dedupeItems(breakingItems));
      // Feed paint must not wait for hundreds of remote translation requests.
      // Fill the selected-language cache progressively after the fresh feed is visible.
      if (languageAtLoad !== 'he') {
        const storageKey = `${TRANSLATION_CACHE_PREFIX}.${languageAtLoad}`;
        let existing = translationCache;
        AsyncStorage.getItem(storageKey)
          .then(raw => {
            if (raw) existing = { ...existing, ...JSON.parse(raw) };
            return translateAllMissing(languageAtLoad, collectLanguageCandidates(feedItems, breakingItems, allTopics(feedItems)), existing, additions => {
              setTranslationCache(prev => ({ ...prev, ...additions }));
            });
          })
          .then(prepared => {
            setTranslationCache(prepared);
            AsyncStorage.setItem(storageKey, JSON.stringify(prepared)).catch(() => null);
          })
          .catch(() => null);
      }
      const syncStamp = new Date().toISOString();
      setLastSyncedAt(syncStamp);
      AsyncStorage.multiSet([
        [STORAGE_KEYS.feedCache, JSON.stringify(feedItems.slice(0, 300))],
        [STORAGE_KEYS.breakingCache, JSON.stringify(breakingItems.slice(0, 150))],
        [STORAGE_KEYS.lastSync, syncStamp],
      ]).catch(() => null);
      setPrefs(prev => ({
        ...prev,
        sources: prefsLoadedFromStorageRef.current ? prev.sources : allSources([...feedItems, ...breakingItems]),
        topics: prefsLoadedFromStorageRef.current ? prev.topics : allTopics(feedItems),
        language: normalizeLanguage(prev.language),
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : tr('שגיאה בטעינת הנתונים'));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => { loadAll(); }, []);
  useEffect(() => {
    let cancelled = false;
    Linking.getInitialURL().then(url => {
      if (!cancelled) handleIncomingSharedArticle(url).catch(() => null);
    }).catch(() => null);
    const subscription = Linking.addEventListener('url', event => {
      handleIncomingSharedArticle(event.url).catch(() => null);
    });
    return () => {
      cancelled = true;
      subscription.remove();
    };
  }, []);
  useEffect(() => () => {
    if (readFlushTimerRef.current) clearTimeout(readFlushTimerRef.current);
    if (settingsCommitTimerRef.current) clearTimeout(settingsCommitTimerRef.current);
  }, []);

  const visibleMainBase = useMemo(() => {
    const rows = items
      .map((item, index) => ({ item, index, date: itemDate(item, index) }))
      .filter(row => prefSourceSet.has(sourceName(row.item)))
      .filter(row => activeFilter !== 'all' || prefTopicSet.has(topicFor(row.item)))
      .filter(row => withinDays(row.item, row.index, prefs.days))
      .filter(row => activeFilter === 'all' || topicFor(row.item) === activeFilter)
      .sort((a, b) => b.date.getTime() - a.date.getTime())
      .map(row => row.item);
    return dedupeItems(rows);
  }, [items, prefs.days, prefSourceSet, prefTopicSet, activeFilter]);

  const visibleMain = useMemo(() => {
    return prefs.feedFilter === 'all' ? visibleMainBase : visibleMainBase.filter(item => !readKeySet.has(itemKey(item)));
  }, [visibleMainBase, prefs.feedFilter, readKeySet]);

  const visibleBreaking = useMemo(() => {
    return breaking
      .filter(item => prefSourceSet.has(sourceName(item)))
      .filter(item => activeFilter === 'all' || sourceName(item) === activeFilter || item.sources?.includes(activeFilter))
      .sort((a, b) => itemDate(b).getTime() - itemDate(a).getTime());
  }, [breaking, prefSourceSet, activeFilter]);

  const searchResults = useMemo(() => {
    const q = normalizeText(search);
    if (q.length < 2) return [];
    const words = q.split(/\s+/).filter(Boolean);
    return dedupeItems([...items, ...savedItems].filter(item => {
      const text = normalizeText([displayHeadline(item), articleHeadline(item), summaryFor(item), articleSummary(item), item.takeaway, articleTakeaway(item), topicFor(item), articleTopic(item), sourceName(item)].join(' '));
      return words.some(w => text.includes(w));
    })).slice(0, 40);
  }, [search, items, savedItems, articleHeadline, articleSummary, articleTakeaway, articleTopic]);

  const topicCounts = useMemo(() => {
    const counts: Record<string, number> = { all: visibleMain.length };
    items.filter((item, index) => prefSourceSet.has(sourceName(item)) && withinDays(item, index, prefs.days)).forEach(item => {
      const t = topicFor(item);
      counts[t] = (counts[t] || 0) + 1;
    });
    return counts;
  }, [items, prefSourceSet, prefs.days, visibleMain.length]);

  const breakingSources = useMemo(() => [...new Set(breaking.flatMap(item => item.sources?.length ? item.sources : [sourceName(item)]))].sort((a, b) => a.localeCompare(b, 'he')), [breaking]);

  async function fetchSharedArticle(shareId: string) {
    const res = await fetch(`${SHARE_ARTICLES_URL}?v=${Date.now()}`, { headers: { Accept: 'application/json', 'User-Agent': 'PoentaMobile/0.3' } });
    if (!res.ok) throw new Error(`Share article request failed: ${res.status}`);
    const data = await res.json();
    const match = (Array.isArray(data?.items) ? data.items : []).find((row: FeedItem) => row.shareId === shareId) as FeedItem | undefined;
    return match || null;
  }

  function saveArticleRecord(item: FeedItem, shared = false) {
    const key = itemKey(item);
    const storedItem = shared ? { ...item, _originLabel: 'משיתוף' } : { ...item };
    setSavedArticleRecords(prev => ({ ...prev, [key]: { item: storedItem, savedAt: Date.now(), shared } }));
    setSavedKeys(prev => prev.includes(key) ? prev : [...prev, key].slice(-500));
    return key;
  }

  function toggleSaved(item: FeedItem) {
    const key = itemKey(item);
    if (savedKeySet.has(key)) {
      setSavedKeys(prev => prev.filter(x => x !== key));
      setSavedArticleRecords(prev => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    } else {
      saveArticleRecord(item);
    }
  }

  async function handleIncomingSharedArticle(rawUrl?: string | null) {
    const shareId = sharedArticleIdFromUrl(rawUrl);
    if (!shareId) return false;
    try {
      const sharedItem = await fetchSharedArticle(shareId);
      if (!sharedItem) return false;
      saveArticleRecord(sharedItem, true);
      markRead(sharedItem);
      viewRef.current = 'saved';
      setView('saved');
      setActiveFilter('all');
      return true;
    } catch {
      return false;
    }
  }

  function markRead(item: FeedItem) {
    const key = itemKey(item);
    setReadKeys(prev => prev.includes(key) ? prev : [...prev, key]);
  }

  function markUnreadSessionProgress(keys: string[]) {
    if (!keys.length) return;
    const readSet = new Set(readKeysRef.current);
    const sessionSet = new Set(unreadSessionKeysRef.current);
    let changed = false;
    keys.forEach(key => {
      if (!readSet.has(key) && !sessionSet.has(key)) {
        sessionSet.add(key);
        changed = true;
      }
    });
    if (!changed) return;
    const next = [...sessionSet].slice(-1200);
    unreadSessionKeysRef.current = next;
    setUnreadSessionKeys(next);
  }

  function flushUnreadSessionToRead() {
    const sessionKeys = unreadSessionKeysRef.current.filter(key => !readKeysRef.current.includes(key));
    if (!sessionKeys.length) {
      unreadSessionKeysRef.current = [];
      setUnreadSessionKeys([]);
      return;
    }
    setReadKeys(prev => {
      const merged = new Set(prev);
      sessionKeys.forEach(key => merged.add(key));
      const next = [...merged].slice(-1200);
      readKeysRef.current = next;
      return next.length === prev.length ? prev : next;
    });
    unreadSessionKeysRef.current = [];
    setUnreadSessionKeys([]);
  }

  const toggleTopic = useCallback((topic: string) => {
    setSettingsPrefs(prev => ({ ...prev, topics: prev.topics.includes(topic) ? prev.topics.filter(t => t !== topic) : [...prev.topics, topic] }));
    setActiveFilter(prev => prev !== 'all' && prev === topic ? 'all' : prev);
  }, []);

  const toggleSource = useCallback((source: string) => {
    setSettingsPrefs(prev => {
      const current = prev.sources.filter(s => s !== '__NONE__');
      return { ...prev, sources: current.includes(source) ? current.filter(s => s !== source) : [...current, source] };
    });
    setActiveFilter(prev => prev !== 'all' && prev === source ? 'all' : prev);
  }, []);

  const setSettingsDays = useCallback((days: number) => {
    setSettingsPrefs(prev => prev.days === days ? prev : ({ ...prev, days }));
  }, []);

  function scheduleSettingsCommit() {
    const draft = settingsPrefs;
    if (samePrefs(prefs, draft)) return;
    if (settingsCommitTimerRef.current) clearTimeout(settingsCommitTimerRef.current);
    // Leave Settings immediately; defer the expensive feed filter/dedupe/storage pass
    // until after navigation has painted, so Settings stays fast and the back-to-feed
    // tap does not feel stuck on Android.
    const apply = () => setPrefs(prev => samePrefs(prev, draft) ? prev : draft);
    settingsCommitTimerRef.current = setTimeout(() => {
      settingsCommitTimerRef.current = null;
      if (Platform.OS === 'web') requestAnimationFrame(apply);
      else InteractionManager.runAfterInteractions(apply);
    }, Platform.OS === 'web' ? 30 : 120);
  }

  function switchView(next: ViewMode) {
    const leavingSettings = viewRef.current === 'settings' && next !== 'settings';
    // Keep the imperative ref in sync before React's next render so viewability logic
    // cannot mark breaking/search/saved rows as normal home-feed rows during tab changes.
    viewRef.current = next;
    setView(next);
    if (next !== 'more') setMoreScreen('menu');
    setActiveFilter('all');
    if (leavingSettings) scheduleSettingsCommit();
  }

  const switchLanguageAtomically = useCallback(async (lang: AppLanguage) => {
    if (lang === prefs.language) return;
    if (lang === 'he') {
      setTranslationCache({});
      setSettingsPrefs(prev => ({ ...prev, language: lang }));
      setPrefs(prev => ({ ...prev, language: lang }));
      return;
    }
    setLanguageLoading(lang);
    const storageKey = `${TRANSLATION_CACHE_PREFIX}.${lang}`;
    try {
      let existing: Record<string, string> = {};
      try {
        const raw = await AsyncStorage.getItem(storageKey);
        existing = raw ? JSON.parse(raw) : {};
      } catch { existing = {}; }
      const candidates = collectLanguageCandidates(items, breaking, [...knownTopics, ...settingsPrefs.topics]);
      const prepared = await translateAllMissing(lang, candidates, existing);
      await AsyncStorage.setItem(storageKey, JSON.stringify(prepared));
      setTranslationCache(prepared);
      setSettingsPrefs(prev => ({ ...prev, language: lang }));
      setPrefs(prev => ({ ...prev, language: lang }));
    } finally {
      setLanguageLoading(null);
    }
  }, [prefs.language, items, breaking, knownTopics, settingsPrefs.topics]);

  const renderTabs = () => {
    const tabs = view === 'breaking' ? breakingSources : knownTopics;
    return <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.tabsScroll} contentContainerStyle={styles.tabs} keyboardShouldPersistTaps="always" nestedScrollEnabled directionalLockEnabled>
      <Chip label={tr('הכל')} active={activeFilter === 'all'} onPress={() => setActiveFilter('all')} count={view === 'breaking' ? visibleBreaking.length : topicCounts.all} themeKey={themeKey} />
      {tabs.map(t => <Chip key={t} label={view === 'breaking' ? t : topicLabel(t)} active={activeFilter === t} onPress={() => setActiveFilter(t)} count={view === 'breaking' ? breaking.filter(i => sourceName(i) === t || i.sources?.includes(t)).length : topicCounts[t] || 0} themeKey={themeKey} />)}
    </ScrollView>;
  };

  const MoreBack = ({ to = 'menu' as MoreScreen }: { to?: MoreScreen }) => <TouchableOpacity style={styles.moreBack} onPress={() => setMoreScreen(to)}><Text style={styles.moreBackText}>{tr('חזרה')}</Text></TouchableOpacity>;

  const MoreRow = ({ title, subtitle, onPress, disabled = false, icon }: { title: string; subtitle: string; onPress?: () => void; disabled?: boolean; icon?: 'share' | 'arrow' }) => <TouchableOpacity style={[styles.moreRow, disabled && styles.moreRowDisabled]} onPress={onPress} activeOpacity={disabled ? 1 : 0.82}>
    {icon === 'share' ? <View style={styles.shareActionIcon}><Image source={POENTA_NAV_ICON} style={styles.shareActionImage as any} /></View> : <Text style={styles.moreArrow}>›</Text>}
    <View style={styles.moreRowText}><Text style={styles.moreTitle}>{tr(title)}</Text><Text style={styles.moreSub}>{tr(subtitle)}</Text></View>
  </TouchableOpacity>;

  const renderMore = () => {
    if (moreScreen === 'settings') return <View style={styles.panel}>
      <View style={styles.moreHead}><MoreBack /><View style={styles.moreHeadText}><Text style={styles.settingsTitle}>{tr('הגדרות')}</Text><Text style={styles.moreHeadSub}>{tr('התאמה אישית של חוויית השימוש.')}</Text></View></View>
      <View style={styles.moreList}><MoreRow title="מצב תצוגה" subtitle="כהה, בהיר או לפי מערכת" onPress={() => setMoreScreen('appearance')} /></View>
    </View>;
    if (moreScreen === 'appearance') return <View style={styles.panel}>
      <View style={styles.moreHead}><MoreBack to="settings" /><View style={styles.moreHeadText}><Text style={styles.settingsTitle}>{tr('מצב תצוגה')}</Text><Text style={styles.moreHeadSub}>{tr('בחר איך Poenta תיראה אצלך.')}</Text></View><Text style={styles.savedPill}>{tr('נשמר')}</Text></View>
      <View style={styles.wrap}>{[
        { code: 'dark' as const, name: tr('כהה') }, { code: 'light' as const, name: tr('בהיר') }, { code: 'system' as const, name: tr('לפי מערכת') },
      ].map(o => <Chip key={o.code} label={o.name} active={appearance === o.code} onPress={() => setAppearance(o.code)} themeKey={themeKey} />)}</View>
      <Text style={styles.translationNote}>{tr('“לפי מערכת” מחליף אוטומטית בין לייט לדרק לפי הגדרת המכשיר.')}</Text>
    </View>;
    if (moreScreen === 'about') return <View style={styles.panel}>
      <View style={styles.moreHead}><MoreBack /><View style={styles.moreHeadText}><Text style={styles.settingsTitle}>{tr('אודות Poenta')}</Text><Text style={styles.moreHeadSub}>{tr('מה Poenta עושה ולמה היא נבנתה.')}</Text></View></View>
      <View style={styles.aboutContent}>
        <Text style={styles.about}>{tr('Poenta / פואנטה היא שירות חדשות אישי בעברית שמרכז, מסכם ומארגן ידיעות ממקורות חיצוניים לפי מקורות, תחומי עניין והעדפות שימוש.')}</Text>
        <Text style={styles.about}>{tr('המטרה: להבין מהר מה באמת קרה, למה זה חשוב ומה הפואנטה — בלי כותרות מטעות, רעש מיותר וגלילה אינסופית.')}</Text>
        <Text style={styles.moreSectionTitle}>{tr('מה מוצג באפליקציה?')}</Text>
        <Text style={styles.about}>{tr('• פיד חדשות חכם ומותאם אישית\n• תקצירים, הקשרים וניסוחי פואנטה בעזרת AI ובקרות איכות\n• קישורים למקורות המקוריים\n• שמורים, מבזקים, מקורות ותחומי עניין')}</Text>
        <Text style={styles.moreSectionTitle}>{tr('גרסה')}</Text><Text style={styles.about}>Poenta 0.3.36</Text>
      </View>
    </View>;
    if (moreScreen === 'terms') return <View style={styles.panel}>
      <View style={styles.moreHead}><MoreBack /><View style={styles.moreHeadText}><Text style={styles.settingsTitle}>{tr('תנאי שימוש')}</Text><Text style={styles.moreHeadSub}>{tr('המסמך המשפטי לשימוש ב־Poenta.')}</Text></View></View>
      <View style={styles.aboutContent}>
        <Text style={styles.about}>{tr('עדכון אחרון: 2026-06-01')}</Text>
        <Text style={styles.about}>{tr('Poenta היא שירות חדשות אישי שמרכז ידיעות ממקורות חיצוניים, מציג תקצירים, הקשרים, קישורים למקורות מקוריים וכלי סינון לפי מקורות ותחומי עניין.')}</Text>
        <Text style={styles.about}>{tr('התוכן מבוסס על מקורות חיצוניים. זכויות היוצרים בתוכן המקורי, בכותרות המקור, בתמונות ובחומרים המקוריים שייכות לבעליהן. Poenta אינה מחליפה את המקור המקורי ואינה טוענת לבעלות על תוכן צד שלישי.')}</Text>
        <Text style={styles.about}>{tr('חלק מהתקצירים, הכותרות, ההקשרים או ניסוחי “הפואנטה” עשויים להיווצר או להיערך בעזרת AI. ייתכנו טעויות, אי־דיוקים או השמטות; במקרה של סתירה המקור המקורי הוא נקודת הייחוס.')}</Text>
        <Text style={styles.about}>{tr('השירות מיועד למידע חדשותי וכללי בלבד ואינו מהווה ייעוץ משפטי, פיננסי, רפואי, ביטחוני או מקצועי. השימוש הוא באחריות המשתמש.')}</Text>
        <Text style={styles.about}>{tr('לפניות בנושא תנאי השימוש: support@poenta.app')}</Text>
      </View>
    </View>;
    if (moreScreen === 'privacy') return <View style={styles.panel}>
      <View style={styles.moreHead}><MoreBack /><View style={styles.moreHeadText}><Text style={styles.settingsTitle}>{tr('מדיניות פרטיות')}</Text><Text style={styles.moreHeadSub}>{tr('איך Poenta מתייחסת למידע ולהעדפות המשתמש.')}</Text></View></View>
      <View style={styles.aboutContent}>
        <Text style={styles.about}>{tr('עדכון אחרון: 2026-06-01')}</Text>
        <Text style={styles.about}>{tr('בגרסה הראשונה, ללא הרשמה וללא התחברות, Poenta מיועדת לעבוד עם מידע מינימלי.')}</Text>
        <Text style={styles.about}>{tr('העדפות מקומיות כמו מקורות, תחומי עניין, פריטים שמורים והגדרות תצוגה עשויות להישמר במכשיר או בדפדפן.')}</Text>
        <Text style={styles.about}>{tr('ייתכן שייאסף מידע טכני בסיסי כמו IP, סוג דפדפן/מכשיר, זמני גישה ושגיאות לצורך אבטחה, תפעול ושיפור השירות.')}</Text>
        <Text style={styles.about}>{tr('Poenta אינה מוכרת מידע אישי. בגרסה הראשונה אין צורך בהרשאות מיקום, אנשי קשר, מצלמה או מיקרופון.')}</Text>
        <Text style={styles.about}>{tr('לפניות פרטיות ותמיכה: support@poenta.app')}</Text>
      </View>
    </View>;
    if (moreScreen === 'contact') return <View style={styles.panel}>
      <View style={styles.moreHead}><MoreBack /><View style={styles.moreHeadText}><Text style={styles.settingsTitle}>{tr('צור קשר')}</Text><Text style={styles.moreHeadSub}>{tr('פניות, הצעות ושאלות על Poenta.')}</Text></View></View>
      <View style={styles.aboutContent}>
        <Text style={styles.about}>{tr('לדיווח על תקלה, בעיית טעינה, תוכן שגוי או שאלה כללית:')}</Text>
        <Text style={styles.moreSectionTitle}>support@poenta.app</Text>
        <Text style={styles.about}>{tr('מומלץ לצרף צילום מסך, סוג מכשיר, מערכת הפעלה ותיאור קצר של הבעיה.')}</Text>
      </View>
    </View>;
    return <View style={styles.panel}>
      <View style={styles.moreHead}><View style={styles.moreHeadText}><Text style={styles.title}>{tr('עוד')}</Text><Text style={styles.moreHeadSub}>{tr('הגדרות ומידע נוסף על Poenta.')}</Text></View></View>
      <View style={styles.moreList}>
        <MoreRow title="שיתוף לאפליקציה" subtitle="שלח קישור ל־Poenta ב־WhatsApp עם טקסט מוכן" icon="share" onPress={() => Linking.openURL(`https://wa.me/?text=${encodeURIComponent(APP_SHARE_TEXT)}`).catch(() => null)} />
        <MoreRow title="משתמש" subtitle="לא פעיל כרגע" disabled />
        <MoreRow title="הגדרות" subtitle="מראה, מצב תצוגה והעדפות נוספות" onPress={() => setMoreScreen('settings')} />
        <MoreRow title="אודות" subtitle="מה Poenta עושה, מקורות, פרטיות וגרסה" onPress={() => setMoreScreen('about')} />
        <MoreRow title="תנאי שימוש" subtitle="המסמך הרשמי לשימוש באפליקציה" onPress={() => setMoreScreen('terms')} />
        <MoreRow title="מדיניות פרטיות" subtitle="נוסח מדיניות הפרטיות של Poenta" onPress={() => setMoreScreen('privacy')} />
        <MoreRow title="צור קשר" subtitle="פרטי קשר ותמיכה" onPress={() => setMoreScreen('contact')} />
      </View>
    </View>;
  };

  const renderSettings = () => <View style={styles.panel}>
    <Text style={styles.title}>{tr('הגדרות Poenta')}</Text>
    <Text style={styles.subtitle}>{tr('תחומי עניין, מקורות וסינון אישי — כמו בגרסת ה־web שפיתחנו.')}</Text>

    <View style={styles.settingsCard}>
      <View style={styles.settingsHead}><Text style={styles.settingsTitle}>{tr('תחומי עניין')}</Text><Text style={styles.savedPill}>{tr('נשמר במכשיר')}</Text></View>
      <View style={styles.bulkRow}>
        <TouchableOpacity style={styles.bulkBtn} onPress={() => setSettingsPrefs(prev => sameList(prev.topics, knownTopics) ? prev : ({ ...prev, topics: knownTopics }))}><Text style={styles.bulkText}>{tr('סמן הכל')}</Text></TouchableOpacity>
        <TouchableOpacity style={styles.bulkBtn} onPress={() => setSettingsPrefs(prev => prev.topics.length ? ({ ...prev, topics: [] }) : prev)}><Text style={styles.bulkText}>{tr('בטל הכל')}</Text></TouchableOpacity>
      </View>
      <View style={styles.wrap}>{knownTopics.map(t => <SettingsTopicChip key={t} topic={t} label={topicLabel(t)} active={settingsPrefTopicSet.has(t)} onToggle={toggleTopic} themeKey={themeKey} />)}</View>
      <View style={styles.inputRow}>
        <TextInput style={styles.input} value={customTopic} onChangeText={setCustomTopic} placeholder={tr('תחום אישי, למשל מיצרי הורמוז')} placeholderTextColor={colors.muted} />
        <TouchableOpacity style={styles.addBtn} onPress={() => { const t = customTopic.trim().slice(0, 22); if (t) { setSettingsPrefs(prev => ({ ...prev, topics: [...new Set([...prev.topics, t])] })); setCustomTopic(''); } }}><Text style={styles.addText}>{tr('הוסף')}</Text></TouchableOpacity>
      </View>
    </View>

    <View style={styles.settingsCard}>
      <View style={styles.settingsHead}><Text style={styles.settingsTitle}>{tr('מקורות')}</Text><Text style={styles.savedPill}>{settingsPrefs.sources.includes('__NONE__') ? 0 : (settingsPrefs.sources.filter(s => s !== '__NONE__').length || knownSources.length)}/{knownSources.length}</Text></View>
      <View style={styles.bulkRow}>
        <TouchableOpacity style={styles.bulkBtn} onPress={() => setSettingsPrefs(prev => sameList(prev.sources, knownSources) ? prev : ({ ...prev, sources: knownSources }))}><Text style={styles.bulkText}>{tr('סמן הכל')}</Text></TouchableOpacity>
        <TouchableOpacity style={styles.bulkBtn} onPress={() => setSettingsPrefs(prev => sameList(prev.sources, ['__NONE__']) ? prev : ({ ...prev, sources: ['__NONE__'] }))}><Text style={styles.bulkText}>{tr('בטל הכל')}</Text></TouchableOpacity>
      </View>
      {groupedSources.map(group => <View key={group.key} style={styles.sourceGroup}>
        <View style={styles.sourceGroupHead}>
          <Text style={styles.sourceGroupTitle}>{tr(group.label)}</Text>
          <Text style={styles.sourceGroupCount}>{group.sources.filter(src => settingsPrefSourceSet.has(src)).length}/{group.sources.length}</Text>
        </View>
        {group.sources.map(src => <SettingsSourceRow key={src} source={src} active={settingsPrefSourceSet.has(src)} onToggle={toggleSource} themeKey={themeKey} />)}
      </View>)}
    </View>

    <View style={styles.settingsCard}>
      <View style={styles.settingsHead}><Text style={styles.settingsTitle}>{tr('סינון קריאה')}</Text><Text style={styles.savedPill}>{settingsPrefs.days === 1 ? tr('יום אחד') : `${settingsPrefs.days} ${tr('ימים')}`}</Text></View>
      <View style={styles.daysSlider}>
        <View style={styles.daysTrack}><View style={[styles.daysFill, { width: `${((settingsPrefs.days - 1) / 6) * 100}%` }]} /></View>
        <View style={styles.daysTicks}>{SETTINGS_DAYS.map(d => <TouchableOpacity key={d} style={styles.dayTickTouch} onPress={() => setSettingsDays(d)} activeOpacity={0.82}><View style={[styles.dayDot, settingsPrefs.days >= d && styles.dayDotOn]} /><Text style={[styles.dayLabel, settingsPrefs.days === d && styles.dayLabelOn]}>{d}</Text></TouchableOpacity>)}</View>
      </View>
    </View>

    <View style={styles.settingsCard}>
      <View style={styles.settingsHead}><Text style={styles.settingsTitle}>{tr('שפת האפליקציה והפיד')}</Text><Text style={styles.savedPill}>{languageName(settingsPrefs.language)}</Text></View>
      <View style={[styles.languageDropdown, styles.languageDropdownAbove]}>
        {LANGUAGE_OPTIONS.map(option => {
          const on = settingsPrefs.language === option.code;
          const chooseLanguage = () => { switchLanguageAtomically(option.code).catch(() => null); };
          return <TouchableOpacity key={option.code} style={[styles.languageOption, on && styles.languageOptionOn]} onPress={chooseLanguage} activeOpacity={0.82} accessibilityLabel={`${tr('שפת האפליקציה והפיד')} ${option.name}`}>
            <Text style={[styles.languageOptionCode, on && styles.languageOptionCodeOn]}>{option.code.toUpperCase()}</Text>
            <Text style={[styles.languageOptionName, option.dir === 'rtl' && styles.languageOptionRtl, on && styles.languageOptionNameOn]}>{option.name}</Text>
          </TouchableOpacity>;
        })}
      </View>
      <Text style={styles.translationNote}>{tr('שינוי השפה מתרגם את כל ממשק Poenta ואת טקסטי הכתבות. כותרות המקור ושמות המקורות נשארים כפי שהמקור פרסם.')}</Text>
    </View>

  </View>;

  const list = view === 'breaking' ? visibleBreaking : view === 'saved' ? savedItems : view === 'search' ? searchResults : visibleMain;
  const unreadDisplayCount = visibleMainBase.filter(i => {
    const key = itemKey(i);
    return !readKeySet.has(key) && !unreadSessionKeySet.has(key);
  }).length;
  const totalMainCount = visibleMainBase.length;
  const unreadPct = totalMainCount ? Math.max(0, Math.min(100, Math.round((unreadDisplayCount / totalMainCount) * 100))) : 0;
  const unreadRatio = totalMainCount ? unreadDisplayCount / totalMainCount : 0;
  const unreadMarkerLeftPct = totalMainCount ? Math.max(13, Math.min(86, 13 + (1 - unreadRatio) * 73)) : 13;

  const keyExtractor = useCallback((item: FeedItem, index: number) => `${itemKey(item)}-${index}`, []);
  const renderItem = useCallback(({ item, index }: { item: FeedItem; index: number }) => view === 'breaking'
    ? <BreakingCard item={item} index={index} headline={articleHeadline(item)} time={articleTime(item, index)} themeKey={themeKey} />
    : <ArticleCard item={item} index={index} saved={savedKeySet.has(itemKey(item))} onSave={() => { toggleSaved(item); markRead(item); }} onOpen={() => markRead(item)} headline={articleHeadline(item)} summary={articleSummary(item)} takeaway={articleTakeaway(item)} topic={articleTopic(item)} time={articleTime(item, index)} tr={tr} themeKey={themeKey} />, [view, savedKeySet, articleHeadline, articleSummary, articleTakeaway, articleTopic, articleTime, tr, themeKey]);
  const viewabilityConfig = useRef({ itemVisiblePercentThreshold: 62, minimumViewTime: 450 }).current;
  const onViewableItemsChanged = useRef(({ viewableItems }: { viewableItems: Array<{ item?: FeedItem }> }) => {
    if (viewRef.current !== 'home') return;
    const visibleKeys = viewableItems.map(v => v.item).filter((item): item is FeedItem => !!item).map(itemKey);
    // In “new/unread only” mode the visible list must stay stable while the user
    // reads or scrolls it. Track session progress separately so the freshness bar
    // and count move, but do not merge into persistent readKeys until the user
    // leaves “new” mode.
    if (feedFilterRef.current === 'unread') {
      markUnreadSessionProgress(visibleKeys);
      return;
    }
    const existing = new Set(readKeysRef.current);
    const nextKeys = visibleKeys.filter(key => !existing.has(key));
    if (!nextKeys.length) return;
    nextKeys.forEach(key => existing.add(key));
    readKeysRef.current = [...existing].slice(-1200);
    if (readFlushTimerRef.current) return;
    readFlushTimerRef.current = setTimeout(() => {
      readFlushTimerRef.current = null;
      setReadKeys(prev => {
        const merged = new Set(prev);
        readKeysRef.current.forEach(key => merged.add(key));
        return merged.size === prev.length ? prev : [...merged].slice(-1200);
      });
    }, 650);
  }).current;

  const listHeader = <>
    {view === 'search' && <>
      <Text style={styles.title}>{tr('חיפוש')}</Text>
      <Text style={styles.subtitle}>{tr('חיפוש חכם בכתבות מהפיד ומהשמורים. אפשר לכתוב רעיון כמו “הופעות רוק”.')}</Text>
      <TextInput style={styles.searchInput} value={search} onChangeText={setSearch} placeholder={tr('מה לחפש? למשל הופעות רוק')} placeholderTextColor={colors.muted} textAlign={RTL_TEXT_ALIGN} autoCorrect={false} autoCapitalize="none" blurOnSubmit={false} returnKeyType="search" />
    </>}

    {view === 'saved' && <>
      <Text style={styles.title}>{tr('שמורים')}</Text>
      <Text style={styles.subtitle}>{savedItems.length ? `${savedItems.length} ${tr('כתבות שמורות')}` : tr('אפשר לשמור כתבות מהפיד בלחיצה על שמור.')}</Text>
    </>}

    {loading && <ActivityIndicator color={colors.yellow} style={{ marginTop: 28 }} />}
    {error && <Text style={styles.error}>{tr('שגיאה בטעינת הפיד')}: {error}</Text>}
  </>;

  const listEmptyText = view === 'search' && search.trim().length < 2 ? tr('הקלד לפחות 2 אותיות לחיפוש.') : tr('אין אייטמים להצגה כרגע.');

  return <SafeAreaView style={styles.safe}>
    <StatusBar style={isLight ? "dark" : "light"} />
    <View style={[styles.topbar, { height: topbarHeight, paddingTop: topInset }]}>
      <View style={styles.header}>
        <Image source={isLight ? POENTA_LOGO_LIGHT : POENTA_LOGO} style={styles.logoImage as any} resizeMode="contain" />
        <TouchableOpacity style={styles.topMore} accessibilityLabel={tr('עוד')} onPress={() => switchView('more')}><Text style={styles.topMoreText}>☰</Text></TouchableOpacity>
      </View>
      {showFreshnessMeter && <View style={styles.updates}>
        <TouchableOpacity style={styles.updateTrack} onPress={loadAll} activeOpacity={0.86} accessibilityLabel={tr('רענן פיד')}>
          <View style={[styles.updateFill, { width: `${unreadPct}%` }]} />
          <Text style={styles.updateText}>{tr('מדד החדשים שלך')}</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[styles.updateTotalPill, prefs.feedFilter === 'all' && styles.updatePillActive]} onPress={() => setPrefs(prev => ({ ...prev, feedFilter: 'all' }))} activeOpacity={0.84} accessibilityLabel={tr('הצג את כל הידיעות')}>
          <Text style={styles.updatePillText}>{totalMainCount}</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[styles.updatePill, { left: `${unreadMarkerLeftPct}%` }, prefs.feedFilter === 'unread' && styles.updatePillActive]} onPress={() => setPrefs(prev => ({ ...prev, feedFilter: prev.feedFilter === 'unread' ? 'all' : 'unread' }))} activeOpacity={0.84} accessibilityLabel={tr('סנן לחדשים')}>
          <Text style={styles.updatePillText}>{unreadDisplayCount}</Text>
        </TouchableOpacity>
      </View>}
      <View style={styles.tabline}>{(view === 'home' || view === 'breaking') && renderTabs()}</View>
    </View>

    {view === 'settings' || view === 'more' ? <ScrollView style={styles.scroll} contentContainerStyle={[styles.content, { paddingTop: topbarHeight + 4, paddingBottom: navHeight + 52 }]} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={loadAll} tintColor={colors.yellow} colors={[colors.yellow]} progressViewOffset={topbarHeight} />} keyboardShouldPersistTaps="handled">
      {view === 'settings' ? renderSettings() : renderMore()}
    </ScrollView> : <FlatList
      key={view === 'breaking' ? 'breaking-list' : view === 'home' ? 'home-list' : view === 'search' ? 'search-list' : 'saved-list'}
      style={styles.scroll}
      contentContainerStyle={[styles.content, { paddingTop: topbarHeight + 4, paddingBottom: navHeight + 52 }]}
      data={list}
      keyExtractor={keyExtractor}
      renderItem={renderItem}
      ListHeaderComponent={listHeader}
      ListEmptyComponent={!loading ? <Text style={styles.empty}>{listEmptyText}</Text> : null}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={loadAll} tintColor={colors.yellow} colors={[colors.yellow]} progressViewOffset={topbarHeight} />}
      initialNumToRender={6}
      maxToRenderPerBatch={6}
      updateCellsBatchingPeriod={80}
      windowSize={5}
      removeClippedSubviews={view !== 'search'}
      onViewableItemsChanged={onViewableItemsChanged}
      viewabilityConfig={viewabilityConfig}
      keyboardShouldPersistTaps="always"
      keyboardDismissMode="none"
    />}

    {languageLoading && <View style={styles.languageLoadingOverlay}>
      <ActivityIndicator color={colors.yellow} size="large" />
      <Text style={styles.languageLoadingTitle}>{languageName(languageLoading)}</Text>
      <Text style={styles.languageLoadingText}>{tr('טוען את כל האפליקציה בשפה החדשה…')}</Text>
    </View>}

    <View style={[styles.nav, { height: navHeight, paddingBottom: bottomInset }]}>
      <NavButton label={tr('שמור')} icon="bookmark" active={view === 'saved' || savedKeys.length > 0} filled={view === 'saved'} onPress={() => switchView('saved')} themeKey={themeKey} />
      <NavButton label={tr('חיפוש')} icon="search" active={view === 'search'} onPress={() => switchView('search')} themeKey={themeKey} />
      <NavButton label={tr('הגדרות')} icon="settings" active={view === 'settings'} onPress={() => switchView('settings')} themeKey={themeKey} />
      <NavButton label={tr('מבזקים')} icon="breaking" active={view === 'breaking'} onPress={() => switchView('breaking')} themeKey={themeKey} />
      <NavButton label="Poenta" logo active={view === 'home'} onPress={() => switchView('home')} themeKey={themeKey} />
    </View>
  </SafeAreaView>;
}


export default function App() {
  return <SafeAreaProvider><PoentaApp /></SafeAreaProvider>;
}
function createStyles(c: AppColors) {
return StyleSheet.create({
  safe: { flex: 1, backgroundColor: c.bg, direction: 'rtl', alignItems: 'stretch' },
  topbar: { position: 'absolute', top: 0, left: 0, right: 0, zIndex: 50, backgroundColor: c.topbar, borderBottomWidth: 1, borderBottomColor: c.border, borderBottomLeftRadius: 18, borderBottomRightRadius: 18, shadowColor: c.shadow, shadowOpacity: 0.22, shadowRadius: 22, shadowOffset: { width: 0, height: 10 }, elevation: 10, direction: 'rtl', alignItems: 'stretch' },
  header: { height: 52, paddingHorizontal: 16, paddingTop: 4, flexDirection: 'row', direction: 'rtl', alignItems: 'center', justifyContent: 'space-between', alignSelf: 'stretch' },
  topMore: { width: 36, height: 36, alignItems: 'center', justifyContent: 'center' },
  topMoreText: { color: c.secondary, fontSize: 25, fontWeight: '900', lineHeight: 30 },
  logoImage: { height: 38, width: 164 },
  updates: { height: 42, paddingHorizontal: 16, borderTopWidth: 1, borderBottomWidth: 1, borderColor: c.border, backgroundColor: c.surface, justifyContent: 'center', direction: 'rtl', alignSelf: 'stretch' },
  updatePill: { position: 'absolute', top: 4, minWidth: 34, height: 20, borderWidth: 1, borderColor: 'rgba(255,196,0,0.34)', borderRadius: 999, backgroundColor: c.surfaceSoft, alignItems: 'center', justifyContent: 'center', zIndex: 2 },
  updateTotalPill: { position: 'absolute', left: 18, top: 4, minWidth: 34, height: 20, borderWidth: 1, borderColor: 'rgba(255,196,0,0.24)', borderRadius: 999, backgroundColor: c.surfaceSoft, alignItems: 'center', justifyContent: 'center', zIndex: 2 },
  updatePillActive: { borderColor: c.yellow, backgroundColor: c.yellowBg },
  updatePillText: { color: c.yellowSoft, fontSize: 12, fontWeight: '900' },
  updateTrack: { height: 16, marginTop: 18, borderRadius: 999, overflow: 'hidden', backgroundColor: 'rgba(255,196,0,0.16)', borderWidth: 1, borderColor: 'rgba(255,196,0,0.18)', alignItems: 'center', justifyContent: 'center' },
  updateFill: { position: 'absolute', right: 0, top: 0, bottom: 0, backgroundColor: c.yellow },
  updateText: { color: c.textOnYellow, fontSize: 10.8, fontWeight: '900', letterSpacing: -0.05 },
  syncText: { color: c.muted, textAlign: 'center', fontSize: 10.5, fontWeight: '800', marginTop: 3 },
  tabline: { height: 46, paddingHorizontal: 16, justifyContent: 'center', overflow: 'hidden', direction: 'rtl', alignSelf: 'stretch' },
  scroll: { flex: 1, alignSelf: 'stretch', width: '100%', direction: 'rtl' },
  content: { flexGrow: 1, width: '100%', paddingHorizontal: 16, direction: 'rtl', alignItems: 'stretch' },
  title: { color: c.text, fontSize: 25, lineHeight: 30, fontWeight: '900', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl' },
  subtitle: { color: c.muted, fontSize: 13.5, lineHeight: 20, fontWeight: '700', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', marginTop: 7, marginBottom: 12 },
  tabsScroll: { flex: 1, alignSelf: 'stretch', width: '100%', direction: 'rtl' },
  tabs: { flexDirection: 'row', direction: 'rtl', gap: 9, alignItems: 'center', paddingHorizontal: 1, paddingLeft: 28, paddingRight: 1, flexGrow: 0 },
  chip: { height: 28, maxWidth: 132, borderWidth: 1, borderColor: c.faint, borderRadius: 999, backgroundColor: c.surfaceSoft, paddingHorizontal: 9, paddingVertical: 0, flexDirection: 'row', direction: 'rtl', gap: 6, alignItems: 'center', justifyContent: 'center' },
  chipActive: { borderColor: c.yellow, backgroundColor: c.yellow },
  chipText: { color: c.secondary, fontSize: 13, fontWeight: '800', writingDirection: 'rtl', textAlign: RTL_TEXT_ALIGN, flexShrink: 1, lineHeight: 18 },
  chipTextActive: { color: c.textOnYellow, fontWeight: '900' },
  chipCount: { minWidth: 18, height: 18, lineHeight: 18, textAlign: 'center', textAlignVertical: 'center', color: c.yellowSoft, backgroundColor: c.yellowBg, borderRadius: 999, overflow: 'hidden', paddingHorizontal: 5, fontSize: 10.5, fontWeight: '900' },
  chipCountActive: { color: c.textOnYellow, backgroundColor: 'rgba(7,16,21,0.18)', fontWeight: '900' },
  feedToggle: { flexDirection: 'row-reverse', gap: 8, marginBottom: 3 },
  card: { width: '100%', borderWidth: 1, borderColor: c.subtleBorder, borderRadius: 18, backgroundColor: c.card, paddingHorizontal: 14, paddingTop: 13, paddingBottom: 0, marginTop: 10, overflow: 'hidden', shadowColor: c.shadow, shadowOpacity: 0.12, shadowRadius: 20, shadowOffset: { width: 0, height: 8 }, elevation: 2, direction: 'rtl', alignSelf: 'stretch', alignItems: 'stretch' },
  unreadCard: { borderColor: 'rgba(255,196,0,0.18)' },
  breakingCard: { borderColor: 'rgba(255,196,0,0.22)', backgroundColor: 'rgba(255,196,0,0.055)', paddingBottom: 14 },
  metaRow: { flexDirection: 'row', direction: 'rtl', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8, paddingHorizontal: 2, gap: 8, alignSelf: 'stretch' },
  breakingMetaRow: { flexDirection: 'row', direction: 'rtl', alignItems: 'center', justifyContent: 'flex-start', alignSelf: 'stretch', marginBottom: 8, paddingHorizontal: 2, gap: 8 },
  metaActions: { flexDirection: 'row', direction: 'rtl', alignItems: 'center', justifyContent: 'flex-start', gap: 7, flexShrink: 1 },
  cat: { flexDirection: 'row-reverse', direction: 'rtl', alignItems: 'center', justifyContent: 'flex-start', gap: 7, flex: 1 },
  breakingCat: { flexDirection: 'row-reverse', direction: 'rtl', alignItems: 'center', justifyContent: 'flex-start', gap: 7, flexShrink: 1 },
  breakingSourceList: { flexDirection: 'row', direction: 'rtl', alignItems: 'center', justifyContent: 'flex-start', gap: 5, flexShrink: 1, minWidth: 0 },
  breakingSourceItem: { flexDirection: 'row', direction: 'rtl', alignItems: 'center', gap: 4, flexShrink: 1 },
  breakingSourceLink: { color: c.yellowSoft, fontSize: 12.2, fontWeight: '900', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl' },
  breakingSourceSep: { color: c.yellowSoft, opacity: 0.62, fontSize: 12, fontWeight: '900' },
  breakingDot: { color: c.red, fontSize: 22, lineHeight: 16, fontWeight: '900' },
  iconAction: { width: 15, height: 15, alignItems: 'center', justifyContent: 'center', marginLeft: 1 },
  iconActionText: { color: c.yellow, fontSize: 14, fontWeight: '900', lineHeight: 16 },
  iconActionOn: { color: c.yellow },
  star: { color: c.yellow, fontSize: 15, fontWeight: '900', lineHeight: 16 },
  bolt: { color: c.yellow, fontSize: 16, fontWeight: '900' },
  catText: { color: c.muted, fontSize: 12, fontWeight: '800', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', flexShrink: 1 },
  time: { color: c.muted, fontSize: 12, fontWeight: '700', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl' },
  heroBox: { width: '100%', alignSelf: 'stretch', position: 'relative', borderRadius: 22, overflow: 'hidden', backgroundColor: c.heroBg, minHeight: 214, justifyContent: 'flex-end', marginBottom: 11, direction: 'rtl' },
  heroShade: { position: 'absolute', left: 0, right: 0, top: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.28)' },
  image: { width: '100%', height: 214, borderRadius: 0, backgroundColor: c.heroBg },
  placeholder: { width: '100%', height: 214, borderRadius: 0, backgroundColor: c.heroBg, alignItems: 'center', justifyContent: 'center' },
  placeholderText: { color: c.textOnYellow, backgroundColor: c.yellow, overflow: 'hidden', borderRadius: 15, width: 48, height: 48, lineHeight: 48, textAlign: 'center', fontSize: 22, fontWeight: '900' },
  headlineWrap: { position: 'absolute', left: 0, right: 0, bottom: 0, paddingHorizontal: 15, paddingBottom: 13, paddingTop: 44, alignItems: 'flex-end', justifyContent: 'flex-end', direction: 'rtl' },
  headlineText: { width: '100%', color: '#FFFFFF', fontSize: 21.5, lineHeight: 24.3, fontWeight: '900', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', direction: 'rtl', letterSpacing: -0.42, textShadowColor: 'rgba(0,0,0,0.55)', textShadowRadius: 11, textShadowOffset: { width: 0, height: 2 } },
  breakingHeadline: { color: c.text, fontSize: 18.4, lineHeight: 22.4, fontWeight: '800', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', direction: 'rtl', alignSelf: 'stretch', letterSpacing: -0.18, marginBottom: 7, flexShrink: 1 },
  summary: { color: c.secondary, fontSize: 14.8, lineHeight: 21.3, fontWeight: '500', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', direction: 'rtl', alignSelf: 'stretch' },
  takeawayBox: { marginTop: 9, paddingTop: 9, borderTopWidth: 1, borderTopColor: c.border },
  takeaway: { color: c.yellowSoft, fontSize: 14, lineHeight: 17.5, fontWeight: '800', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', direction: 'rtl', alignSelf: 'stretch' },
  actionRow: { marginTop: 12, flexDirection: 'row-reverse', gap: 8, alignItems: 'stretch' },
  smallAction: { borderWidth: 1, borderColor: c.faint, borderRadius: 14, backgroundColor: c.surfaceSoft, paddingHorizontal: 10, alignItems: 'center', justifyContent: 'center' },
  smallActionOn: { borderColor: 'rgba(255,196,0,0.42)', backgroundColor: 'rgba(255,196,0,0.13)' },
  smallActionText: { color: c.yellow, fontSize: 12, fontWeight: '900' },
  sourceBox: { width: '100%', alignSelf: 'stretch', position: 'relative', marginTop: 12, marginHorizontal: -1, borderWidth: 1, borderColor: 'rgba(255,196,0,0.26)', borderRadius: 15, backgroundColor: c.sourceBg, paddingHorizontal: 12, paddingTop: 10, paddingBottom: 11, overflow: 'hidden', direction: 'rtl', alignItems: 'stretch' },
  sourceAccent: { position: 'absolute', right: 0, top: 12, bottom: 12, width: 3, borderRadius: 999, backgroundColor: 'rgba(255,196,0,0.74)' },
  sourceHead: { flexDirection: 'row', direction: 'ltr', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 7 },
  sourceLabel: { color: c.yellowSoft, backgroundColor: c.yellowBg, borderRadius: 999, paddingHorizontal: 7, paddingVertical: 4, fontSize: 10.5, fontWeight: '900', overflow: 'hidden', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', flexShrink: 0 },
  sourceBrand: { flexDirection: 'row', direction: 'rtl', alignItems: 'center', justifyContent: 'flex-start', gap: 6, flexShrink: 0, maxWidth: '64%', minWidth: 62 },
  sourceNameText: { color: c.secondary, fontSize: 11.5, fontWeight: '900', flexShrink: 0, textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl' },
  sourceIconImage: { width: 22, height: 22, borderRadius: 999, backgroundColor: 'transparent' },
  sourceIconFallback: { width: 22, height: 22, borderRadius: 7, backgroundColor: c.faint, alignItems: 'center', justifyContent: 'center' },
  sourceIconFallbackText: { color: c.text, fontSize: 9.5, fontWeight: '900' },
  sourceText: { color: c.text, fontSize: 13.8, lineHeight: 18.5, fontWeight: '700', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', direction: 'rtl', alignSelf: 'stretch' },
  panel: { gap: 12 },
  settingsCard: { borderWidth: 1, borderColor: c.border, borderRadius: 20, backgroundColor: c.surface, padding: 16, marginTop: 8 },
  settingsHead: { flexDirection: 'row', direction: 'rtl', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12, gap: 12 },
  settingsTitle: { color: c.text, fontSize: 18, lineHeight: 19, fontWeight: '900', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl' },
  savedPill: { color: c.yellow, backgroundColor: 'rgba(255,196,0,0.13)', fontSize: 11, fontWeight: '900', borderWidth: 1, borderColor: 'rgba(255,196,0,.20)', borderRadius: 999, paddingHorizontal: 9, paddingVertical: 5, overflow: 'hidden' },
  bulkRow: { flexDirection: 'row', direction: 'rtl', justifyContent: 'flex-start', gap: 8, marginBottom: 10 },
  bulkBtn: { borderWidth: 1, borderColor: 'rgba(255,196,0,0.24)', borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7, backgroundColor: 'rgba(255,196,0,0.08)' },
  bulkText: { color: c.yellowSoft, fontSize: 12, fontWeight: '900' },
  wrap: { flexDirection: 'row', direction: 'rtl', justifyContent: 'flex-start', flexWrap: 'wrap', gap: 8 },
  inputRow: { flexDirection: 'row', direction: 'rtl', gap: 8, marginTop: 10 },
  daysSlider: { marginTop: 6, paddingTop: 8, paddingBottom: 2, direction: 'ltr' },
  daysTrack: { position: 'absolute', left: 13, right: 13, top: 18, height: 8, borderRadius: 999, backgroundColor: 'rgba(255,196,0,0.16)', overflow: 'hidden' },
  daysFill: { height: '100%', backgroundColor: c.yellow, borderRadius: 999 },
  daysTicks: { flexDirection: 'row', direction: 'ltr', justifyContent: 'space-between', alignItems: 'flex-start' },
  dayTickTouch: { width: 28, alignItems: 'center', justifyContent: 'flex-start' },
  dayDot: { width: 18, height: 18, borderRadius: 999, borderWidth: 2, borderColor: 'rgba(255,196,0,0.32)', backgroundColor: c.card },
  dayDotOn: { borderColor: c.yellow, backgroundColor: c.yellow },
  dayLabel: { marginTop: 7, color: c.muted, fontSize: 11.5, fontWeight: '900', textAlign: 'center' },
  dayLabelOn: { color: c.yellowSoft },
  input: { flex: 1, height: 45, borderRadius: 14, borderWidth: 1, borderColor: c.border, color: c.text, backgroundColor: c.inputBg, paddingHorizontal: 12, textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', fontWeight: '700' },
  addBtn: { borderRadius: 14, backgroundColor: c.yellow, paddingHorizontal: 15, alignItems: 'center', justifyContent: 'center' },
  addText: { color: c.textOnYellow, fontWeight: '900' },
  sourceGroup: { marginTop: 10, borderTopWidth: 1, borderTopColor: c.border, paddingTop: 10 },
  sourceGroupHead: { flexDirection: 'row', direction: 'rtl', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 },
  sourceGroupTitle: { color: c.text, fontSize: 15, fontWeight: '900', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl' },
  sourceGroupCount: { color: c.yellowSoft, fontSize: 12, fontWeight: '900' },
  sourceRow: { borderTopWidth: 1, borderTopColor: c.subtleBorder, paddingVertical: 12, flexDirection: 'row', direction: 'rtl', justifyContent: 'space-between', alignItems: 'center', gap: 12 },
  sourceRowOn: { backgroundColor: 'rgba(255,196,0,0.04)' },
  sourceRowLabel: { flex: 1, flexDirection: 'row', direction: 'rtl', alignItems: 'center', gap: 9, minWidth: 0 },
  sourceMiniImage: { width: 24, height: 24, borderRadius: 999, backgroundColor: 'transparent', borderWidth: 0 },
  sourceMiniFallback: { width: 24, height: 24, borderRadius: 8, backgroundColor: c.faint, alignItems: 'center', justifyContent: 'center' },
  sourceMiniFallbackText: { color: c.yellow, fontSize: 10, fontWeight: '900' },
  sourceRowName: { color: c.text, fontSize: 14, fontWeight: '800', textAlign: RTL_TEXT_ALIGN, flexShrink: 1, writingDirection: 'rtl' },
  sourceRowNameOn: { color: c.yellowSoft },
  languageDropdown: { maxHeight: 460, marginTop: 8, borderWidth: 1, borderColor: c.border, borderRadius: 16, backgroundColor: c.surfaceSoft, overflow: 'hidden' },
  languageDropdownAbove: { marginTop: 0, marginBottom: 8 },
  languageOption: { minHeight: 44, paddingHorizontal: 12, paddingVertical: 9, borderTopWidth: 1, borderTopColor: c.border, flexDirection: 'row', direction: 'rtl', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  languageOptionOn: { backgroundColor: 'rgba(255,196,0,0.11)' },
  languageOptionCode: { width: 48, height: 24, lineHeight: 24, borderRadius: 999, overflow: 'hidden', textAlign: 'center', color: c.yellowSoft, backgroundColor: c.yellowBg, fontSize: 10.5, fontWeight: '900' },
  languageOptionCodeOn: { color: c.textOnYellow, backgroundColor: c.yellow },
  languageOptionName: { flex: 1, color: c.text, fontSize: 14.5, fontWeight: '800', textAlign: 'left', writingDirection: 'ltr' },
  languageOptionRtl: { textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl' },
  languageOptionNameOn: { color: c.yellowSoft },
  switchText: { color: c.yellowSoft, fontSize: 12, fontWeight: '900' },
  switchTrack: { width: 42, height: 24, borderRadius: 999, backgroundColor: c.faint, padding: 3, justifyContent: 'center', alignItems: 'flex-start' },
  switchTrackOn: { backgroundColor: c.yellow, alignItems: 'flex-end' },
  switchKnob: { width: 18, height: 18, borderRadius: 999, backgroundColor: '#fff' },
  switchKnobOn: { backgroundColor: c.textOnYellow },
  about: { color: c.secondary, textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', lineHeight: 21, marginTop: 12, fontWeight: '600' },
  moreHead: { flexDirection: 'row', direction: 'rtl', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 12 },
  moreHeadText: { flex: 1, alignItems: 'stretch', alignSelf: 'stretch' },
  moreHeadSub: { width: '100%', color: c.muted, fontSize: 13, fontWeight: '700', lineHeight: 18, textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', marginTop: 5 },
  moreBack: { borderWidth: 1, borderColor: 'rgba(255,196,0,0.24)', borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7, backgroundColor: 'rgba(255,196,0,0.08)' },
  moreBackText: { color: c.yellowSoft, fontSize: 12, fontWeight: '900' },
  moreList: { gap: 10 },
  moreRow: { borderWidth: 1, borderColor: c.border, borderRadius: 18, backgroundColor: c.surface, paddingHorizontal: 15, paddingVertical: 14, flexDirection: 'row', direction: 'rtl', alignItems: 'center', justifyContent: 'flex-start', gap: 12 },
  moreRowDisabled: { opacity: 0.46 },
  moreRowText: { flex: 1, alignItems: 'stretch', alignSelf: 'stretch', minWidth: 0 },
  moreTitle: { width: '100%', color: c.text, fontSize: 16, fontWeight: '900', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl' },
  moreSub: { width: '100%', color: c.muted, fontSize: 12.5, fontWeight: '700', lineHeight: 17, textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', marginTop: 4 },
  moreArrow: { color: c.yellow, fontSize: 28, fontWeight: '800', lineHeight: 30 },
  shareActionIcon: { width: 38, height: 38, borderRadius: 14, borderWidth: 1.5, borderColor: 'rgba(255,196,0,0.55)', backgroundColor: 'rgba(255,196,0,0.14)', alignItems: 'center', justifyContent: 'center', shadowColor: c.yellow, shadowOpacity: 0.16, shadowRadius: 10, shadowOffset: { width: 0, height: 0 }, elevation: 4 },
  shareActionImage: { width: 27, height: 27, borderRadius: 9 },
  aboutContent: { borderWidth: 1, borderColor: c.border, borderRadius: 20, backgroundColor: c.surface, padding: 16 },
  moreSectionTitle: { color: c.text, fontSize: 17, fontWeight: '900', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', marginTop: 14, marginBottom: 2 },
  translationNote: { color: c.secondary, textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', lineHeight: 20, marginTop: 12, fontWeight: '700' },
  searchInput: { height: 50, borderRadius: 16, borderWidth: 1, borderColor: c.border, backgroundColor: c.inputBg, color: c.text, paddingHorizontal: 14, textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', fontSize: 16, fontWeight: '800', marginBottom: 10 },
  empty: { color: c.muted, textAlign: 'center', marginTop: 34, fontWeight: '800' },
  error: { color: c.red, textAlign: RTL_TEXT_ALIGN, marginTop: 18, fontWeight: '800' },
  languageLoadingOverlay: { position: 'absolute', left: 18, right: 18, top: '34%', zIndex: 120, borderRadius: 24, paddingVertical: 26, paddingHorizontal: 18, borderWidth: 1, borderColor: c.border, backgroundColor: c.card, alignItems: 'center', justifyContent: 'center', shadowColor: c.shadow, shadowOpacity: 0.26, shadowRadius: 22, elevation: 18 },
  languageLoadingTitle: { color: c.text, fontSize: 20, fontWeight: '900', marginTop: 12, textAlign: 'center' },
  languageLoadingText: { color: c.secondary, fontSize: 13.5, lineHeight: 20, fontWeight: '800', marginTop: 8, textAlign: 'center' },
  nav: { position: 'absolute', left: 0, right: 0, bottom: 0, borderTopWidth: 1, borderTopColor: c.border, borderTopLeftRadius: 18, borderTopRightRadius: 18, backgroundColor: c.bottom, flexDirection: 'row', direction: 'ltr', alignItems: 'center', justifyContent: 'space-around', paddingTop: 6, shadowColor: c.shadow, shadowOpacity: 0.22, shadowRadius: 18, elevation: 12 },
  navButton: { flex: 1, alignItems: 'center', justifyContent: 'center', minWidth: 0 },
  navActive: {},
  navIcon: { color: c.iconMuted, fontSize: 28, fontWeight: '800', lineHeight: 30 },
  navLogoBadge: { width: 36, height: 36, borderRadius: 14, backgroundColor: 'rgba(255,196,0,0.14)', borderWidth: 1.5, borderColor: 'rgba(255,196,0,0.38)', alignItems: 'center', justifyContent: 'center' },
  navLogoBadgeActive: { borderColor: c.yellow, shadowColor: c.yellow, shadowOpacity: 0.22, shadowRadius: 12, shadowOffset: { width: 0, height: 0 }, elevation: 5 },
  navLogo: { width: 27, height: 27, borderRadius: 9 },
  navText: { display: 'none' },
  navTextActive: { color: c.yellow },
});
}
let styles = createStyles(appColors);
