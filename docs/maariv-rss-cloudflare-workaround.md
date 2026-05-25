# Maariv RSS Cloudflare workaround — 2026-05-25

## Finding

Direct fetches to the official Maariv RSS endpoints currently return Cloudflare challenge pages instead of XML from this server.

Checked endpoints:

- `https://www.maariv.co.il/rss/rsschadashot`
- `https://www.maariv.co.il/rss/rssfeedsmivzakichadashot`
- `https://www.maariv.co.il/rss/rssfeedszavavebetachon`

Result with a normal browser-like user agent and with `PoantaRSS/0.1`:

- HTTP: `403`
- Content type: `text/html; charset=UTF-8`
- Body starts with: `<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>`

This is a source-access problem, not an editor/QA/feed-publication problem.

## Current operational treatment

- Do not block a clean feed deploy only because Maariv source-view freshness is stale.
- Keep Maariv stale status as an operational warning/source-debt signal.
- Do not bypass Cloudflare with scraping tricks, cookies, or headless challenge-solving inside routine feed jobs.
- For urgent freshness, rely on other active official/security sources already in the feed: IDF Spokesperson Telegram, Israel Police Telegram, ynet, Walla, Israel Hayom, Jerusalem Post, and vetted foreign Middle East feeds.

## Safe future options

1. Find a stable official Maariv XML endpoint that does not trigger Cloudflare and validate it before enabling.
2. If Lior approves a non-official fallback, add a tightly scoped Google News/Bing News fallback for Maariv and mark it `official: false`.
3. Keep the live auditor warning-only for Maariv until a stable source path exists.

## Verification command used

```bash
python3 - <<'PY'
import subprocess
urls = [
  'https://www.maariv.co.il/rss/rsschadashot',
  'https://www.maariv.co.il/rss/rssfeedsmivzakichadashot',
  'https://www.maariv.co.il/rss/rssfeedszavavebetachon',
]
for ua in [
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36',
  'PoantaRSS/0.1',
]:
  for url in urls:
    p = subprocess.run([
      'curl', '-L', '-sS', '-o', '/tmp/maariv.out',
      '-w', '%{http_code} %{content_type} %{size_download}',
      '-A', ua, url,
    ], text=True, capture_output=True, timeout=30)
    print(url, p.stdout.strip())
    print(open('/tmp/maariv.out', 'rb').read(120))
PY
```
