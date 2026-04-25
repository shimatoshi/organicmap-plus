const CACHE_NAME = 'omplus-v2';

// Install: minimal shell only
self.addEventListener('install', e => {
  e.waitUntil(self.skipWaiting());
});

// Activate: claim clients, clean old caches
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME && k !== 'omplus-tiles').map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Fetch: stale-while-revalidate for same-origin, cache-first for tiles/CDN
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Tile requests: cache-first, long-lived
  if (url.hostname === 'tile.openstreetmap.org') {
    e.respondWith(
      caches.open('omplus-tiles').then(cache =>
        cache.match(e.request).then(cached => {
          if (cached) return cached;
          return fetch(e.request).then(resp => {
            if (resp.ok) cache.put(e.request, resp.clone());
            return resp;
          }).catch(() => cached);
        })
      )
    );
    return;
  }

  // Leaflet CDN: cache-first
  if (url.hostname === 'unpkg.com') {
    e.respondWith(
      caches.open(CACHE_NAME).then(cache =>
        cache.match(e.request).then(cached => {
          if (cached) return cached;
          return fetch(e.request).then(resp => {
            if (resp.ok) cache.put(e.request, resp.clone());
            return resp;
          });
        })
      )
    );
    return;
  }

  // Same-origin: network-first, fallback to cache
  if (url.origin === self.location.origin) {
    e.respondWith(
      fetch(e.request).then(resp => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(e.request, clone));
        }
        return resp;
      }).catch(() => caches.match(e.request))
    );
    return;
  }
});
