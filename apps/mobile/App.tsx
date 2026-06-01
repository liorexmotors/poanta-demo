import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Image, SafeAreaView, ScrollView, StyleSheet, Text, View } from 'react-native';
import { fetchFeed } from './src/feed';
import { FeedItem } from './src/types';
import { theme } from './src/theme';

function sourceName(item: FeedItem) {
  return item.sourceName || item.source || 'מקור';
}

function summary(item: FeedItem) {
  return item.summary || item.context || '';
}

function topic(item: FeedItem) {
  return item.topic || item.category || 'חדשות';
}

function timeLabel(item: FeedItem) {
  const raw = item.publishedAt || item.updatedAt;
  if (!raw) return '';
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return '';
  return new Intl.DateTimeFormat('he-IL', { hour: '2-digit', minute: '2-digit' }).format(d);
}

function LogoMark() {
  return <View style={styles.mark}><View style={[styles.markLine, { top: 10, width: 20 }]} /><View style={[styles.markLine, { top: 18, width: 20 }]} /><View style={[styles.markLine, { top: 26, width: 14 }]} /></View>;
}

function Card({ item, index }: { item: FeedItem; index: number }) {
  return <View style={[styles.card, index < 3 && styles.unreadCard]}>
    <View style={styles.metaRow}>
      <View style={styles.cat}><Text style={styles.star}>✧</Text><Text style={styles.catText}>{topic(item)}</Text></View>
      <Text style={styles.time}>{timeLabel(item)}</Text>
    </View>
    <Text style={styles.headline}>{item.headline}</Text>
    <View style={styles.contentRow}>
      <Text style={styles.summary}>{summary(item)}</Text>
      {item.imageUrl ? <Image source={{ uri: item.imageUrl }} style={styles.image} /> : <View style={styles.placeholder}><Text style={styles.placeholderText}>P</Text></View>}
    </View>
    {!!item.takeaway && <Text style={styles.takeaway}>💡 {item.takeaway}</Text>}
    <View style={styles.sourceBox}>
      <Text style={styles.sourceLabel}>כותרת המקור</Text>
      <Text style={styles.sourceText}>{sourceName(item)}</Text>
    </View>
  </View>;
}

export default function App() {
  const [items, setItems] = useState<FeedItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchFeed().then(feed => setItems(feed.items.slice(0, 30))).catch(err => setError(err.message)).finally(() => setLoading(false));
  }, []);

  return <SafeAreaView style={styles.safe}>
    <StatusBar style="light" />
    <View style={styles.header}>
      <View style={styles.brand}><LogoMark /><Text style={styles.logoText}>Poenta</Text></View>
      <View style={styles.badge}><Text style={styles.badgeText}>חי</Text></View>
    </View>
    <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
      <Text style={styles.title}>פיד פואנטה</Text>
      <Text style={styles.subtitle}>חדשות בעברית, תקציר ברור והמקור ליד כל ידיעה — כדי להבין מהר מה חשוב עכשיו.</Text>
      {loading && <ActivityIndicator color={theme.yellow} style={{ marginTop: 28 }} />}
      {error && <Text style={styles.error}>שגיאה בטעינת הפיד: {error}</Text>}
      {items.map((item, index) => <Card key={`${item.id || item.sourceUrl || item.headline}-${index}`} item={item} index={index} />)}
    </ScrollView>
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
  content: { padding: 16, paddingBottom: 32 },
  title: { color: theme.text, fontSize: 24, lineHeight: 28, fontWeight: '900', textAlign: 'right' },
  subtitle: { color: theme.muted, fontSize: 13, lineHeight: 19, fontWeight: '700', textAlign: 'right', marginTop: 7, marginBottom: 12 },
  card: { borderWidth: 1, borderColor: theme.faint, borderRadius: 18, backgroundColor: 'rgba(255,255,255,0.025)', padding: 15, marginTop: 10 },
  unreadCard: { borderColor: 'rgba(255,196,0,0.18)' },
  metaRow: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 },
  cat: { flexDirection: 'row-reverse', alignItems: 'center', gap: 7 },
  star: { color: theme.yellow, fontSize: 15, fontWeight: '900' },
  catText: { color: theme.muted, fontSize: 12, fontWeight: '800' },
  time: { color: theme.muted, fontSize: 12, fontWeight: '700' },
  headline: { color: theme.text, fontSize: 22, lineHeight: 26, fontWeight: '900', textAlign: 'right', letterSpacing: -0.45, marginBottom: 10 },
  contentRow: { flexDirection: 'row-reverse', gap: 12, alignItems: 'stretch' },
  summary: { flex: 1, color: theme.secondary, fontSize: 14.5, lineHeight: 21, fontWeight: '500', textAlign: 'right' },
  image: { width: 110, height: 88, borderRadius: 14, backgroundColor: '#111a20' },
  placeholder: { width: 110, height: 88, borderRadius: 14, backgroundColor: '#111a20', alignItems: 'center', justifyContent: 'center' },
  placeholderText: { color: '#071015', backgroundColor: theme.yellow, overflow: 'hidden', borderRadius: 14, width: 48, height: 48, lineHeight: 48, textAlign: 'center', fontSize: 24, fontWeight: '900' },
  takeaway: { marginTop: 10, color: theme.yellowSoft, fontSize: 14, lineHeight: 18, fontWeight: '800', textAlign: 'right' },
  sourceBox: { marginTop: 12, borderWidth: 1, borderColor: 'rgba(255,196,0,0.18)', borderRadius: 15, backgroundColor: 'rgba(255,196,0,0.075)', padding: 10 },
  sourceLabel: { alignSelf: 'flex-start', color: theme.yellow, backgroundColor: 'rgba(255,196,0,0.13)', borderRadius: 999, paddingHorizontal: 7, paddingVertical: 4, fontSize: 10.5, fontWeight: '900', overflow: 'hidden' },
  sourceText: { marginTop: 7, color: 'rgba(255,255,255,0.84)', fontSize: 13.8, lineHeight: 19, fontWeight: '700', textAlign: 'right' },
  error: { color: theme.red, textAlign: 'right', marginTop: 18, fontWeight: '800' },
});
