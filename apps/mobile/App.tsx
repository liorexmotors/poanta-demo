import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  ActivityIndicator,
  FlatList,
  Image,
  I18nManager,
  Linking,
  Platform,
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
type Prefs = { topics: string[]; sources: string[]; days: number; feedFilter: 'all' | 'unread' };

const DEFAULT_TOPICS = ['ביטחון', 'פוליטיקה', 'אקטואליה בעולם', 'כלכלה', 'רכב', 'טכנולוגיה', 'צרכנות', 'תרבות', 'ספורט', 'בריאות'];
const APP_SHARE_TEXT = 'מצאתי אפליקציית חדשות מעולה — Poenta.\nחדשות בעברית עם תקציר ברור, הקשר והפואנטה.\nhttps://poenta.app/';
const POENTA_LOGO = require('./assets/poenta-logo.png');
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

function SourceIcon({ name, item, small = false }: { name: string; item?: FeedItem; small?: boolean }) {
  const icon = faviconForSource(name, item);
  if (small && icon) return <Image source={{ uri: icon }} style={styles.sourceMiniImage as any} fadeDuration={0} />;
  if (small) return <View style={styles.sourceMiniFallback}><Text style={styles.sourceMiniFallbackText}>{name.slice(0, 1) || 'P'}</Text></View>;
  if (icon) return <Image source={{ uri: icon }} style={styles.sourceIconImage as any} fadeDuration={0} />;
  return <View style={styles.sourceIconFallback}><Text style={styles.sourceIconFallbackText}>{name.slice(0, 1) || 'P'}</Text></View>;
}

type IconName = 'bookmark' | 'share' | 'breaking' | 'settings' | 'search';
function WebIcon({ name, active = false, size = 28 }: { name: IconName; active?: boolean; size?: number }) {
  const color = active ? appColors.yellow : appColors.iconMuted;
  const fill = active && (name === 'breaking' || name === 'search') ? color : 'none';
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
  items.forEach(item => {
    const explicit = item.semanticClusterKey || item.storyClusterKey || item.clusterKey || item.dedupeKey;
    const match = explicit
      ? out.find(row => (row.semanticClusterKey || row.storyClusterKey || row.clusterKey || row.dedupeKey) === explicit && sourceName(row) !== sourceName(item))
      : out.find(row => sourceName(row) !== sourceName(item) && nearDuplicate(item, row));
    if (!match) out.push(item);
  });
  return out;
}

function allTopics(items: FeedItem[]) {
  return [...new Set([...DEFAULT_TOPICS, ...items.map(topicFor)])].filter(Boolean);
}

function allSources(items: FeedItem[]) {
  const defaults = ['וואלה', 'ynet', 'גלובס', 'הארץ', 'ישראל היום', 'מעריב', 'דה מרקר', 'N12', 'BBC', 'Sky News', 'CNN', 'Reuters'];
  return [...new Set([...items.map(sourceName), ...defaults])].filter(Boolean).sort((a, b) => a.localeCompare(b, 'he'));
}


function Chip({ label, active, onPress, count }: { label: string; active: boolean; onPress: () => void; count?: number }) {
  return <TouchableOpacity style={[styles.chip, active && styles.chipActive]} onPress={onPress} activeOpacity={0.82}>
    <Text style={[styles.chipText, active && styles.chipTextActive]} numberOfLines={1}>{label}</Text>
    {typeof count === 'number' && <Text style={[styles.chipCount, active && styles.chipCountActive]}>{count}</Text>}
  </TouchableOpacity>;
}

function SourceThumb({ item }: { item: FeedItem }) {
  if (item.imageUrl) return <Image source={{ uri: item.imageUrl }} style={styles.image as any} resizeMode="cover" fadeDuration={0} />;
  const label = sourceName(item).slice(0, 2) || 'P';
  return <View style={styles.placeholder}><Text style={styles.placeholderText}>{label}</Text></View>;
}

function ArticleCard({ item, index, saved, onSave, onOpen }: { item: FeedItem; index: number; saved: boolean; onSave: () => void; onOpen: () => void }) {
  const shareText = `${displayHeadline(item)}\n${item.sourceUrl || 'https://poenta.app/'}`;
  const openSource = () => { onOpen(); if (item.sourceUrl) Linking.openURL(item.sourceUrl).catch(() => null); };
  const share = () => Linking.openURL(`https://wa.me/?text=${encodeURIComponent(shareText)}`).catch(() => null);
  return <View style={[styles.card, index < 3 && styles.unreadCard]}>
    <View style={styles.metaRow}>
      <View style={styles.metaActions}>
        <TouchableOpacity onPress={onSave} style={styles.iconAction} accessibilityLabel={saved ? 'הסר משמור' : 'שמור'}><WebIcon name="bookmark" active={saved} size={15} /></TouchableOpacity>
        <TouchableOpacity onPress={share} style={styles.iconAction} accessibilityLabel="שתף"><WebIcon name="share" active={false} size={15} /></TouchableOpacity>
        <Text style={styles.star}>✧</Text>
        <Text style={styles.catText}>{topicFor(item)}</Text>
      </View>
      <Text style={styles.time}>{timeLabel(item, index)}</Text>
    </View>
    <View style={styles.heroBox}>
      <SourceThumb item={item} />
      <View style={styles.heroShade} />
      <View style={styles.headlineWrap}><Text style={styles.headlineText}>{displayHeadline(item)}</Text></View>
    </View>
    {!!summaryFor(item) && <Text style={styles.summary}>{summaryFor(item)}</Text>}
    {!!item.takeaway && <View style={styles.takeawayBox}><Text style={styles.takeaway}>■ {String(item.takeaway).replace(/^💡\s*/, '')}</Text></View>}
    <TouchableOpacity onPress={openSource} activeOpacity={item.sourceUrl ? 0.78 : 1} accessibilityLabel="פתח את כתבת המקור">
      <View style={styles.sourceBox}>
        <View style={styles.sourceAccent} />
        <View style={styles.sourceHead}>
          <Text style={styles.sourceLabel}>כותרת המקור</Text>
          <View style={styles.sourceBrand}><SourceIcon name={sourceName(item)} item={item} /><Text style={styles.sourceNameText}>{sourceName(item)}</Text></View>
        </View>
        <Text style={styles.sourceText}>{String(item.originalTitle || sourceName(item))}</Text>
      </View>
    </TouchableOpacity>
  </View>;
}

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

function BreakingCard({ item, index }: { item: FeedItem; index: number }) {
  return <View style={[styles.card, styles.breakingCard]}>
    <View style={styles.breakingMetaRow}>
      <BreakingSourceLinks item={item} />
      <Text style={styles.time}>{timeLabel(item, index)}</Text>
    </View>
    <Text style={styles.breakingHeadline}>{displayHeadline(item)}</Text>
  </View>;
}

function NavButton({ label, icon, active, onPress, logo }: { label: string; icon?: IconName; active: boolean; onPress: () => void; logo?: boolean }) {
  return <TouchableOpacity style={styles.navButton} onPress={onPress} accessibilityLabel={label}>
    {logo ? <View style={[styles.navLogoBadge, active && styles.navLogoBadgeActive]}><Image source={POENTA_NAV_ICON} style={styles.navLogo as any} /></View> : icon ? <WebIcon name={icon} active={active} size={28} /> : null}
  </TouchableOpacity>;
}

function PoentaApp() {
  const colorScheme = useColorScheme();
  const insets = useSafeAreaInsets();
  const topInset = Math.max(insets.top, 18);
  const bottomInset = Math.max(insets.bottom, 10);
  const topbarHeight = 150 + topInset;
  const navHeight = 58 + bottomInset;
  const [items, setItems] = useState<FeedItem[]>([]);
  const [breaking, setBreaking] = useState<FeedItem[]>([]);
  const [view, setView] = useState<ViewMode>('home');
  const [moreScreen, setMoreScreen] = useState<MoreScreen>('menu');
  const [appearance, setAppearance] = useState<'dark' | 'light' | 'system'>('system');
  const [activeFilter, setActiveFilter] = useState('all');
  const [savedKeys, setSavedKeys] = useState<string[]>([]);
  const [readKeys, setReadKeys] = useState<string[]>([]);
  const [search, setSearch] = useState('');
  const [customTopic, setCustomTopic] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<Prefs>({ topics: DEFAULT_TOPICS.slice(0, 7), sources: [], days: 3, feedFilter: 'all' });
  const storageReady = useRef(false);
  const viewRef = useRef<ViewMode>('home');
  const readKeysRef = useRef<string[]>([]);
  const readFlushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isLight = appearance === 'light' || (appearance === 'system' && colorScheme === 'light');
  const colors = isLight ? LIGHT_COLORS : DARK_COLORS;
  appColors = colors;
  styles = useMemo(() => createStyles(colors), [colors]);

  const knownTopics = useMemo(() => allTopics(items), [items]);
  const knownSources = useMemo(() => allSources([...items, ...breaking]), [items, breaking]);
  const savedKeySet = useMemo(() => new Set(savedKeys), [savedKeys]);
  const readKeySet = useMemo(() => new Set(readKeys), [readKeys]);
  const prefTopicSet = useMemo(() => new Set(prefs.topics), [prefs.topics]);
  const prefSourceSet = useMemo(() => new Set(prefs.sources.length ? prefs.sources : knownSources), [prefs.sources, knownSources]);
  const savedItems = useMemo(() => items.filter(item => savedKeySet.has(itemKey(item))), [items, savedKeySet]);

  useEffect(() => { viewRef.current = view; }, [view]);
  useEffect(() => { readKeysRef.current = readKeys; }, [readKeys]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [prefsRaw, savedRaw, readRaw, appearanceRaw, feedRaw, breakingRaw, syncRaw] = await Promise.all([
          AsyncStorage.getItem(STORAGE_KEYS.prefs),
          AsyncStorage.getItem(STORAGE_KEYS.saved),
          AsyncStorage.getItem(STORAGE_KEYS.read),
          AsyncStorage.getItem(STORAGE_KEYS.appearance),
          AsyncStorage.getItem(STORAGE_KEYS.feedCache),
          AsyncStorage.getItem(STORAGE_KEYS.breakingCache),
          AsyncStorage.getItem(STORAGE_KEYS.lastSync),
        ]);
        if (!alive) return;
        if (prefsRaw) {
          const parsed = JSON.parse(prefsRaw) as Partial<Prefs>;
          setPrefs(prev => ({
            ...prev,
            ...parsed,
            topics: Array.isArray(parsed.topics) ? parsed.topics : prev.topics,
            sources: Array.isArray(parsed.sources) ? parsed.sources : prev.sources,
            days: typeof parsed.days === 'number' ? parsed.days : prev.days,
            feedFilter: parsed.feedFilter === 'unread' ? 'unread' : 'all',
          }));
        }
        if (savedRaw) setSavedKeys(JSON.parse(savedRaw).filter((x: unknown) => typeof x === 'string').slice(0, 500));
        if (readRaw) setReadKeys(JSON.parse(readRaw).filter((x: unknown) => typeof x === 'string').slice(0, 1200));
        if (appearanceRaw === 'dark' || appearanceRaw === 'light' || appearanceRaw === 'system') setAppearance(appearanceRaw);
        if (feedRaw) {
          const cachedFeed = JSON.parse(feedRaw);
          if (Array.isArray(cachedFeed)) setItems(cachedFeed);
        }
        if (breakingRaw) {
          const cachedBreaking = JSON.parse(breakingRaw);
          if (Array.isArray(cachedBreaking)) setBreaking(dedupeItems(cachedBreaking));
        }
        if (syncRaw) setLastSyncedAt(syncRaw);
      } catch {
        // Keep the app usable if device storage contains invalid stale data.
      } finally {
        storageReady.current = true;
      }
    })();
    return () => { alive = false; };
  }, []);

  useEffect(() => { if (storageReady.current) AsyncStorage.setItem(STORAGE_KEYS.prefs, JSON.stringify(prefs)).catch(() => null); }, [prefs]);
  useEffect(() => { if (storageReady.current) AsyncStorage.setItem(STORAGE_KEYS.saved, JSON.stringify(savedKeys.slice(-500))).catch(() => null); }, [savedKeys]);
  useEffect(() => { if (storageReady.current) AsyncStorage.setItem(STORAGE_KEYS.read, JSON.stringify(readKeys.slice(-1200))).catch(() => null); }, [readKeys]);
  useEffect(() => { if (storageReady.current) AsyncStorage.setItem(STORAGE_KEYS.appearance, appearance).catch(() => null); }, [appearance]);

  const loadAll = async () => {
    setRefreshing(true);
    setError(null);
    try {
      const [feed, breakingFeed] = await Promise.all([fetchFeed(), fetchBreakingFeed()]);
      const feedItems = Array.isArray(feed.items) ? feed.items : [];
      const breakingItems = Array.isArray(breakingFeed.items) ? breakingFeed.items : [];
      setItems(feedItems);
      setBreaking(dedupeItems(breakingItems));
      const syncStamp = new Date().toISOString();
      setLastSyncedAt(syncStamp);
      AsyncStorage.multiSet([
        [STORAGE_KEYS.feedCache, JSON.stringify(feedItems.slice(0, 300))],
        [STORAGE_KEYS.breakingCache, JSON.stringify(breakingItems.slice(0, 150))],
        [STORAGE_KEYS.lastSync, syncStamp],
      ]).catch(() => null);
      setPrefs(prev => ({
        ...prev,
        sources: prev.sources.length ? [...new Set([...prev.sources, ...allSources(feedItems).filter(src => !prev.sources.includes(src)).slice(0, 0)])] : allSources([...feedItems, ...breakingItems]),
        topics: prev.topics.length ? prev.topics : allTopics(feedItems).slice(0, 7),
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'שגיאה בטעינת הנתונים');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => { loadAll(); }, []);
  useEffect(() => () => { if (readFlushTimerRef.current) clearTimeout(readFlushTimerRef.current); }, []);

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
      const text = normalizeText([displayHeadline(item), summaryFor(item), item.takeaway, topicFor(item), sourceName(item)].join(' '));
      return words.some(w => text.includes(w));
    })).slice(0, 40);
  }, [search, items, savedItems]);

  const topicCounts = useMemo(() => {
    const counts: Record<string, number> = { all: visibleMain.length };
    items.filter((item, index) => prefSourceSet.has(sourceName(item)) && withinDays(item, index, prefs.days)).forEach(item => {
      const t = topicFor(item);
      counts[t] = (counts[t] || 0) + 1;
    });
    return counts;
  }, [items, prefSourceSet, prefs.days, visibleMain.length]);

  const breakingSources = useMemo(() => [...new Set(breaking.flatMap(item => item.sources?.length ? item.sources : [sourceName(item)]))].sort((a, b) => a.localeCompare(b, 'he')), [breaking]);

  function toggleSaved(item: FeedItem) {
    const key = itemKey(item);
    setSavedKeys(prev => prev.includes(key) ? prev.filter(x => x !== key) : [...prev, key]);
  }

  function markRead(item: FeedItem) {
    const key = itemKey(item);
    setReadKeys(prev => prev.includes(key) ? prev : [...prev, key]);
  }

  function toggleTopic(topic: string) {
    setPrefs(prev => ({ ...prev, topics: prev.topics.includes(topic) ? prev.topics.filter(t => t !== topic) : [...prev.topics, topic] }));
    if (activeFilter !== 'all' && activeFilter === topic) setActiveFilter('all');
  }

  function toggleSource(source: string) {
    setPrefs(prev => {
      const current = prev.sources.filter(s => s !== '__NONE__');
      return { ...prev, sources: current.includes(source) ? current.filter(s => s !== source) : [...current, source] };
    });
    if (activeFilter !== 'all' && activeFilter === source) setActiveFilter('all');
  }

  function switchView(next: ViewMode) {
    setView(next);
    if (next !== 'more') setMoreScreen('menu');
    setActiveFilter('all');
  }

  const renderTabs = () => {
    const tabs = view === 'breaking' ? breakingSources : knownTopics;
    return <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.tabsScroll} contentContainerStyle={styles.tabs} keyboardShouldPersistTaps="always" nestedScrollEnabled directionalLockEnabled>
      <Chip label="הכל" active={activeFilter === 'all'} onPress={() => setActiveFilter('all')} count={view === 'breaking' ? visibleBreaking.length : topicCounts.all} />
      {tabs.map(t => <Chip key={t} label={t} active={activeFilter === t} onPress={() => setActiveFilter(t)} count={view === 'breaking' ? breaking.filter(i => sourceName(i) === t || i.sources?.includes(t)).length : topicCounts[t] || 0} />)}
    </ScrollView>;
  };

  const MoreBack = ({ to = 'menu' as MoreScreen }: { to?: MoreScreen }) => <TouchableOpacity style={styles.moreBack} onPress={() => setMoreScreen(to)}><Text style={styles.moreBackText}>חזרה</Text></TouchableOpacity>;

  const MoreRow = ({ title, subtitle, onPress, disabled = false, icon }: { title: string; subtitle: string; onPress?: () => void; disabled?: boolean; icon?: 'share' | 'arrow' }) => <TouchableOpacity style={[styles.moreRow, disabled && styles.moreRowDisabled]} onPress={onPress} activeOpacity={disabled ? 1 : 0.82}>
    <View style={styles.moreRowText}><Text style={styles.moreTitle}>{title}</Text><Text style={styles.moreSub}>{subtitle}</Text></View>
    {icon === 'share' ? <View style={styles.shareActionIcon}><Image source={POENTA_NAV_ICON} style={styles.shareActionImage as any} /></View> : <Text style={styles.moreArrow}>›</Text>}
  </TouchableOpacity>;

  const renderMore = () => {
    if (moreScreen === 'settings') return <View style={styles.panel}>
      <View style={styles.moreHead}><MoreBack /><View style={styles.moreHeadText}><Text style={styles.settingsTitle}>הגדרות</Text><Text style={styles.moreHeadSub}>התאמה אישית של חוויית השימוש.</Text></View></View>
      <View style={styles.moreList}><MoreRow title="מצב תצוגה" subtitle="כהה, בהיר או לפי מערכת" onPress={() => setMoreScreen('appearance')} /></View>
    </View>;
    if (moreScreen === 'appearance') return <View style={styles.panel}>
      <View style={styles.moreHead}><MoreBack to="settings" /><View style={styles.moreHeadText}><Text style={styles.settingsTitle}>מצב תצוגה</Text><Text style={styles.moreHeadSub}>בחר איך Poenta תיראה אצלך.</Text></View><Text style={styles.savedPill}>נשמר</Text></View>
      <View style={styles.wrap}>{[
        { code: 'dark' as const, name: 'כהה' }, { code: 'light' as const, name: 'בהיר' }, { code: 'system' as const, name: 'לפי מערכת' },
      ].map(o => <Chip key={o.code} label={o.name} active={appearance === o.code} onPress={() => setAppearance(o.code)} />)}</View>
      <Text style={styles.translationNote}>“לפי מערכת” מחליף אוטומטית בין לייט לדרק לפי הגדרת המכשיר.</Text>
    </View>;
    if (moreScreen === 'about') return <View style={styles.panel}>
      <View style={styles.moreHead}><MoreBack /><View style={styles.moreHeadText}><Text style={styles.settingsTitle}>אודות Poenta</Text><Text style={styles.moreHeadSub}>מה Poenta עושה ולמה היא נבנתה.</Text></View></View>
      <View style={styles.aboutContent}>
        <Text style={styles.about}>Poenta נבנתה בשביל אנשים שרוצים להבין מהר מה באמת קורה — בלי לבזבז זמן על כותרות מטעות, קליקבייט וכתבות ארוכות.</Text>
        <Text style={styles.about}>האפליקציה מרכזת חדשות ממגוון מקורות ומזקקת כל ידיעה ל־3 דברים בלבד: הכותרת, התמצית והפואנטה.</Text>
        <Text style={styles.moreSectionTitle}>מה מיוחד ב־Poenta?</Text>
        <Text style={styles.about}>• פיד חדשות חכם ומותאם אישית\n• תמצות AI מהיר וברור\n• הסרת קליקבייט ורעש מיותר\n• בחירת תחומי עניין ומקורות מועדפים</Text>
        <Text style={styles.moreSectionTitle}>גרסה</Text><Text style={styles.about}>Poenta Beta v1.0</Text>
      </View>
    </View>;
    if (moreScreen === 'terms') return <View style={styles.panel}>
      <View style={styles.moreHead}><MoreBack /><View style={styles.moreHeadText}><Text style={styles.settingsTitle}>תנאי שימוש</Text><Text style={styles.moreHeadSub}>המסמך המשפטי לשימוש ב־Poenta.</Text></View></View>
      <View style={styles.aboutContent}><Text style={styles.about}>עודכן לאחרונה: 24.05.2026</Text><Text style={styles.about}>השימוש באפליקציה, באתר ובשירותי Poenta כפוף לתנאי השימוש. Poenta היא פלטפורמת תוכן מבוססת AI המרכזת, מנתחת ומתמצתת מידע ממקורות חיצוניים.</Text><Text style={styles.about}>השירות ניתן “כפי שהוא”. כל זכויות הקניין הרוחני באפליקציה שייכות ל־Poenta.</Text></View>
    </View>;
    if (moreScreen === 'privacy') return <View style={styles.panel}>
      <View style={styles.moreHead}><MoreBack /><View style={styles.moreHeadText}><Text style={styles.settingsTitle}>מדיניות פרטיות</Text><Text style={styles.moreHeadSub}>איך Poenta מתייחסת למידע ולהעדפות המשתמש.</Text></View></View>
      <View style={styles.aboutContent}><Text style={styles.about}>Poenta מכבדת את פרטיות המשתמשים ואינה מוכרת מידע אישי למפרסמים.</Text><Text style={styles.about}>המידע משמש להתאמה אישית של הפיד, שיפור השירות וניתוח שימוש בסיסי.</Text><Text style={styles.about}>יצירת קשר: support@poenta.app</Text></View>
    </View>;
    if (moreScreen === 'contact') return <View style={styles.panel}>
      <View style={styles.moreHead}><MoreBack /><View style={styles.moreHeadText}><Text style={styles.settingsTitle}>צור קשר</Text><Text style={styles.moreHeadSub}>פניות, הצעות ושאלות על Poenta.</Text></View></View>
      <View style={styles.aboutContent}><Text style={styles.about}>אפשר לפנות אלינו בכתובת:</Text><Text style={styles.moreSectionTitle}>support@poenta.app</Text></View>
    </View>;
    return <View style={styles.panel}>
      <View style={styles.moreHead}><View style={styles.moreHeadText}><Text style={styles.title}>עוד</Text><Text style={styles.moreHeadSub}>הגדרות ומידע נוסף על Poenta.</Text></View></View>
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
    <Text style={styles.title}>הגדרות Poenta</Text>
    <Text style={styles.subtitle}>תחומי עניין, מקורות וסינון אישי — כמו בגרסת ה־web שפיתחנו.</Text>

    <View style={styles.settingsCard}>
      <View style={styles.settingsHead}><Text style={styles.settingsTitle}>תחומי עניין</Text><Text style={styles.savedPill}>נשמר במכשיר</Text></View>
      <View style={styles.bulkRow}>
        <TouchableOpacity style={styles.bulkBtn} onPress={() => setPrefs(prev => ({ ...prev, topics: knownTopics }))}><Text style={styles.bulkText}>סמן הכל</Text></TouchableOpacity>
        <TouchableOpacity style={styles.bulkBtn} onPress={() => setPrefs(prev => ({ ...prev, topics: [] }))}><Text style={styles.bulkText}>בטל הכל</Text></TouchableOpacity>
      </View>
      <View style={styles.wrap}>{knownTopics.map(t => <Chip key={t} label={t} active={prefs.topics.includes(t)} onPress={() => toggleTopic(t)} />)}</View>
      <View style={styles.inputRow}>
        <TextInput style={styles.input} value={customTopic} onChangeText={setCustomTopic} placeholder="תחום אישי, למשל מיצרי הורמוז" placeholderTextColor={colors.muted} />
        <TouchableOpacity style={styles.addBtn} onPress={() => { const t = customTopic.trim().slice(0, 22); if (t) { setPrefs(prev => ({ ...prev, topics: [...new Set([...prev.topics, t])] })); setCustomTopic(''); } }}><Text style={styles.addText}>הוסף</Text></TouchableOpacity>
      </View>
    </View>

    <View style={styles.settingsCard}>
      <View style={styles.settingsHead}><Text style={styles.settingsTitle}>מקורות</Text><Text style={styles.savedPill}>{prefs.sources.includes('__NONE__') ? 0 : (prefs.sources.filter(s => s !== '__NONE__').length || knownSources.length)}/{knownSources.length}</Text></View>
      <View style={styles.bulkRow}>
        <TouchableOpacity style={styles.bulkBtn} onPress={() => setPrefs(prev => ({ ...prev, sources: knownSources }))}><Text style={styles.bulkText}>סמן הכל</Text></TouchableOpacity>
        <TouchableOpacity style={styles.bulkBtn} onPress={() => setPrefs(prev => ({ ...prev, sources: ['__NONE__'] }))}><Text style={styles.bulkText}>בטל הכל</Text></TouchableOpacity>
      </View>
      {knownSources.map(src => {
        const on = prefSourceSet.has(src);
        return <TouchableOpacity key={src} style={[styles.sourceRow, on && styles.sourceRowOn]} onPress={() => toggleSource(src)}>
          <View style={styles.sourceRowLabel}><SourceIcon name={src} small /><Text style={[styles.sourceRowName, on && styles.sourceRowNameOn]}>{src}</Text></View>
          <View style={[styles.switchTrack, on && styles.switchTrackOn]}><View style={[styles.switchKnob, on && styles.switchKnobOn]} /></View>
        </TouchableOpacity>;
      })}
    </View>

    <View style={styles.settingsCard}>
      <View style={styles.settingsHead}><Text style={styles.settingsTitle}>סינון קריאה</Text><Text style={styles.savedPill}>{prefs.days === 1 ? 'יום אחד' : `${prefs.days} ימים`}</Text></View>
      <View style={styles.daysSlider}>
        <View style={styles.daysTrack}><View style={[styles.daysFill, { width: `${((prefs.days - 1) / 6) * 100}%` }]} /></View>
        <View style={styles.daysTicks}>{[1, 2, 3, 4, 5, 6, 7].map(d => <TouchableOpacity key={d} style={styles.dayTickTouch} onPress={() => setPrefs(prev => ({ ...prev, days: d }))} activeOpacity={0.82}><View style={[styles.dayDot, prefs.days >= d && styles.dayDotOn]} /><Text style={[styles.dayLabel, prefs.days === d && styles.dayLabelOn]}>{d}</Text></TouchableOpacity>)}</View>
      </View>
    </View>

    <View style={styles.settingsCard}>
      <Text style={styles.settingsTitle}>מצב קריאה</Text>
      <View style={styles.wrap}>
        <Chip label="כל הכתבות" active={prefs.feedFilter === 'all'} onPress={() => setPrefs(prev => ({ ...prev, feedFilter: 'all' }))} />
        <Chip label="רק לא נקראו" active={prefs.feedFilter === 'unread'} onPress={() => setPrefs(prev => ({ ...prev, feedFilter: 'unread' }))} count={unreadCount} />
        <TouchableOpacity style={styles.bulkBtn} onPress={() => setReadKeys([])}><Text style={styles.bulkText}>אפס נקראו</Text></TouchableOpacity>
      </View>
    </View>
  </View>;

  const list = view === 'breaking' ? visibleBreaking : view === 'saved' ? savedItems : view === 'search' ? searchResults : visibleMain;
  const unreadCount = visibleMainBase.filter(i => !readKeySet.has(itemKey(i))).length;
  const totalMainCount = visibleMainBase.length;
  const unreadPct = totalMainCount ? Math.max(0, Math.min(100, Math.round((unreadCount / totalMainCount) * 100))) : 0;
  const unreadRatio = totalMainCount ? unreadCount / totalMainCount : 0;
  const unreadMarkerLeftPct = totalMainCount ? Math.max(13, Math.min(86, 13 + (1 - unreadRatio) * 73)) : 13;

  const keyExtractor = useCallback((item: FeedItem, index: number) => `${itemKey(item)}-${index}`, []);
  const renderItem = useCallback(({ item, index }: { item: FeedItem; index: number }) => viewRef.current === 'breaking'
    ? <BreakingCard item={item} index={index} />
    : <ArticleCard item={item} index={index} saved={savedKeySet.has(itemKey(item))} onSave={() => { toggleSaved(item); markRead(item); }} onOpen={() => markRead(item)} />, [savedKeySet]);
  const viewabilityConfig = useRef({ itemVisiblePercentThreshold: 62, minimumViewTime: 450 }).current;
  const onViewableItemsChanged = useRef(({ viewableItems }: { viewableItems: Array<{ item?: FeedItem }> }) => {
    if (viewRef.current !== 'home') return;
    const existing = new Set(readKeysRef.current);
    const nextKeys = viewableItems.map(v => v.item).filter((item): item is FeedItem => !!item).map(itemKey).filter(key => !existing.has(key));
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
      <Text style={styles.title}>חיפוש</Text>
      <Text style={styles.subtitle}>חיפוש חכם בכתבות מהפיד ומהשמורים. אפשר לכתוב רעיון כמו “הופעות רוק”.</Text>
      <TextInput style={styles.searchInput} value={search} onChangeText={setSearch} placeholder="מה לחפש? למשל הופעות רוק" placeholderTextColor={colors.muted} textAlign={RTL_TEXT_ALIGN} autoCorrect={false} autoCapitalize="none" blurOnSubmit={false} returnKeyType="search" />
    </>}

    {view === 'saved' && <>
      <Text style={styles.title}>שמורים</Text>
      <Text style={styles.subtitle}>{savedItems.length ? `${savedItems.length} כתבות שמורות` : 'אפשר לשמור כתבות מהפיד בלחיצה על שמור.'}</Text>
    </>}

    {loading && <ActivityIndicator color={colors.yellow} style={{ marginTop: 28 }} />}
    {error && <Text style={styles.error}>שגיאה בטעינת הפיד: {error}</Text>}
  </>;

  const listEmptyText = view === 'search' && search.trim().length < 2 ? 'הקלד לפחות 2 אותיות לחיפוש.' : 'אין אייטמים להצגה כרגע.';

  return <SafeAreaView style={styles.safe}>
    <StatusBar style={isLight ? "dark" : "light"} />
    <View style={[styles.topbar, { height: topbarHeight, paddingTop: topInset }]}>
      <View style={styles.header}>
        <Image source={POENTA_LOGO} style={styles.logoImage as any} resizeMode="contain" />
        <TouchableOpacity style={styles.topMore} accessibilityLabel="עוד" onPress={() => switchView('more')}><Text style={styles.topMoreText}>☰</Text></TouchableOpacity>
      </View>
      <View style={styles.updates}>
        <TouchableOpacity style={styles.updateTrack} onPress={loadAll} activeOpacity={0.86} accessibilityLabel="רענן פיד">
          <View style={[styles.updateFill, { width: `${unreadPct}%` }]} />
          <Text style={styles.updateText}>מדד החדשים שלך</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[styles.updateTotalPill, prefs.feedFilter === 'all' && styles.updatePillActive]} onPress={() => setPrefs(prev => ({ ...prev, feedFilter: 'all' }))} activeOpacity={0.84} accessibilityLabel="הצג את כל הידיעות">
          <Text style={styles.updatePillText}>{totalMainCount}</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[styles.updatePill, { left: `${unreadMarkerLeftPct}%` }, prefs.feedFilter === 'unread' && styles.updatePillActive]} onPress={() => setPrefs(prev => ({ ...prev, feedFilter: prev.feedFilter === 'unread' ? 'all' : 'unread' }))} activeOpacity={0.84} accessibilityLabel="סנן לחדשים">
          <Text style={styles.updatePillText}>{unreadCount}</Text>
        </TouchableOpacity>
      </View>
      <View style={styles.tabline}>{(view === 'home' || view === 'breaking') && renderTabs()}</View>
    </View>

    {view === 'settings' || view === 'more' ? <ScrollView style={styles.scroll} contentContainerStyle={[styles.content, { paddingTop: topbarHeight + 4, paddingBottom: navHeight + 52 }]} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={loadAll} tintColor={colors.yellow} />} keyboardShouldPersistTaps="handled">
      {view === 'settings' ? renderSettings() : renderMore()}
    </ScrollView> : <FlatList
      key={view === 'breaking' ? 'breaking-list' : view === 'home' ? 'home-list' : view === 'search' ? 'search-list' : 'saved-list'}
      style={styles.scroll}
      contentContainerStyle={[styles.content, { paddingTop: topbarHeight + 4, paddingBottom: navHeight + 52 }]}
      data={loading ? [] : list}
      keyExtractor={keyExtractor}
      renderItem={renderItem}
      ListHeaderComponent={listHeader}
      ListEmptyComponent={!loading ? <Text style={styles.empty}>{listEmptyText}</Text> : null}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={loadAll} tintColor={colors.yellow} />}
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

    <View style={[styles.nav, { height: navHeight, paddingBottom: bottomInset }]}>
      <NavButton label="שמור" icon="bookmark" active={view === 'saved' || savedKeys.length > 0} onPress={() => switchView('saved')} />
      <NavButton label="חיפוש" icon="search" active={view === 'search'} onPress={() => switchView('search')} />
      <NavButton label="הגדרות" icon="settings" active={view === 'settings'} onPress={() => switchView('settings')} />
      <NavButton label="מבזקים" icon="breaking" active={view === 'breaking'} onPress={() => switchView('breaking')} />
      <NavButton label="Poenta" logo active={view === 'home'} onPress={() => switchView('home')} />
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
  breakingHeadline: { color: c.text, fontSize: 21.5, lineHeight: 25, fontWeight: '900', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', direction: 'rtl', alignSelf: 'stretch', letterSpacing: -0.42, marginBottom: 8 },
  summary: { color: c.secondary, fontSize: 14.8, lineHeight: 21.3, fontWeight: '500', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', direction: 'rtl', alignSelf: 'stretch' },
  takeawayBox: { marginTop: 9, paddingTop: 9, borderTopWidth: 1, borderTopColor: c.border },
  takeaway: { color: c.yellowSoft, fontSize: 14, lineHeight: 17.5, fontWeight: '800', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', direction: 'rtl', alignSelf: 'stretch' },
  actionRow: { marginTop: 12, flexDirection: 'row-reverse', gap: 8, alignItems: 'stretch' },
  smallAction: { borderWidth: 1, borderColor: c.faint, borderRadius: 14, backgroundColor: c.surfaceSoft, paddingHorizontal: 10, alignItems: 'center', justifyContent: 'center' },
  smallActionOn: { borderColor: 'rgba(255,196,0,0.42)', backgroundColor: 'rgba(255,196,0,0.13)' },
  smallActionText: { color: c.yellow, fontSize: 12, fontWeight: '900' },
  sourceBox: { width: '100%', alignSelf: 'stretch', position: 'relative', marginTop: 12, marginHorizontal: -1, borderWidth: 1, borderColor: 'rgba(255,196,0,0.26)', borderRadius: 15, backgroundColor: c.sourceBg, paddingHorizontal: 12, paddingTop: 10, paddingBottom: 11, overflow: 'hidden', direction: 'rtl', alignItems: 'stretch' },
  sourceAccent: { position: 'absolute', right: 0, top: 12, bottom: 12, width: 3, borderRadius: 999, backgroundColor: 'rgba(255,196,0,0.74)' },
  sourceHead: { flexDirection: 'row', direction: 'rtl', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 7 },
  sourceLabel: { color: c.yellowSoft, backgroundColor: c.yellowBg, borderRadius: 999, paddingHorizontal: 7, paddingVertical: 4, fontSize: 10.5, fontWeight: '900', overflow: 'hidden', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl' },
  sourceBrand: { flexDirection: 'row', direction: 'rtl', alignItems: 'center', gap: 6, flexShrink: 1, minWidth: 0 },
  sourceNameText: { color: c.secondary, fontSize: 11.5, fontWeight: '900', flexShrink: 1, textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl' },
  sourceIconImage: { width: 22, height: 22, borderRadius: 7, backgroundColor: c.faint },
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
  sourceRow: { borderTopWidth: 1, borderTopColor: c.border, paddingVertical: 12, flexDirection: 'row', direction: 'rtl', justifyContent: 'space-between', alignItems: 'center', gap: 12 },
  sourceRowOn: { backgroundColor: 'rgba(255,196,0,0.04)' },
  sourceRowLabel: { flex: 1, flexDirection: 'row', direction: 'rtl', alignItems: 'center', gap: 9, minWidth: 0 },
  sourceMiniImage: { width: 24, height: 24, borderRadius: 8, backgroundColor: c.faint, borderWidth: 1, borderColor: c.border },
  sourceMiniFallback: { width: 24, height: 24, borderRadius: 8, backgroundColor: c.faint, alignItems: 'center', justifyContent: 'center' },
  sourceMiniFallbackText: { color: c.yellow, fontSize: 10, fontWeight: '900' },
  sourceRowName: { color: c.text, fontSize: 14, fontWeight: '800', textAlign: RTL_TEXT_ALIGN, flexShrink: 1 },
  sourceRowNameOn: { color: c.yellowSoft },
  switchText: { color: c.yellowSoft, fontSize: 12, fontWeight: '900' },
  switchTrack: { width: 42, height: 24, borderRadius: 999, backgroundColor: c.faint, padding: 3, justifyContent: 'center', alignItems: 'flex-start' },
  switchTrackOn: { backgroundColor: c.yellow, alignItems: 'flex-end' },
  switchKnob: { width: 18, height: 18, borderRadius: 999, backgroundColor: '#fff' },
  switchKnobOn: { backgroundColor: c.textOnYellow },
  about: { color: c.secondary, textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', lineHeight: 21, marginTop: 12, fontWeight: '600' },
  moreHead: { flexDirection: 'row', direction: 'rtl', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 12 },
  moreHeadText: { flex: 1, alignItems: 'flex-end' },
  moreHeadSub: { color: c.muted, fontSize: 13, fontWeight: '700', lineHeight: 18, textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', marginTop: 5 },
  moreBack: { borderWidth: 1, borderColor: 'rgba(255,196,0,0.24)', borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7, backgroundColor: 'rgba(255,196,0,0.08)' },
  moreBackText: { color: c.yellowSoft, fontSize: 12, fontWeight: '900' },
  moreList: { gap: 10 },
  moreRow: { borderWidth: 1, borderColor: c.border, borderRadius: 18, backgroundColor: c.surface, paddingHorizontal: 15, paddingVertical: 14, flexDirection: 'row', direction: 'rtl', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  moreRowDisabled: { opacity: 0.46 },
  moreRowText: { flex: 1, alignItems: 'flex-end' },
  moreTitle: { color: c.text, fontSize: 16, fontWeight: '900', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl' },
  moreSub: { color: c.muted, fontSize: 12.5, fontWeight: '700', lineHeight: 17, textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', marginTop: 4 },
  moreArrow: { color: c.yellow, fontSize: 28, fontWeight: '800', lineHeight: 30 },
  shareActionIcon: { width: 38, height: 38, borderRadius: 14, borderWidth: 1.5, borderColor: 'rgba(255,196,0,0.55)', backgroundColor: '#f7f1df', alignItems: 'center', justifyContent: 'center', shadowColor: c.yellow, shadowOpacity: 0.16, shadowRadius: 10, shadowOffset: { width: 0, height: 0 }, elevation: 4 },
  shareActionImage: { width: 27, height: 27, borderRadius: 9 },
  aboutContent: { borderWidth: 1, borderColor: c.border, borderRadius: 20, backgroundColor: c.surface, padding: 16 },
  moreSectionTitle: { color: c.text, fontSize: 17, fontWeight: '900', textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', marginTop: 14, marginBottom: 2 },
  translationNote: { color: c.secondary, textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', lineHeight: 20, marginTop: 12, fontWeight: '700' },
  searchInput: { height: 50, borderRadius: 16, borderWidth: 1, borderColor: c.border, backgroundColor: c.inputBg, color: c.text, paddingHorizontal: 14, textAlign: RTL_TEXT_ALIGN, writingDirection: 'rtl', fontSize: 16, fontWeight: '800', marginBottom: 10 },
  empty: { color: c.muted, textAlign: 'center', marginTop: 34, fontWeight: '800' },
  error: { color: c.red, textAlign: RTL_TEXT_ALIGN, marginTop: 18, fontWeight: '800' },
  nav: { position: 'absolute', left: 0, right: 0, bottom: 0, borderTopWidth: 1, borderTopColor: c.border, borderTopLeftRadius: 18, borderTopRightRadius: 18, backgroundColor: c.bottom, flexDirection: 'row', direction: 'ltr', paddingBottom: 10, justifyContent: 'space-around', shadowColor: c.shadow, shadowOpacity: 0.22, shadowRadius: 30, shadowOffset: { width: 0, height: -14 }, elevation: 20 },
  navButton: { flex: 1, alignItems: 'center', justifyContent: 'center', minWidth: 0 },
  navActive: {},
  navIcon: { color: c.iconMuted, fontSize: 28, fontWeight: '800', lineHeight: 30 },
  navLogoBadge: { width: 36, height: 36, borderRadius: 14, backgroundColor: '#f7f1df', borderWidth: 1.5, borderColor: 'rgba(255,196,0,0.38)', alignItems: 'center', justifyContent: 'center' },
  navLogoBadgeActive: { borderColor: c.yellow, shadowColor: c.yellow, shadowOpacity: 0.22, shadowRadius: 12, shadowOffset: { width: 0, height: 0 }, elevation: 5 },
  navLogo: { width: 27, height: 27, borderRadius: 9 },
  navText: { display: 'none' },
  navTextActive: { color: c.yellow },
});
}
let styles = createStyles(appColors);
