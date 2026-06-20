/**
 * Jarvis Service Worker – PWA Offline-Cache
 * Cached statische Assets für Offline-Nutzung.
 */

const CACHE_NAME = 'jarvis-pwa-v4';

// Nur wirklich cachbare statische Assets (kein HTML – Server setzt no-store)
const PRECACHE_ASSETS = [
  '/static/css/chat.css',
  '/static/js/chat.js',
  '/static/js/websocket.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

// ─── Install ───────────────────────────────────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return Promise.allSettled(
        PRECACHE_ASSETS.map((url) =>
          cache.add(url).catch((err) => {
            console.warn('[SW] Konnte nicht cachen:', url, err);
          })
        )
      );
    })
  );
  self.skipWaiting();
});

// ─── Activate: alte Caches löschen + Clients sofort neu laden ──────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    ).then(() => {
      // Alle offenen Fenster nach SW-Update neu laden (löscht stale State)
      return self.clients.matchAll({ type: 'window' }).then((clients) => {
        clients.forEach((c) => c.navigate(c.url));
      });
    })
  );
  self.clients.claim();
});

// ─── Fetch ─────────────────────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API- und WebSocket-Requests NICHT cachen
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws')) {
    return;
  }

  const isHtml = url.pathname.endsWith('.html') || url.pathname === '/' || url.pathname === '/chat';
  const isStatic = url.pathname.startsWith('/static/');
  // JS/CSS IMMER frisch laden (Network-First). Cache-First hatte zu stale
  // Assets gefuehrt (alte CSS/JS trotz neuem ?v). Bilder/Icons bleiben Cache-First.
  const isCode = isStatic && /\.(js|css)(\?|$)/.test(url.pathname + url.search);

  if (isHtml || isCode) {
    // Network-First: frisch holen, bei Offline Fallback auf Cache; Cache aktualisieren.
    event.respondWith(
      fetch(event.request).then((response) => {
        if (response && response.status === 200 && isCode) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => caches.match(event.request))
    );
  } else if (isStatic) {
    // Cache-First nur fuer selten wechselnde Assets (Bilder/Icons/Fonts).
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request).then((response) => {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        });
      })
    );
  }
});

// ─── Push-Benachrichtigungen (vorbereitet) ─────────────────────────────────
self.addEventListener('push', (event) => {
  if (!event.data) return;
  const data = event.data.json();
  self.registration.showNotification(data.title || 'Jarvis', {
    body: data.body || '',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-192.png',
    tag: 'jarvis-notification',
    renotify: true,
  });
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow('/chat'));
});
