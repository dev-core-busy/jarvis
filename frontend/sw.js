/**
 * Jarvis Service Worker – PWA Offline-Cache
 * Cached statische Assets für Offline-Nutzung.
 */

const CACHE_NAME = 'jarvis-pwa-v1';

// Assets die beim Install gecacht werden
const PRECACHE_ASSETS = [
  '/chat.html',
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
      // Graceful: einzelne Fehler beim Precaching nicht abbrechen lassen
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

// ─── Activate ──────────────────────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
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

  // Network-First für HTML (immer aktuell), Cache-First für statische Assets
  const isHtml = url.pathname.endsWith('.html') || url.pathname === '/';
  const isStatic = url.pathname.startsWith('/static/');

  if (isHtml) {
    // Network-First: versuche zuerst netzwerk, fallback auf cache
    event.respondWith(
      fetch(event.request)
        .catch(() => caches.match(event.request))
    );
  } else if (isStatic) {
    // Cache-First: cache zuerst, dann netzwerk und cache aktualisieren
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
  event.waitUntil(clients.openWindow('/chat.html'));
});
