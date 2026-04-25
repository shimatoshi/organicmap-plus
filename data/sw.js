const CACHE_NAME = 'omplus-v1';
const SHELL = [
  './',
  './index.html',
  './transit/viewer.html',
  './transit/index.json',
  './spots/viewer.html',
  './spots/spots_index.json',
  './spots/spots_data.json',
  './manifest.webmanifest',
];

// Install: cache app shell
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

// Activate: clean old caches
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Fetch: network-first for data, cache-first for shell
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Tile requests: cache with long TTL
  if (url.hostname === 'tile.openstreetmap.org') {
    e.respondWith(
      caches.open('omplus-tiles').then(cache =>
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

  // Leaflet CDN: cache on first use
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

  // Pref JSON files: stale-while-revalidate
  if (url.pathname.includes('/pref/') && url.pathname.endsWith('.json')) {
    e.respondWith(
      caches.open(CACHE_NAME).then(cache =>
        cache.match(e.request).then(cached => {
          const fetchPromise = fetch(e.request).then(resp => {
            if (resp.ok) cache.put(e.request, resp.clone());
            return resp;
          }).catch(() => cached);
          return cached || fetchPromise;
        })
      )
    );
    return;
  }

  // App shell: cache-first
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(resp => {
        if (resp.ok && url.origin === self.location.origin) {
          caches.open(CACHE_NAME).then(cache => cache.put(e.request, resp.clone()));
        }
        return resp;
      });
    })
  );
});
