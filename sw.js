// ─── GRAPEFRUIT LEAGUE SERVICE WORKER ────────────────────────────────────────
// Hosted as /sw.js on Firebase Hosting
// Bump CACHE_VERSION when deploying a new build to force cache invalidation

const CACHE_VERSION = 'gfl-v3';
const CDN_CACHE = 'gfl-cdn-v3';

// ─── INSTALL ──────────────────────────────────────────────────────────────────
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CDN_CACHE).then(cache => cache.addAll([
      'https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Mono:ital,wght@0,300;0,400;0,500;1,400&family=DM+Sans:wght@300;400;500;600&display=swap',
      'https://www.gstatic.com/firebasejs/9.23.0/firebase-app-compat.js',
      'https://www.gstatic.com/firebasejs/9.23.0/firebase-firestore-compat.js'
    ]).catch(() => {})) // don't fail install if CDN is unavailable
  );
  self.skipWaiting(); // activate immediately, don't wait for old SW to die
});

// ─── ACTIVATE ─────────────────────────────────────────────────────────────────
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_VERSION && k !== CDN_CACHE)
          .map(k => {
            console.log('[SW] Deleting old cache:', k);
            return caches.delete(k);
          })
      )
    ).then(() => self.clients.claim()) // take control of all open tabs immediately
  );
});

// ─── FETCH ────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // 1. Always network-first for Firebase, GitHub, CouchManagers — never cache these
  if (
    url.hostname.includes('firestore.googleapis.com') ||
    url.hostname.includes('firebase') ||
    url.hostname.includes('githubusercontent.com') ||
    url.hostname.includes('couchmanagers.com')
  ) {
    e.respondWith(
      fetch(e.request).catch(() => caches.match(e.request))
    );
    return;
  }

  // 2. Network-first for the app shell (index.html) — always serve freshest version
  if (
    url.pathname === '/' ||
    url.pathname === '/index.html' ||
    url.pathname.endsWith('/')
  ) {
    e.respondWith(
      fetch(e.request)
        .then(res => {
          // Cache the fresh response for offline fallback
          const clone = res.clone();
          caches.open(CACHE_VERSION).then(c => c.put(e.request, clone));
          return res;
        })
        .catch(() => caches.match(e.request)) // fall back to cached version if offline
    );
    return;
  }

  // 3. Cache-first for fonts and CDN scripts (these rarely change)
  if (
    url.hostname.includes('fonts.googleapis.com') ||
    url.hostname.includes('fonts.gstatic.com') ||
    url.hostname.includes('gstatic.com')
  ) {
    e.respondWith(
      caches.match(e.request).then(hit => {
        if (hit) return hit;
        return fetch(e.request).then(res => {
          const clone = res.clone();
          caches.open(CDN_CACHE).then(c => c.put(e.request, clone));
          return res;
        });
      })
    );
    return;
  }

  // 4. Default: network-first, cache as fallback
  e.respondWith(
    fetch(e.request)
      .then(res => {
        const clone = res.clone();
        caches.open(CACHE_VERSION).then(c => c.put(e.request, clone));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});

// ─── MESSAGES ─────────────────────────────────────────────────────────────────
self.addEventListener('message', e => {
  if (e.data === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
