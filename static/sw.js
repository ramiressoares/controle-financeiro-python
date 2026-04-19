// Service Worker - Controle Financeiro Web
// Cacheia assets estaticos para funcionamento offline basico e velocidade.

const CACHE_NAME = 'controle-financeiro-v1';

// Assets estaticos proprios da PWA
const STATIC_ASSETS = [
  '/app/static/manifest.webmanifest',
  '/app/static/icon-192.png',
  '/app/static/icon-512.png',
];

// ── Install: pre-cacheia assets estaticos ─────────────────────────────────────
self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      cache.addAll(STATIC_ASSETS).catch(() => {
        // Ignora falha de pre-cache (icones podem nao existir ainda)
      })
    )
  );
});

// ── Activate: remove caches antigos ───────────────────────────────────────────
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

// ── Fetch: cache-first para assets estaticos, network-first para o resto ──────
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  const url = new URL(event.request.url);

  // Cache-first apenas para os proprios assets estaticos da PWA
  if (url.pathname.startsWith('/app/static/')) {
    event.respondWith(
      caches
        .match(event.request)
        .then((cached) => cached || fetch(event.request).then((resp) => {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return resp;
        }))
    );
    return;
  }

  // Para tudo mais (Streamlit app), usa apenas rede
  // Nao interfere no funcionamento normal do Streamlit
});
