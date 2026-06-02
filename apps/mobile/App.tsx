import { StatusBar } from 'expo-status-bar';
import { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Linking,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import Svg, { Circle, Path } from 'react-native-svg';
import { SafeAreaProvider, useSafeAreaInsets } from 'react-native-safe-area-context';
import { fetchBreakingFeed, fetchFeed } from './src/feed';
import { FeedItem } from './src/types';
import { theme } from './src/theme';

type ViewMode = 'home' | 'breaking' | 'saved' | 'search' | 'settings' | 'more';
type MoreScreen = 'menu' | 'settings' | 'appearance' | 'about' | 'terms' | 'privacy' | 'contact';
type Prefs = { topics: string[]; sources: string[]; days: number; feedFilter: 'all' | 'unread' };

const DEFAULT_TOPICS = ['ביטחון', 'פוליטיקה', 'אקטואליה בעולם', 'כלכלה', 'רכב', 'טכנולוגיה', 'צרכנות', 'תרבות', 'ספורט', 'בריאות'];
const APP_SHARE_TEXT = 'מצאתי אפליקציית חדשות מעולה — Poenta.\nחדשות בעברית עם תקציר ברור, הקשר והפואנטה.\nhttps://poenta.app/';
const POENTA_LOGO = require('./assets/poenta-logo.png');
const POENTA_NAV_ICON = require('./assets/poenta-icon-64.png');

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
  if (icon) return <Image source={{ uri: icon }} style={(small ? styles.sourceMiniImage : styles.sourceIconImage) as any} />;
  return <View style={small ? styles.sourceMiniFallback : styles.sourceIconFallback}><Text style={small ? styles.sourceMiniFallbackText : styles.sourceIconFallbackText}>{name.slice(0, 1) || 'P'}</Text></View>;
}

type IconName = 'bookmark' | 'share' | 'breaking' | 'settings' | 'search';
function WebIcon({ name, active = false, size = 28 }: { name: IconName; active?: boolean; size?: number }) {
  const color = active ? '#FFC400' : 'rgba(255,255,255,0.48)';
  const fill = active && (name === 'bookmark' || name === 'breaking' || name === 'search') ? color : 'none';
  if (name === 'bookmark') return <Svg width={size} height={size} viewBox="0 0 24 24"><Path d="M6 4h12v17l-6-4-6 4V4Z" stroke={color} fill={fill} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" /></Svg>;
  if (name === 'share') return <Svg width={size} height={size} viewBox="0 0 24 24"><Path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7" stroke={color} fill="none" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" /><Path d="M12 16V4" stroke={color} fill="none" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" /><Path d="M7 9l5-5 5 5" stroke={color} fill="none" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" /></Svg>;
  if (name === 'breaking') return <Svg width={size} height={size} viewBox="0 0 24 24"><Path d="M13 2 5 13h6l-1 9 9-13h-6l1-7Z" stroke={color} fill={fill} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" /></Svg>;
  if (name === 'settings') return <Svg width={size} height={size} viewBox="0 0 24 24"><Path d="M6 4v16" stroke={color} strokeWidth={2} strokeLinecap="round" /><Path d="M12 4v16" stroke={color} strokeWidth={2} strokeLinecap="round" /><Path d="M18 4v16" stroke={color} strokeWidth={2} strokeLinecap="round" /><Circle cx="6" cy="9" r="2.15" stroke={color} fill="#050b0f" strokeWidth={2} /><Circle cx="12" cy="15" r="2.15" stroke={color} fill="#050b0f" strokeWidth={2} /><Circle cx="18" cy="7.5" r="2.15" stroke={color} fill="#050b0f" strokeWidth={2} /></Svg>;
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
    <Text style={[styles.chipText, active && styles.chipTextActive]}>{label}</Text>
    {typeof count === 'number' && <Text style={[styles.chipCount, active && styles.chipTextActive]}>{count}</Text>}
  </TouchableOpacity>;
}

function SourceThumb({ item }: { item: FeedItem }) {
  if (item.imageUrl) return <Image source={{ uri: item.imageUrl }} style={styles.image as any} />;
  const label = sourceName(item).slice(0, 2) || 'P';
  return <View style={styles.placeholder}><Text style={styles.placeholderText}>{label}</Text></View>;
}

function ArticleCard({ item, index, saved, onSave }: { item: FeedItem; index: number; saved: boolean; onSave: () => void }) {
  const open = () => { if (item.sourceUrl) Linking.openURL(item.sourceUrl).catch(() => null); };
  return <View style={[styles.card, index < 3 && styles.unreadCard]}>
    <View style={styles.metaRow}>
      <View style={styles.metaActions}>
        <TouchableOpacity onPress={onSave} style={styles.iconAction} accessibilityLabel={saved ? 'הסר משמור' : 'שמור'}><WebIcon name="bookmark" active={saved} size={15} /></TouchableOpacity>
        <TouchableOpacity style={styles.iconAction} accessibilityLabel="שתף"><WebIcon name="share" active={false} size={15} /></TouchableOpacity>
        <Text style={styles.star}>✧</Text>
        <Text style={styles.catText}>{topicFor(item)}</Text>
      </View>
      <Text style={styles.time}>{timeLabel(item, index)}</Text>
    </View>
    <TouchableOpacity onPress={open} activeOpacity={item.sourceUrl ? 0.78 : 1}>
      <View style={styles.heroBox}>
        <SourceThumb item={item} />
        <View style={styles.heroShade} />
        <Text style={styles.headline}>{displayHeadline(item)}</Text>
      </View>
      {!!summaryFor(item) && <Text style={styles.summary}>{summaryFor(item)}</Text>}
      {!!item.takeaway && <View style={styles.takeawayBox}><Text style={styles.takeaway}>■ {String(item.takeaway).replace(/^💡\s*/, '')}</Text></View>}
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

function BreakingCard({ item, index }: { item: FeedItem; index: number }) {
  const open = () => { if (item.sourceUrl) Linking.openURL(item.sourceUrl).catch(() => null); };
  const sources = item.sources?.length ? item.sources.join(' + ') : sourceName(item);
  return <TouchableOpacity style={[styles.card, styles.breakingCard]} onPress={open} activeOpacity={item.sourceUrl ? 0.78 : 1}>
    <View style={styles.metaRow}>
      <View style={styles.cat}><Text style={styles.bolt}>⚡</Text><Text style={styles.catText}>{sources}</Text></View>
      <Text style={styles.time}>{timeLabel(item, index)}</Text>
    </View>
    <Text style={styles.breakingHeadline}>{displayHeadline(item)}</Text>
    {!!summaryFor(item) && <Text style={styles.summary}>{summaryFor(item)}</Text>}
  </TouchableOpacity>;
}

function NavButton({ label, icon, active, onPress, logo }: { label: string; icon?: IconName; active: boolean; onPress: () => void; logo?: boolean }) {
  return <TouchableOpacity style={styles.navButton} onPress={onPress} accessibilityLabel={label}>
    {logo ? <View style={[styles.navLogoBadge, active && styles.navLogoBadgeActive]}><Image source={POENTA_NAV_ICON} style={styles.navLogo as any} /></View> : icon ? <WebIcon name={icon} active={active} size={28} /> : null}
  </TouchableOpacity>;
}

function PoentaApp() {
  const insets = useSafeAreaInsets();
  const topInset = Math.max(insets.top, 18);
  const bottomInset = Math.max(insets.bottom, 10);
  const topbarHeight = 142 + topInset;
  const navHeight = 58 + bottomInset;
  const [items, setItems] = useState<FeedItem[]>([]);
  const [breaking, setBreaking] = useState<FeedItem[]>([]);
  const [view, setView] = useState<ViewMode>('home');
  const [moreScreen, setMoreScreen] = useState<MoreScreen>('menu');
  const [appearance, setAppearance] = useState<'dark' | 'light' | 'system'>('dark');
  const [activeFilter, setActiveFilter] = useState('all');
  const [savedKeys, setSavedKeys] = useState<string[]>([]);
  const [readKeys, setReadKeys] = useState<string[]>([]);
  const [search, setSearch] = useState('');
  const [customTopic, setCustomTopic] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<Prefs>({ topics: DEFAULT_TOPICS.slice(0, 7), sources: [], days: 3, feedFilter: 'all' });

  const knownTopics = useMemo(() => allTopics(items), [items]);
  const knownSources = useMemo(() => allSources([...items, ...breaking]), [items, breaking]);
  const savedItems = useMemo(() => items.filter(item => savedKeys.includes(itemKey(item))), [items, savedKeys]);

  const loadAll = async () => {
    setRefreshing(true);
    setError(null);
    try {
      const [feed, breakingFeed] = await Promise.all([fetchFeed(), fetchBreakingFeed()]);
      const feedItems = Array.isArray(feed.items) ? feed.items : [];
      const breakingItems = Array.isArray(breakingFeed.items) ? breakingFeed.items : [];
      setItems(feedItems);
      setBreaking(dedupeItems(breakingItems));
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

  const visibleMain = useMemo(() => {
    const selectedTopics = new Set(prefs.topics);
    const selectedSources = new Set(prefs.sources.length ? prefs.sources : knownSources);
    const rows = items
      .map((item, index) => ({ item, index, date: itemDate(item, index) }))
      .filter(row => selectedSources.has(sourceName(row.item)))
      .filter(row => selectedTopics.has(topicFor(row.item)))
      .filter(row => withinDays(row.item, row.index, prefs.days))
      .filter(row => activeFilter === 'all' || topicFor(row.item) === activeFilter)
      .filter(row => prefs.feedFilter === 'all' || !readKeys.includes(itemKey(row.item)))
      .sort((a, b) => b.date.getTime() - a.date.getTime())
      .map(row => row.item);
    return dedupeItems(rows);
  }, [items, prefs, knownSources, activeFilter, readKeys]);

  const visibleBreaking = useMemo(() => {
    const selectedSources = new Set(prefs.sources.length ? prefs.sources : knownSources);
    return breaking
      .filter(item => selectedSources.has(sourceName(item)))
      .filter(item => activeFilter === 'all' || sourceName(item) === activeFilter || item.sources?.includes(activeFilter))
      .sort((a, b) => itemDate(b).getTime() - itemDate(a).getTime());
  }, [breaking, prefs.sources, knownSources, activeFilter]);

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
    const selectedSources = new Set(prefs.sources.length ? prefs.sources : knownSources);
    items.filter((item, index) => selectedSources.has(sourceName(item)) && withinDays(item, index, prefs.days)).forEach(item => {
      const t = topicFor(item);
      counts[t] = (counts[t] || 0) + 1;
    });
    return counts;
  }, [items, prefs.sources, prefs.days, knownSources, visibleMain.length]);

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
    setPrefs(prev => ({ ...prev, sources: prev.sources.includes(source) ? prev.sources.filter(s => s !== source) : [...prev.sources, source] }));
    if (activeFilter !== 'all' && activeFilter === source) setActiveFilter('all');
  }

  function switchView(next: ViewMode) {
    setView(next);
    if (next !== 'more') setMoreScreen('menu');
    setActiveFilter('all');
  }

  const renderTabs = () => {
    const tabs = view === 'breaking' ? breakingSources : prefs.topics.filter(t => knownTopics.includes(t));
    return <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tabs}>
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
      <View style={styles.settingsHead}><Text style={styles.settingsTitle}>תחומי עניין</Text><Text style={styles.savedPill}>נשמר בסשן</Text></View>
      <View style={styles.bulkRow}>
        <TouchableOpacity style={styles.bulkBtn} onPress={() => setPrefs(prev => ({ ...prev, topics: knownTopics }))}><Text style={styles.bulkText}>סמן הכל</Text></TouchableOpacity>
        <TouchableOpacity style={styles.bulkBtn} onPress={() => setPrefs(prev => ({ ...prev, topics: [] }))}><Text style={styles.bulkText}>בטל הכל</Text></TouchableOpacity>
      </View>
      <View style={styles.wrap}>{knownTopics.map(t => <Chip key={t} label={t} active={prefs.topics.includes(t)} onPress={() => toggleTopic(t)} />)}</View>
      <View style={styles.inputRow}>
        <TextInput style={styles.input} value={customTopic} onChangeText={setCustomTopic} placeholder="תחום אישי, למשל מיצרי הורמוז" placeholderTextColor="rgba(255,255,255,0.34)" />
        <TouchableOpacity style={styles.addBtn} onPress={() => { const t = customTopic.trim().slice(0, 22); if (t) { setPrefs(prev => ({ ...prev, topics: [...new Set([...prev.topics, t])] })); setCustomTopic(''); } }}><Text style={styles.addText}>הוסף</Text></TouchableOpacity>
      </View>
    </View>

    <View style={styles.settingsCard}>
      <View style={styles.settingsHead}><Text style={styles.settingsTitle}>מקורות</Text><Text style={styles.savedPill}>{prefs.sources.length}/{knownSources.length}</Text></View>
      <View style={styles.bulkRow}>
        <TouchableOpacity style={styles.bulkBtn} onPress={() => setPrefs(prev => ({ ...prev, sources: knownSources }))}><Text style={styles.bulkText}>סמן הכל</Text></TouchableOpacity>
        <TouchableOpacity style={styles.bulkBtn} onPress={() => setPrefs(prev => ({ ...prev, sources: [] }))}><Text style={styles.bulkText}>בטל הכל</Text></TouchableOpacity>
      </View>
      {knownSources.map(src => {
        const on = prefs.sources.includes(src);
        return <TouchableOpacity key={src} style={[styles.sourceRow, on && styles.sourceRowOn]} onPress={() => toggleSource(src)}>
          <View style={styles.sourceRowLabel}><SourceIcon name={src} small /><Text style={[styles.sourceRowName, on && styles.sourceRowNameOn]}>{src}</Text></View>
          <View style={[styles.switchTrack, on && styles.switchTrackOn]}><View style={[styles.switchKnob, on && styles.switchKnobOn]} /></View>
        </TouchableOpacity>;
      })}
    </View>

    <View style={styles.settingsCard}>
      <Text style={styles.settingsTitle}>טווח זמן</Text>
      <View style={styles.wrap}>{[1, 2, 3, 7].map(d => <Chip key={d} label={d === 1 ? 'יום אחד' : `${d} ימים`} active={prefs.days === d} onPress={() => setPrefs(prev => ({ ...prev, days: d }))} />)}</View>
    </View>

    <View style={styles.settingsCard}>
      <Text style={styles.settingsTitle}>עוד</Text>
      <TouchableOpacity style={styles.sourceRow} onPress={() => Linking.openURL(`https://wa.me/?text=${encodeURIComponent(APP_SHARE_TEXT)}`).catch(() => null)}><Text style={styles.sourceRowName}>שתף את Poenta בווטסאפ</Text><Text style={styles.switchText}>›</Text></TouchableOpacity>
      <Text style={styles.about}>Poenta מרכזת חדשות ממגוון מקורות ומזקקת כל ידיעה לכותרת, התמצית והפואנטה — בלי רעש ובלי קליקבייט.</Text>
    </View>
  </View>;

  const list = view === 'breaking' ? visibleBreaking : view === 'saved' ? savedItems : view === 'search' ? searchResults : visibleMain;
  const unreadCount = visibleMain.filter(i => !readKeys.includes(itemKey(i))).length;

  return <SafeAreaView style={styles.safe}>
    <StatusBar style="light" />
    <View style={[styles.topbar, { height: topbarHeight, paddingTop: topInset }]}>
      <View style={styles.header}>
        <Image source={POENTA_LOGO} style={styles.logoImage as any} resizeMode="contain" />
        <TouchableOpacity style={styles.topMore} accessibilityLabel="עוד" onPress={() => switchView('more')}><Text style={styles.topMoreText}>☰</Text></TouchableOpacity>
      </View>
      <TouchableOpacity style={styles.updates} onPress={loadAll}>
        <View style={styles.updatePill}><Text style={styles.updatePillText}>{unreadCount || visibleMain.length}</Text></View>
        <View style={styles.updateTrack}><View style={styles.updateFill} /><Text style={styles.updateText}>מדד החדשים שלך</Text></View>
      </TouchableOpacity>
      <View style={styles.tabline}>{(view === 'home' || view === 'breaking') && renderTabs()}</View>
    </View>

    <ScrollView style={styles.scroll} contentContainerStyle={[styles.content, { paddingTop: topbarHeight + 4, paddingBottom: navHeight + 52 }]} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={loadAll} tintColor={theme.yellow} />}>
      {view === 'search' && <>
        <Text style={styles.title}>חיפוש</Text>
        <Text style={styles.subtitle}>חיפוש חכם בכתבות מהפיד ומהשמורים. אפשר לכתוב רעיון כמו “הופעות רוק”.</Text>
        <TextInput style={styles.searchInput} value={search} onChangeText={setSearch} placeholder="מה לחפש? למשל הופעות רוק" placeholderTextColor="rgba(255,255,255,0.34)" />
      </>}

      {view === 'saved' && <>
        <Text style={styles.title}>שמורים</Text>
        <Text style={styles.subtitle}>{savedItems.length ? `${savedItems.length} כתבות שמורות` : 'אפשר לשמור כתבות מהפיד בלחיצה על שמור.'}</Text>
      </>}

      {loading && <ActivityIndicator color={theme.yellow} style={{ marginTop: 28 }} />}
      {error && <Text style={styles.error}>שגיאה בטעינת הפיד: {error}</Text>}
      {view === 'settings' ? renderSettings() : view === 'more' ? renderMore() : <>
        {!loading && !list.length && <Text style={styles.empty}>{view === 'search' && search.trim().length < 2 ? 'הקלד לפחות 2 אותיות לחיפוש.' : 'אין אייטמים להצגה כרגע.'}</Text>}
        {list.map((item, index) => view === 'breaking'
          ? <BreakingCard key={`${itemKey(item)}-${index}`} item={item} index={index} />
          : <ArticleCard key={`${itemKey(item)}-${index}`} item={item} index={index} saved={savedKeys.includes(itemKey(item))} onSave={() => { toggleSaved(item); markRead(item); }} />)}
      </>}
    </ScrollView>

    <View style={[styles.nav, { height: navHeight, paddingBottom: bottomInset }]}>
      <NavButton label="שמור" icon="bookmark" active={view === 'saved'} onPress={() => switchView('saved')} />
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
const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#071015', direction: 'rtl' },
  topbar: { position: 'absolute', top: 0, left: 0, right: 0, zIndex: 50, backgroundColor: '#071015', borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.07)', borderBottomLeftRadius: 18, borderBottomRightRadius: 18, shadowColor: '#000', shadowOpacity: 0.34, shadowRadius: 22, shadowOffset: { width: 0, height: 10 }, elevation: 10 },
  header: { height: 52, paddingHorizontal: 16, paddingTop: 4, flexDirection: 'row', direction: 'ltr', alignItems: 'center', justifyContent: 'space-between' },
  topMore: { width: 36, height: 36, alignItems: 'center', justifyContent: 'center' },
  topMoreText: { color: 'rgba(255,255,255,0.82)', fontSize: 25, fontWeight: '900', lineHeight: 30 },
  logoImage: { height: 38, width: 164 },
  updates: { height: 44, paddingHorizontal: 16, borderTopWidth: 1, borderBottomWidth: 1, borderColor: 'rgba(255,255,255,0.07)', backgroundColor: 'rgba(255,255,255,0.025)', justifyContent: 'center' },
  updatePill: { position: 'absolute', left: 18, top: 3, minWidth: 34, height: 20, borderWidth: 1, borderColor: 'rgba(255,196,0,0.28)', borderRadius: 999, backgroundColor: 'rgba(255,255,255,0.035)', alignItems: 'center', justifyContent: 'center', zIndex: 2 },
  updatePillText: { color: 'rgba(255,196,0,0.88)', fontSize: 12, fontWeight: '900' },
  updateTrack: { height: 16, marginTop: 20, borderRadius: 999, overflow: 'hidden', backgroundColor: 'rgba(255,196,0,0.16)', borderWidth: 1, borderColor: 'rgba(255,196,0,0.18)', alignItems: 'center', justifyContent: 'center' },
  updateFill: { position: 'absolute', right: 0, top: 0, bottom: 0, width: '68%', backgroundColor: '#FFC400' },
  updateText: { color: '#071015', fontSize: 10.8, fontWeight: '900', letterSpacing: -0.05 },
  tabline: { height: 46, paddingHorizontal: 16, justifyContent: 'center' },
  scroll: { flex: 1 },
  content: { paddingHorizontal: 16 },
  title: { color: theme.text, fontSize: 25, lineHeight: 30, fontWeight: '900', textAlign: 'right' },
  subtitle: { color: theme.muted, fontSize: 13.5, lineHeight: 20, fontWeight: '700', textAlign: 'right', marginTop: 7, marginBottom: 12 },
  tabs: { flexDirection: 'row-reverse', gap: 9, alignItems: 'center' },
  chip: { height: 28, maxWidth: 132, borderWidth: 1, borderColor: 'rgba(255,255,255,0.055)', borderRadius: 999, backgroundColor: 'rgba(255,255,255,0.035)', paddingHorizontal: 9, paddingVertical: 0, flexDirection: 'row-reverse', gap: 6, alignItems: 'center', justifyContent: 'center' },
  chipActive: { borderColor: '#FFC400', backgroundColor: '#FFC400' },
  chipText: { color: 'rgba(255,255,255,0.62)', fontSize: 13, fontWeight: '800' },
  chipTextActive: { color: '#071015', fontWeight: '900' },
  chipCount: { minWidth: 18, height: 18, lineHeight: 18, textAlign: 'center', color: '#FFC400', backgroundColor: 'rgba(255,196,0,0.16)', borderRadius: 999, overflow: 'hidden', paddingHorizontal: 5, fontSize: 10.5, fontWeight: '900' },
  feedToggle: { flexDirection: 'row-reverse', gap: 8, marginBottom: 3 },
  card: { borderWidth: 1, borderColor: 'rgba(255,255,255,0.05)', borderRadius: 18, backgroundColor: 'rgba(255,255,255,0.022)', paddingHorizontal: 14, paddingTop: 13, paddingBottom: 0, marginTop: 10, overflow: 'hidden', shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 20, shadowOffset: { width: 0, height: 8 }, elevation: 2 },
  unreadCard: { borderColor: 'rgba(255,196,0,0.18)' },
  breakingCard: { borderColor: 'rgba(255,196,0,0.22)', backgroundColor: 'rgba(255,196,0,0.055)', paddingBottom: 14 },
  metaRow: { flexDirection: 'row', direction: 'rtl', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8, paddingHorizontal: 2, gap: 8 },
  metaActions: { flexDirection: 'row', direction: 'rtl', alignItems: 'center', gap: 7, flexShrink: 1 },
  cat: { flexDirection: 'row-reverse', alignItems: 'center', gap: 7, flex: 1 },
  iconAction: { width: 15, height: 15, alignItems: 'center', justifyContent: 'center', marginLeft: 1 },
  iconActionText: { color: '#FFC400', fontSize: 14, fontWeight: '900', lineHeight: 16 },
  iconActionOn: { color: '#FFC400' },
  star: { color: theme.yellow, fontSize: 15, fontWeight: '900', lineHeight: 16 },
  bolt: { color: theme.yellow, fontSize: 16, fontWeight: '900' },
  catText: { color: theme.muted, fontSize: 12, fontWeight: '800', textAlign: 'right', flexShrink: 1 },
  time: { color: theme.muted, fontSize: 12, fontWeight: '700', textAlign: 'left' },
  heroBox: { position: 'relative', borderRadius: 22, overflow: 'hidden', backgroundColor: '#111a20', minHeight: 214, justifyContent: 'flex-end', marginBottom: 11 },
  heroShade: { position: 'absolute', left: 0, right: 0, bottom: 0, height: 118, backgroundColor: 'rgba(0,0,0,0.42)' },
  image: { width: '100%', height: 214, borderRadius: 0, backgroundColor: '#111a20' },
  placeholder: { width: '100%', height: 214, borderRadius: 0, backgroundColor: '#111a20', alignItems: 'center', justifyContent: 'center' },
  placeholderText: { color: '#071015', backgroundColor: theme.yellow, overflow: 'hidden', borderRadius: 15, width: 48, height: 48, lineHeight: 48, textAlign: 'center', fontSize: 22, fontWeight: '900' },
  headline: { position: 'absolute', bottom: 0, right: 0, left: 0, color: '#FFFFFF', fontSize: 21.5, lineHeight: 24.3, fontWeight: '900', textAlign: 'right', letterSpacing: -0.42, paddingHorizontal: 15, paddingBottom: 13, paddingTop: 44, textShadowColor: 'rgba(0,0,0,0.55)', textShadowRadius: 11, textShadowOffset: { width: 0, height: 2 } },
  breakingHeadline: { color: theme.text, fontSize: 21.5, lineHeight: 25, fontWeight: '900', textAlign: 'right', letterSpacing: -0.42, marginBottom: 8 },
  summary: { color: 'rgba(255,255,255,0.72)', fontSize: 14.8, lineHeight: 21.3, fontWeight: '500', textAlign: 'right' },
  takeawayBox: { marginTop: 9, paddingTop: 9, borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.07)' },
  takeaway: { color: theme.yellowSoft, fontSize: 14, lineHeight: 17.5, fontWeight: '800', textAlign: 'right' },
  actionRow: { marginTop: 12, flexDirection: 'row-reverse', gap: 8, alignItems: 'stretch' },
  smallAction: { borderWidth: 1, borderColor: theme.faint, borderRadius: 14, backgroundColor: 'rgba(255,255,255,0.035)', paddingHorizontal: 10, alignItems: 'center', justifyContent: 'center' },
  smallActionOn: { borderColor: 'rgba(255,196,0,0.42)', backgroundColor: 'rgba(255,196,0,0.13)' },
  smallActionText: { color: theme.yellow, fontSize: 12, fontWeight: '900' },
  sourceBox: { position: 'relative', marginTop: 12, marginHorizontal: -1, borderWidth: 1, borderColor: 'rgba(255,196,0,0.18)', borderRadius: 15, backgroundColor: 'rgba(255,196,0,0.07)', paddingHorizontal: 12, paddingTop: 10, paddingBottom: 11, overflow: 'hidden' },
  sourceAccent: { position: 'absolute', right: 0, top: 12, bottom: 12, width: 3, borderRadius: 999, backgroundColor: 'rgba(255,196,0,0.74)' },
  sourceHead: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 7 },
  sourceLabel: { color: theme.yellow, backgroundColor: 'rgba(255,196,0,0.13)', borderRadius: 999, paddingHorizontal: 7, paddingVertical: 4, fontSize: 10.5, fontWeight: '900', overflow: 'hidden' },
  sourceBrand: { flexDirection: 'row', direction: 'rtl', alignItems: 'center', gap: 6, flexShrink: 1, minWidth: 0 },
  sourceNameText: { color: 'rgba(255,255,255,0.74)', fontSize: 11.5, fontWeight: '900', flexShrink: 1 },
  sourceIconImage: { width: 22, height: 22, borderRadius: 7, backgroundColor: 'rgba(255,255,255,0.08)' },
  sourceIconFallback: { width: 22, height: 22, borderRadius: 7, backgroundColor: 'rgba(255,255,255,0.08)', alignItems: 'center', justifyContent: 'center' },
  sourceIconFallbackText: { color: '#fff', fontSize: 9.5, fontWeight: '900' },
  sourceText: { color: 'rgba(255,255,255,0.84)', fontSize: 13.8, lineHeight: 18.5, fontWeight: '700', textAlign: 'right', writingDirection: 'rtl' },
  panel: { gap: 12 },
  settingsCard: { borderWidth: 1, borderColor: 'rgba(255,255,255,0.07)', borderRadius: 20, backgroundColor: 'rgba(255,255,255,0.03)', padding: 16, marginTop: 8 },
  settingsHead: { flexDirection: 'row', direction: 'rtl', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12, gap: 12 },
  settingsTitle: { color: theme.text, fontSize: 18, lineHeight: 19, fontWeight: '900', textAlign: 'right' },
  savedPill: { color: theme.yellow, backgroundColor: 'rgba(255,196,0,0.13)', fontSize: 11, fontWeight: '900', borderWidth: 1, borderColor: 'rgba(255,196,0,.20)', borderRadius: 999, paddingHorizontal: 9, paddingVertical: 5, overflow: 'hidden' },
  bulkRow: { flexDirection: 'row', direction: 'rtl', justifyContent: 'flex-start', gap: 8, marginBottom: 10 },
  bulkBtn: { borderWidth: 1, borderColor: 'rgba(255,196,0,0.24)', borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7, backgroundColor: 'rgba(255,196,0,0.08)' },
  bulkText: { color: theme.yellow, fontSize: 12, fontWeight: '900' },
  wrap: { flexDirection: 'row', direction: 'rtl', justifyContent: 'flex-start', flexWrap: 'wrap', gap: 8 },
  inputRow: { flexDirection: 'row', direction: 'rtl', gap: 8, marginTop: 10 },
  input: { flex: 1, height: 45, borderRadius: 14, borderWidth: 1, borderColor: 'rgba(255,255,255,0.07)', color: theme.text, backgroundColor: '#0b151a', paddingHorizontal: 12, textAlign: 'right', fontWeight: '700' },
  addBtn: { borderRadius: 14, backgroundColor: theme.yellow, paddingHorizontal: 15, alignItems: 'center', justifyContent: 'center' },
  addText: { color: '#091016', fontWeight: '900' },
  sourceRow: { borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.07)', paddingVertical: 12, flexDirection: 'row', direction: 'rtl', justifyContent: 'space-between', alignItems: 'center', gap: 12 },
  sourceRowOn: { backgroundColor: 'rgba(255,196,0,0.04)' },
  sourceRowLabel: { flex: 1, flexDirection: 'row', direction: 'rtl', alignItems: 'center', gap: 9, minWidth: 0 },
  sourceMiniImage: { width: 24, height: 24, borderRadius: 8, backgroundColor: 'rgba(255,255,255,0.08)' },
  sourceMiniFallback: { width: 24, height: 24, borderRadius: 8, backgroundColor: 'rgba(255,255,255,0.08)', alignItems: 'center', justifyContent: 'center' },
  sourceMiniFallbackText: { color: theme.yellow, fontSize: 10, fontWeight: '900' },
  sourceRowName: { color: theme.text, fontSize: 14, fontWeight: '800', textAlign: 'right', flexShrink: 1 },
  sourceRowNameOn: { color: theme.yellow },
  switchText: { color: theme.yellow, fontSize: 12, fontWeight: '900' },
  switchTrack: { width: 42, height: 24, borderRadius: 999, backgroundColor: 'rgba(255,255,255,0.16)', padding: 3, justifyContent: 'center', alignItems: 'flex-start' },
  switchTrackOn: { backgroundColor: theme.yellow, alignItems: 'flex-end' },
  switchKnob: { width: 18, height: 18, borderRadius: 999, backgroundColor: '#fff' },
  switchKnobOn: { backgroundColor: '#071015' },
  about: { color: theme.secondary, textAlign: 'right', lineHeight: 21, marginTop: 12, fontWeight: '600' },
  moreHead: { flexDirection: 'row', direction: 'rtl', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 12 },
  moreHeadText: { flex: 1, alignItems: 'flex-start' },
  moreHeadSub: { color: 'rgba(255,255,255,0.55)', fontSize: 13, fontWeight: '700', lineHeight: 18, textAlign: 'right', marginTop: 5 },
  moreBack: { borderWidth: 1, borderColor: 'rgba(255,196,0,0.24)', borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7, backgroundColor: 'rgba(255,196,0,0.08)' },
  moreBackText: { color: theme.yellow, fontSize: 12, fontWeight: '900' },
  moreList: { gap: 10 },
  moreRow: { borderWidth: 1, borderColor: 'rgba(255,255,255,0.07)', borderRadius: 18, backgroundColor: 'rgba(255,255,255,0.03)', paddingHorizontal: 15, paddingVertical: 14, flexDirection: 'row', direction: 'rtl', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  moreRowDisabled: { opacity: 0.46 },
  moreRowText: { flex: 1, alignItems: 'flex-start' },
  moreTitle: { color: theme.text, fontSize: 16, fontWeight: '900', textAlign: 'right' },
  moreSub: { color: 'rgba(255,255,255,0.52)', fontSize: 12.5, fontWeight: '700', lineHeight: 17, textAlign: 'right', marginTop: 4 },
  moreArrow: { color: theme.yellow, fontSize: 28, fontWeight: '800', lineHeight: 30 },
  shareActionIcon: { width: 38, height: 38, borderRadius: 14, borderWidth: 1.5, borderColor: 'rgba(255,196,0,0.55)', backgroundColor: '#f7f1df', alignItems: 'center', justifyContent: 'center', shadowColor: '#FFC400', shadowOpacity: 0.16, shadowRadius: 10, shadowOffset: { width: 0, height: 0 }, elevation: 4 },
  shareActionImage: { width: 27, height: 27, borderRadius: 9 },
  aboutContent: { borderWidth: 1, borderColor: 'rgba(255,255,255,0.07)', borderRadius: 20, backgroundColor: 'rgba(255,255,255,0.03)', padding: 16 },
  moreSectionTitle: { color: theme.text, fontSize: 17, fontWeight: '900', textAlign: 'right', marginTop: 14, marginBottom: 2 },
  translationNote: { color: theme.secondary, textAlign: 'right', lineHeight: 20, marginTop: 12, fontWeight: '700' },
  searchInput: { height: 50, borderRadius: 16, borderWidth: 1, borderColor: 'rgba(255,255,255,0.10)', backgroundColor: '#0b151a', color: theme.text, paddingHorizontal: 14, textAlign: 'right', fontSize: 16, fontWeight: '800', marginBottom: 10 },
  empty: { color: theme.muted, textAlign: 'center', marginTop: 34, fontWeight: '800' },
  error: { color: theme.red, textAlign: 'right', marginTop: 18, fontWeight: '800' },
  nav: { position: 'absolute', left: 0, right: 0, bottom: 0, borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.05)', borderTopLeftRadius: 18, borderTopRightRadius: 18, backgroundColor: '#050b0f', flexDirection: 'row', direction: 'ltr', paddingBottom: 10, justifyContent: 'space-around', shadowColor: '#000', shadowOpacity: 0.38, shadowRadius: 30, shadowOffset: { width: 0, height: -14 }, elevation: 20 },
  navButton: { flex: 1, alignItems: 'center', justifyContent: 'center', minWidth: 0 },
  navActive: {},
  navIcon: { color: 'rgba(255,255,255,0.48)', fontSize: 28, fontWeight: '800', lineHeight: 30 },
  navLogoBadge: { width: 36, height: 36, borderRadius: 14, backgroundColor: '#f7f1df', borderWidth: 1.5, borderColor: 'rgba(255,196,0,0.38)', alignItems: 'center', justifyContent: 'center' },
  navLogoBadgeActive: { borderColor: theme.yellow, shadowColor: '#FFC400', shadowOpacity: 0.22, shadowRadius: 12, shadowOffset: { width: 0, height: 0 }, elevation: 5 },
  navLogo: { width: 27, height: 27, borderRadius: 9 },
  navText: { display: 'none' },
  navTextActive: { color: theme.yellow },
});
