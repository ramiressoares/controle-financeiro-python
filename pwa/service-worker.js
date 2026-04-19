// Service Worker - Controle Financeiro Web
// Este arquivo eh a referencia para deploy com reverse proxy na raiz.
// Em producao com proxy, copie o conteudo de ../static/sw.js e ajuste o scope.

const CACHE_NAME = 'controle-financeiro-v2';

const STATIC_ASSETS = [
  '/pwa/manifest.webmanifest?v=2',
  '/pwa/icon-192.png?v=2',
  '/pwa/icon-512.png?v=2',
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      cache.addAll(STATIC_ASSETS).catch(() => {})
    )
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.pathname === '/pwa/manifest.webmanifest') {
    event.respondWith(
      fetch(event.request, { cache: 'no-store' })
        .then((resp) => {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return resp;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }
  if (url.pathname.startsWith('/pwa/')) {
    event.respondWith(
      caches.match(event.request).then((cached) => cached || fetch(event.request))
    );
  }
});
