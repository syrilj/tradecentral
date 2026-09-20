/**
 * TradeCentral Cloudflare Worker.
 *
 * Serves the built Vue SPA as static assets and proxies `/api/*` to the
 * TradeCentral Python API server running behind a Cloudflare Tunnel.
 *
 * The Python backend cannot run on Workers (pandas, local parquet, threaded
 * scan jobs), so the Worker acts as a thin reverse proxy. The tunnel hostname
 * is configured via the `API_UPSTREAM` environment variable in wrangler.toml.
 *
 * Deploy with:
 *   npx wrangler deploy
 *
 * Prerequisites:
 *   - cloudflared tunnel running locally (see setup_tunnel.sh)
 *   - API server bound to 127.0.0.1:8787 (tools/run_dashboard.sh --serve)
 *   - Cloudflare Access application gating this Worker hostname
 */

const SPA_ROUTES = new Set([
  "/",
  "/flow",
  "/auth",
]);

// File extensions that map directly to static assets; anything else that
// looks like a route (no dot in the last path segment) falls back to the SPA.
function isStaticAsset(path) {
  const last = path.split("/").pop() ?? "";
  return last.includes(".");
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Proxy API calls to the tunnel origin.
    if (url.pathname.startsWith("/api/")) {
      if (!env.API_UPSTREAM) {
        return Response.json(
          { error: "API_UPSTREAM not configured — set the tunnel hostname in wrangler.toml" },
          { status: 503 },
        );
      }
      const upstream = new URL(request.url);
      upstream.hostname = env.API_UPSTREAM;
      upstream.port = "";
      upstream.protocol = "https:";

      const proxyRequest = new Request(upstream, request);
      proxyRequest.headers.set("X-Forwarded-Host", url.hostname);
      proxyRequest.headers.set("X-Forwarded-Proto", "https");

      return fetch(proxyRequest);
    }

    // Serve the SPA via Workers Assets for known routes and static files.
    // Everything else that is not a static asset falls back to index.html
    // so client-side routing works on refresh.
    if (isStaticAsset(url.pathname) || SPA_ROUTES.has(url.pathname)) {
      return env.ASSETS.fetch(request);
    }

    // Unknown route: serve the SPA shell and let the Vue router handle it.
    const indexUrl = new URL("/index.html", url.origin);
    return env.ASSETS.fetch(new Request(indexUrl, request));
  },
};
