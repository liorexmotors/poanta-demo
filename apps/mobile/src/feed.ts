import { FeedResponse } from './types';

export const DEFAULT_FEED_URL = 'https://poenta.app/feed.json';
export const DEFAULT_BREAKING_URL = 'https://poenta.app/breaking_feed.json';

async function fetchJson(url: string) {
  const res = await fetch(`${url}?v=${Date.now()}`, {
    headers: { Accept: 'application/json', 'User-Agent': 'PoentaMobile/0.2' },
  });
  if (!res.ok) throw new Error(`Feed request failed: ${res.status}`);
  return res.json();
}

export async function fetchFeed(url = DEFAULT_FEED_URL): Promise<FeedResponse> {
  const data = await fetchJson(url);
  return { items: Array.isArray(data.items) ? data.items : [], updatedAt: data.updatedAt, mode: data.mode };
}

export async function fetchBreakingFeed(url = DEFAULT_BREAKING_URL): Promise<FeedResponse> {
  const data = await fetchJson(url);
  return {
    items: Array.isArray(data.items) ? data.items : [],
    updatedAt: data.updatedAt,
    ttlHours: typeof data.ttlHours === 'number' ? data.ttlHours : 12,
    mode: data.mode,
  };
}
