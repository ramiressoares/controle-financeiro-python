// Service Worker - Controle Financeiro Web
// Este arquivo eh a referencia para deploy com reverse proxy na raiz.
// Em producao com proxy, copie o conteudo de ../static/sw.js e ajuste o scope.

const CACHE_NAME = 'controle-financeiro-v1';

const STATIC_ASSETS = [
  '/app/static/manifest.webmanifest',
  '/app/static/icon-192.png',
  '/app/static/icon-512.png',
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
  if (url.pathname.startsWith('/app/static/')) {
    event.respondWith(
      caches.match(event.request).then((cached) => cached || fetch(event.request))
    );
  }
});
