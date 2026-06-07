import { FeedResponse } from './types';

export const DEFAULT_FEED_URL = 'https://poenta.app/feed.json';
export const DEFAULT_BREAKING_URL = 'https://poenta.app/breaking_feed.json';

const FEED_FALLBACK_URLS = [
  DEFAULT_FEED_URL,
  'https://raw.githubusercontent.com/ExcellentMotors/poanta-demo/gh-pages/feed.json',
];
const BREAKING_FALLBACK_URLS = [
  DEFAULT_BREAKING_URL,
  'https://raw.githubusercontent.com/ExcellentMotors/poanta-demo/gh-pages/breaking_feed.json',
];

async function fetchJson(url: string, timeoutMs = 8500) {
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const res = await fetch(`${url}?v=${Date.now()}`, {
      headers: { Accept: 'application/json' },
      signal: controller?.signal,
    });
    if (!res.ok) throw new Error(`Feed request failed: ${res.status}`);
    return res.json();
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function fetchFirstJson(urls: string[]) {
  let lastError: unknown = null;
  for (const url of urls) {
    try { return await fetchJson(url); }
    catch (err) { lastError = err; }
  }
  throw lastError instanceof Error ? lastError : new Error('Feed request failed');
}

export async function fetchFeed(url = DEFAULT_FEED_URL): Promise<FeedResponse> {
  const data = await fetchFirstJson(url === DEFAULT_FEED_URL ? FEED_FALLBACK_URLS : [url, ...FEED_FALLBACK_URLS]);
  return { items: Array.isArray(data.items) ? data.items : [], updatedAt: data.updatedAt, mode: data.mode };
}

export async function fetchBreakingFeed(url = DEFAULT_BREAKING_URL): Promise<FeedResponse> {
  const data = await fetchFirstJson(url === DEFAULT_BREAKING_URL ? BREAKING_FALLBACK_URLS : [url, ...BREAKING_FALLBACK_URLS]);
  return {
    items: Array.isArray(data.items) ? data.items : [],
    updatedAt: data.updatedAt,
    ttlHours: typeof data.ttlHours === 'number' ? data.ttlHours : 12,
    mode: data.mode,
  };
}
