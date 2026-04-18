// Placeholder para evolucao PWA futura.
// Streamlit nao registra service worker por padrao.
// Em futura etapa, use um reverse proxy/frontend shell para registro.
self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});
