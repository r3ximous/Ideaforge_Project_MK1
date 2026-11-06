const CACHE_NAME = "altitude-pulse-shell-v1";
const SHELL = [
  "/",
  "/index.html",
  "/track.html",
  "/history.html",
  "/kds.html",
  "/assets/style.css",
  "/assets/icon.svg",
  "/assets/icon-192.png",
  "/assets/icon-512.png",
  "/js/shared.js",
  "/js/app.js",
  "/js/tracker.js",
  "/js/history.js",
  "/js/kds.js",
  "/manifest.webmanifest",
];
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) =>
        cache.addAll(
          SHELL.map(
            (path) =>
              new Request(path, { credentials: "omit", cache: "reload" }),
          ),
        ),
      ),
  );
});
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter(
              (key) =>
                key.startsWith("altitude-pulse-shell-") && key !== CACHE_NAME,
            )
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // An explicit shell-only allowlist: never intercept APIs, sockets, GLBs, CDN assets,
  // private response bodies, or POST requests. Query parameters are not cache keys.
  if (
    event.request.method !== "GET" ||
    url.origin !== self.location.origin ||
    !SHELL.includes(url.pathname)
  )
    return;
  event.respondWith(
    (async () => {
      const request = new Request(url.origin + url.pathname, {
        credentials: "omit",
        cache: "no-cache",
      });
      const cache = await caches.open(CACHE_NAME);
      try {
        const response = await fetch(request);
        if (response.ok && response.type === "basic")
          await cache.put(url.pathname, response.clone());
        return response;
      } catch {
        return (
          (await cache.match(url.pathname)) ||
          new Response(
            "The app shell is unavailable offline. Reconnect and reload Altitude Pulse.",
            {
              status: 503,
              headers: { "Content-Type": "text/plain; charset=utf-8" },
            },
          )
        );
      }
    })(),
  );
});
