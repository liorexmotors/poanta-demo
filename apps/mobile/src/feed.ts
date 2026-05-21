import { FeedResponse } from './types';

export const DEFAULT_FEED_URL = 'https://liorexmotors.github.io/poanta-demo/feed.json';

export async function fetchFeed(url = DEFAULT_FEED_URL): Promise<FeedResponse> {
  const res = await fetch(`${url}?v=${Date.now()}`, { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`Feed request failed: ${res.status}`);
  const data = await res.json();
  return { items: Array.isArray(data.items) ? data.items : [], updatedAt: data.updatedAt };
}
