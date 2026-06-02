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
import { fetchBreakingFeed, fetchFeed } from './src/feed';
import { FeedItem } from './src/types';
import { theme } from './src/theme';

type ViewMode = 'home' | 'breaking' | 'saved' | 'search' | 'settings';
type Prefs = { topics: string[]; sources: string[]; days: number; feedFilter: 'all' | 'unread' };

const DEFAULT_TOPICS = ['ביטחון', 'פוליטיקה', 'אקטואליה בעולם', 'כלכלה', 'רכב', 'טכנולוגיה', 'צרכנות', 'תרבות', 'ספורט', 'בריאות'];
const APP_SHARE_TEXT = 'מצאתי אפליקציית חדשות מעולה — Poenta.\nחדשות בעברית עם תקציר ברור, הקשר והפואנטה.\nhttps://poenta.app/';

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

function LogoMark() {
  return <View style={styles.mark}><View style={[styles.markLine, { top: 10, width: 20 }]} /><View style={[styles.markLine, { top: 18, width: 20 }]} /><View style={[styles.markLine, { top: 26, width: 14 }]} /></View>;
}

function Chip({ label, active, onPress, count }: { label: string; active: boolean; onPress: () => void; count?: number }) {
  return <TouchableOpacity style={[styles.chip, active && styles.chipActive]} onPress={onPress} activeOpacity={0.82}>
    <Text style={[styles.chipText, active && styles.chipTextActive]}>{label}</Text>
    {typeof count === 'number' && <Text style={[styles.chipCount, active && styles.chipTextActive]}>{count}</Text>}
  </TouchableOpacity>;
}

function SourceThumb({ item }: { item: FeedItem }) {
  if (item.imageUrl) return <Image source={{ uri: item.imageUrl }} style={styles.image} />;
  const label = sourceName(item).slice(0, 2) || 'P';
  return <View style={styles.placeholder}><Text style={styles.placeholderText}>{label}</Text></View>;
}

function ArticleCard({ item, index, saved, onSave }: { item: FeedItem; index: number; saved: boolean; onSave: () => void }) {
  const open = () => { if (item.sourceUrl) Linking.openURL(item.sourceUrl).catch(() => null); };
  return <View style={[styles.card, index < 3 && styles.unreadCard]}>
    <View style={styles.metaRow}>
      <View style={styles.cat}><Text style={styles.star}>✧</Text><Text style={styles.catText}>{topicFor(item)}</Text></View>
      <Text style={styles.time}>{timeLabel(item, index)}</Text>
    </View>
    <TouchableOpacity onPress={open} activeOpacity={item.sourceUrl ? 0.78 : 1}>
      <View style={styles.heroBox}>
        <SourceThumb item={item} />
        <Text style={styles.headline}>{displayHeadline(item)}</Text>
      </View>
      {!!summaryFor(item) && <Text style={styles.summary}>{summaryFor(item)}</Text>}
      {!!item.takeaway && <Text style={styles.takeaway}>💡 {String(item.takeaway).replace(/^💡\s*/, '')}</Text>}
    </TouchableOpacity>
    <View style={styles.actionRow}>
      <TouchableOpacity style={[styles.smallAction, saved && styles.smallActionOn]} onPress={onSave}><Text style={styles.smallActionText}>{saved ? '★ שמור' : '☆ שמור'}</Text></TouchableOpacity>
      <TouchableOpacity style={styles.sourceBox} onPress={open} activeOpacity={item.sourceUrl ? 0.78 : 1}>
        <Text style={styles.sourceLabel}>כותרת המקור</Text>
        <Text style={styles.sourceText}>{sourceName(item)}</Text>
      </TouchableOpacity>
    </View>
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

function NavButton({ label, icon, active, onPress }: { label: string; icon: string; active: boolean; onPress: () => void }) {
  return <TouchableOpacity style={[styles.navButton, active && styles.navActive]} onPress={onPress}>
    <Text style={[styles.navIcon, active && styles.navTextActive]}>{icon}</Text>
    <Text style={[styles.navText, active && styles.navTextActive]}>{label}</Text>
  </TouchableOpacity>;
}

export default function App() {
  const [items, setItems] = useState<FeedItem[]>([]);
  const [breaking, setBreaking] = useState<FeedItem[]>([]);
  const [view, setView] = useState<ViewMode>('home');
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
    setActiveFilter('all');
  }

  const renderTabs = () => {
    const tabs = view === 'breaking' ? breakingSources : prefs.topics.filter(t => knownTopics.includes(t));
    return <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tabs}>
      <Chip label="הכל" active={activeFilter === 'all'} onPress={() => setActiveFilter('all')} count={view === 'breaking' ? visibleBreaking.length : topicCounts.all} />
      {tabs.map(t => <Chip key={t} label={t} active={activeFilter === t} onPress={() => setActiveFilter(t)} count={view === 'breaking' ? breaking.filter(i => sourceName(i) === t || i.sources?.includes(t)).length : topicCounts[t] || 0} />)}
    </ScrollView>;
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
      {knownSources.map(src => <TouchableOpacity key={src} style={[styles.sourceRow, prefs.sources.includes(src) && styles.sourceRowOn]} onPress={() => toggleSource(src)}>
        <Text style={styles.sourceRowName}>{src}</Text><Text style={styles.switchText}>{prefs.sources.includes(src) ? 'פעיל' : 'כבוי'}</Text>
      </TouchableOpacity>)}
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

  return <SafeAreaView style={styles.safe}>
    <StatusBar style="light" />
    <View style={styles.header}>
      <View style={styles.brand}><LogoMark /><Text style={styles.logoText}>Poenta</Text></View>
      <View style={styles.badge}><Text style={styles.badgeText}>{view === 'breaking' ? 'מבזקים' : 'חי'}</Text></View>
    </View>

    <ScrollView style={styles.scroll} contentContainerStyle={styles.content} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={loadAll} tintColor={theme.yellow} />}>
      {view === 'home' && <>
        <Text style={styles.title}>פיד פואנטה</Text>
        <Text style={styles.subtitle}>חדשות בעברית, תקציר ברור, מקור והפואנטה — מותאם לתחומי העניין שלך.</Text>
        <View style={styles.feedToggle}>
          <Chip label="כל הידיעות" active={prefs.feedFilter === 'all'} onPress={() => setPrefs(prev => ({ ...prev, feedFilter: 'all' }))} count={visibleMain.length} />
          <Chip label="חדשים" active={prefs.feedFilter === 'unread'} onPress={() => setPrefs(prev => ({ ...prev, feedFilter: 'unread' }))} count={visibleMain.filter(i => !readKeys.includes(itemKey(i))).length} />
        </View>
        {renderTabs()}
      </>}

      {view === 'breaking' && <>
        <Text style={styles.title}>מבזקים</Text>
        <Text style={styles.subtitle}>עדכונים קצרים בזמן אמת, עם איחוד מקורות כדי לצמצם כפילויות.</Text>
        {renderTabs()}
      </>}

      {view === 'search' && <>
        <Text style={styles.title}>חיפוש</Text>
        <Text style={styles.subtitle}>חיפוש בכתבות מהפיד ומהשמורים.</Text>
        <TextInput style={styles.searchInput} value={search} onChangeText={setSearch} placeholder="מה לחפש? למשל הופעות רוק" placeholderTextColor="rgba(255,255,255,0.34)" />
      </>}

      {view === 'saved' && <>
        <Text style={styles.title}>שמורים</Text>
        <Text style={styles.subtitle}>{savedItems.length ? `${savedItems.length} כתבות שמורות` : 'אפשר לשמור כתבות מהפיד בלחיצה על שמור.'}</Text>
      </>}

      {loading && <ActivityIndicator color={theme.yellow} style={{ marginTop: 28 }} />}
      {error && <Text style={styles.error}>שגיאה בטעינת הפיד: {error}</Text>}
      {view === 'settings' ? renderSettings() : <>
        {!loading && !list.length && <Text style={styles.empty}>{view === 'search' && search.trim().length < 2 ? 'הקלד לפחות 2 אותיות לחיפוש.' : 'אין אייטמים להצגה כרגע.'}</Text>}
        {list.map((item, index) => view === 'breaking'
          ? <BreakingCard key={`${itemKey(item)}-${index}`} item={item} index={index} />
          : <ArticleCard key={`${itemKey(item)}-${index}`} item={item} index={index} saved={savedKeys.includes(itemKey(item))} onSave={() => { toggleSaved(item); markRead(item); }} />)}
      </>}
    </ScrollView>

    <View style={styles.nav}>
      <NavButton label="פיד" icon="⌂" active={view === 'home'} onPress={() => switchView('home')} />
      <NavButton label="מבזקים" icon="⚡" active={view === 'breaking'} onPress={() => switchView('breaking')} />
      <NavButton label="שמורים" icon="★" active={view === 'saved'} onPress={() => switchView('saved')} />
      <NavButton label="חיפוש" icon="⌕" active={view === 'search'} onPress={() => switchView('search')} />
      <NavButton label="הגדרות" icon="⚙" active={view === 'settings'} onPress={() => switchView('settings')} />
    </View>
  </SafeAreaView>;
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.bg, direction: 'rtl' },
  header: { height: 74, backgroundColor: theme.bg, borderBottomWidth: 1, borderBottomColor: theme.faint, paddingHorizontal: 18, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between' },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  mark: { width: 38, height: 38, borderRadius: 13, backgroundColor: theme.yellow, position: 'relative' },
  markLine: { position: 'absolute', right: 9, height: 3, borderRadius: 20, backgroundColor: '#0a0d0f' },
  logoText: { color: theme.text, fontSize: 30, fontWeight: '900', letterSpacing: -0.8 },
  badge: { borderColor: 'rgba(255,196,0,0.20)', borderWidth: 1, borderRadius: 999, backgroundColor: 'rgba(255,196,0,0.08)', paddingHorizontal: 10, paddingVertical: 6 },
  badgeText: { color: theme.yellow, fontSize: 11, fontWeight: '900' },
  scroll: { flex: 1 },
  content: { padding: 16, paddingBottom: 104 },
  title: { color: theme.text, fontSize: 25, lineHeight: 30, fontWeight: '900', textAlign: 'right' },
  subtitle: { color: theme.muted, fontSize: 13.5, lineHeight: 20, fontWeight: '700', textAlign: 'right', marginTop: 7, marginBottom: 12 },
  tabs: { flexDirection: 'row-reverse', gap: 8, paddingVertical: 7 },
  feedToggle: { flexDirection: 'row-reverse', gap: 8, marginBottom: 3 },
  chip: { borderWidth: 1, borderColor: theme.faint, borderRadius: 999, backgroundColor: 'rgba(255,255,255,0.035)', paddingHorizontal: 13, paddingVertical: 8, flexDirection: 'row-reverse', gap: 7, alignItems: 'center' },
  chipActive: { borderColor: 'rgba(255,196,0,0.62)', backgroundColor: 'rgba(255,196,0,0.14)' },
  chipText: { color: theme.secondary, fontSize: 12.5, fontWeight: '900' },
  chipTextActive: { color: theme.yellow },
  chipCount: { color: theme.muted, fontSize: 11, fontWeight: '900' },
  card: { borderWidth: 1, borderColor: theme.faint, borderRadius: 20, backgroundColor: 'rgba(255,255,255,0.026)', padding: 14, marginTop: 11 },
  unreadCard: { borderColor: 'rgba(255,196,0,0.18)' },
  breakingCard: { backgroundColor: 'rgba(255,196,0,0.045)' },
  metaRow: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between', marginBottom: 9, gap: 8 },
  cat: { flexDirection: 'row-reverse', alignItems: 'center', gap: 7, flex: 1 },
  star: { color: theme.yellow, fontSize: 15, fontWeight: '900' },
  bolt: { color: theme.yellow, fontSize: 16, fontWeight: '900' },
  catText: { color: theme.muted, fontSize: 12, fontWeight: '800', textAlign: 'right', flexShrink: 1 },
  time: { color: theme.muted, fontSize: 12, fontWeight: '700' },
  heroBox: { position: 'relative', borderRadius: 18, overflow: 'hidden', backgroundColor: '#111a20', minHeight: 156, justifyContent: 'flex-end', marginBottom: 11 },
  image: { width: '100%', height: 176, borderRadius: 18, backgroundColor: '#111a20' },
  placeholder: { width: '100%', height: 156, borderRadius: 18, backgroundColor: '#111a20', alignItems: 'center', justifyContent: 'center' },
  placeholderText: { color: '#071015', backgroundColor: theme.yellow, overflow: 'hidden', borderRadius: 18, width: 58, height: 58, lineHeight: 58, textAlign: 'center', fontSize: 22, fontWeight: '900' },
  headline: { position: 'absolute', bottom: 0, right: 0, left: 0, color: theme.text, fontSize: 22, lineHeight: 27, fontWeight: '900', textAlign: 'right', letterSpacing: -0.45, padding: 13, paddingTop: 46, backgroundColor: 'rgba(0,0,0,0.48)' },
  breakingHeadline: { color: theme.text, fontSize: 22, lineHeight: 27, fontWeight: '900', textAlign: 'right', letterSpacing: -0.45, marginBottom: 7 },
  summary: { color: theme.secondary, fontSize: 14.5, lineHeight: 21, fontWeight: '500', textAlign: 'right' },
  takeaway: { marginTop: 10, color: theme.yellowSoft, fontSize: 14, lineHeight: 19, fontWeight: '800', textAlign: 'right' },
  actionRow: { marginTop: 12, flexDirection: 'row-reverse', gap: 8, alignItems: 'stretch' },
  smallAction: { borderWidth: 1, borderColor: theme.faint, borderRadius: 14, backgroundColor: 'rgba(255,255,255,0.035)', paddingHorizontal: 10, alignItems: 'center', justifyContent: 'center' },
  smallActionOn: { borderColor: 'rgba(255,196,0,0.42)', backgroundColor: 'rgba(255,196,0,0.13)' },
  smallActionText: { color: theme.yellow, fontSize: 12, fontWeight: '900' },
  sourceBox: { flex: 1, borderWidth: 1, borderColor: 'rgba(255,196,0,0.18)', borderRadius: 15, backgroundColor: 'rgba(255,196,0,0.075)', padding: 10 },
  sourceLabel: { alignSelf: 'flex-start', color: theme.yellow, backgroundColor: 'rgba(255,196,0,0.13)', borderRadius: 999, paddingHorizontal: 7, paddingVertical: 4, fontSize: 10.5, fontWeight: '900', overflow: 'hidden' },
  sourceText: { marginTop: 7, color: 'rgba(255,255,255,0.84)', fontSize: 13.8, lineHeight: 19, fontWeight: '700', textAlign: 'right' },
  panel: { gap: 12 },
  settingsCard: { borderWidth: 1, borderColor: theme.faint, borderRadius: 18, backgroundColor: 'rgba(255,255,255,0.03)', padding: 13, marginTop: 8 },
  settingsHead: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  settingsTitle: { color: theme.text, fontSize: 18, fontWeight: '900', textAlign: 'right' },
  savedPill: { color: theme.yellow, fontSize: 11, fontWeight: '900', borderWidth: 1, borderColor: 'rgba(255,196,0,.25)', borderRadius: 999, paddingHorizontal: 8, paddingVertical: 4 },
  bulkRow: { flexDirection: 'row-reverse', gap: 8, marginBottom: 8 },
  bulkBtn: { borderWidth: 1, borderColor: theme.faint, borderRadius: 999, paddingHorizontal: 11, paddingVertical: 7 },
  bulkText: { color: theme.secondary, fontSize: 12, fontWeight: '800' },
  wrap: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8 },
  inputRow: { flexDirection: 'row-reverse', gap: 8, marginTop: 10 },
  input: { flex: 1, height: 45, borderRadius: 14, borderWidth: 1, borderColor: theme.faint, color: theme.text, backgroundColor: '#0b151a', paddingHorizontal: 12, textAlign: 'right', fontWeight: '700' },
  addBtn: { borderRadius: 14, backgroundColor: theme.yellow, paddingHorizontal: 15, alignItems: 'center', justifyContent: 'center' },
  addText: { color: '#091016', fontWeight: '900' },
  sourceRow: { borderWidth: 1, borderColor: theme.faint, borderRadius: 15, padding: 12, marginTop: 7, flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', backgroundColor: 'rgba(255,255,255,0.022)' },
  sourceRowOn: { borderColor: 'rgba(255,196,0,0.25)', backgroundColor: 'rgba(255,196,0,0.07)' },
  sourceRowName: { color: theme.text, fontSize: 14, fontWeight: '800', textAlign: 'right' },
  switchText: { color: theme.yellow, fontSize: 12, fontWeight: '900' },
  about: { color: theme.secondary, textAlign: 'right', lineHeight: 21, marginTop: 12, fontWeight: '600' },
  searchInput: { height: 50, borderRadius: 16, borderWidth: 1, borderColor: theme.faint, backgroundColor: '#0b151a', color: theme.text, paddingHorizontal: 14, textAlign: 'right', fontSize: 16, fontWeight: '800', marginBottom: 10 },
  empty: { color: theme.muted, textAlign: 'center', marginTop: 34, fontWeight: '800' },
  error: { color: theme.red, textAlign: 'right', marginTop: 18, fontWeight: '800' },
  nav: { position: 'absolute', left: 0, right: 0, bottom: 0, height: 78, borderTopWidth: 1, borderTopColor: theme.faint, backgroundColor: 'rgba(5,11,15,0.98)', flexDirection: 'row-reverse', paddingHorizontal: 6, paddingTop: 7, justifyContent: 'space-around' },
  navButton: { flex: 1, alignItems: 'center', justifyContent: 'flex-start', gap: 2, paddingVertical: 6, borderRadius: 15 },
  navActive: { backgroundColor: 'rgba(255,196,0,0.10)' },
  navIcon: { color: theme.muted, fontSize: 18, fontWeight: '900' },
  navText: { color: theme.muted, fontSize: 10.5, fontWeight: '900' },
  navTextActive: { color: theme.yellow },
});
