const CACHE_NAME = 'poanta-demo-v2';
const ASSETS = ['./', './index.html', './feed.json', './manifest.webmanifest'];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  event.respondWith(
    fetch(request).then(response => {
      const copy = response.clone();
      caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
      return response;
    }).catch(() => caches.match(request).then(cached => cached || caches.match('./index.html')))
  );
});

self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { title: event.data.text() }; }
  const title = data.title || 'פואנטה חדשה';
  const options = {
    body: data.body || 'יש עדכון חדש בפיד פואנטה',
    icon: './icon-192.png',
    badge: './icon-192.png',
    data: { url: data.url || './index.html' },
    dir: 'rtl',
    lang: 'he-IL',
    tag: data.tag || 'poanta-update',
    renotify: true
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const targetUrl = event.notification.data?.url || './index.html';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clientList => {
      for (const client of clientList) {
        if ('focus' in client) return client.focus();
      }
      return clients.openWindow(targetUrl);
    })
  );
});
