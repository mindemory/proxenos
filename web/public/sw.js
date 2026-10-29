// Proxenos's service worker. It exists so Chrome offers "Install app" (on desktop and Android),
// which wants a worker with a fetch handler, and it does almost nothing else.
//
// Pages: always from the network, so the app is never out of date. Only when the network is
// down is a short page shown that says so. Everything else (scripts, styles, images, and above
// all /api, which is your own data) is left to the browser: nothing here is ever cached.

const OFFLINE = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Proxenos</title>
<style>
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px;
    background: #0e1013; color: #ece9e3; font: 16px/1.5 system-ui, sans-serif; text-align: center; }
  p { margin: 0 0 16px; color: #9ea4af; }
  button { padding: 8px 18px; border: 0; border-radius: 999px; background: #a3b1ff; color: #0d1020; font: inherit; }
</style>
</head>
<body>
  <main>
    <h1>Can't reach Proxenos</h1>
    <p>Your computer is off or asleep, or Tailscale isn't connected.</p>
    <button onclick="location.reload()">Try again</button>
  </main>
</body>
</html>`;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  // Not a page: no respondWith, so the browser fetches it as if this worker weren't here.
  if (event.request.mode !== "navigate") return;
  event.respondWith(
    fetch(event.request).catch(
      () => new Response(OFFLINE, { status: 503, headers: { "content-type": "text/html; charset=utf-8" } }),
    ),
  );
});
