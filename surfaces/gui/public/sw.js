/**
 * Service Worker — cache-first for immutable assets (vendor chunks, fonts, CSS).
 *
 * Vite's hashed filenames (e.g. vendor-react-CL1w0_5e.js) are content-addressed:
 * if the hash changes the URL changes, so cached entries never go stale. The SW
 * intercepts fetches, serves from cache when available, and populates the cache
 * on first load. Non-asset requests (API, WebSocket, HTML) always go to network.
 */

const CACHE_NAME = "werubworker-assets-v1";

// Patterns that identify immutable, cache-worthy assets.
const CACHEABLE = [
  /\/assets\/vendor-.*\.js$/,
  /\/assets\/index-.*\.css$/,
  /\/assets\/.*\.woff2$/,
  /\/assets\/.*\.svg$/,
];

function isCacheable(url) {
  const path = new URL(url).pathname;
  return CACHEABLE.some((re) => re.test(path));
}

// Install: skip waiting so the new SW activates immediately.
self.addEventListener("install", () => self.skipWaiting());

// Activate: claim all clients + prune old caches.
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// Fetch: cache-first for immutable assets, network-only for everything else.
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  if (!isCacheable(event.request.url)) return;

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      });
    })
  );
});
