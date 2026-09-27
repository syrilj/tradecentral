/**
 * TradeCentral Cloudflare Worker.
 *
 * The production-safe default is a static Clerk-protected SPA. It deliberately
 * does not expose the local research API: a public Worker-to-tunnel proxy can
 * otherwise turn unauthenticated requests into expensive provider calls.
 *
 * A staging proxy is an explicit, fail-closed exception. It only starts when
 * API_PROXY_ENABLED=true and both PUBLIC_ORIGIN and API_UPSTREAM are exact
 * HTTPS origins. The Python API remains responsible for validating Clerk JWTs
 * and the operator allowlist, including requests that reach a tunnel directly.
 */

const STATIC_METHODS = new Set(['GET', 'HEAD']);
const API_METHODS = new Set(['GET', 'HEAD', 'POST']);
const FORWARDED_HEADERS = ['accept', 'authorization', 'content-type'];

const SECURITY_HEADERS = {
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Permissions-Policy': 'camera=(), geolocation=(), microphone=()',
};

function isStaticAsset(pathname) {
  const last = pathname.split('/').pop() ?? '';
  return last.includes('.');
}

function response(body, init = {}) {
  const headers = new Headers(init.headers);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    headers.set(name, value);
  }
  return new Response(body, { ...init, headers });
}

function json(body, init = {}) {
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json; charset=utf-8');
  headers.set('Cache-Control', 'no-store');
  return response(JSON.stringify(body), { ...init, headers });
}

function parseExactHttpsOrigin(value) {
  if (typeof value !== 'string' || !value.trim()) return null;

  try {
    const url = new URL(value);
    if (
      url.protocol !== 'https:' ||
      url.username ||
      url.password ||
      url.pathname !== '/' ||
      url.search ||
      url.hash
    ) {
      return null;
    }
    return url;
  } catch {
    return null;
  }
}

function apiConfiguration(env) {
  if (env.API_PROXY_ENABLED !== 'true') return null;

  const publicOrigin = parseExactHttpsOrigin(env.PUBLIC_ORIGIN);
  const upstream = parseExactHttpsOrigin(env.API_UPSTREAM);
  if (!publicOrigin || !upstream) return null;

  return { publicOrigin, upstream };
}

function configuredRequestHeaders(request, publicOrigin) {
  const headers = new Headers();
  for (const name of FORWARDED_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set('X-Forwarded-Host', publicOrigin.host);
  headers.set('X-Forwarded-Proto', 'https');
  return headers;
}

function withSecurityHeaders(upstreamResponse, noStore = false) {
  const headers = new Headers(upstreamResponse.headers);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    headers.set(name, value);
  }
  if (noStore) headers.set('Cache-Control', 'no-store');
  return new Response(upstreamResponse.body, {
    status: upstreamResponse.status,
    statusText: upstreamResponse.statusText,
    headers,
  });
}

async function proxyApi(request, requestUrl, env) {
  const config = apiConfiguration(env);
  if (!config) {
    return json(
      { error: 'Research API is disabled for this deployment.' },
      { status: 503 },
    );
  }

  // Origin is an extra browser-side boundary, while the API itself validates
  // the Clerk bearer token. It prevents a misrouted Worker hostname from ever
  // becoming a permissive public proxy.
  const requestOrigin = request.headers.get('Origin');
  if (
    requestUrl.origin !== config.publicOrigin.origin ||
    (requestOrigin && requestOrigin !== config.publicOrigin.origin) ||
    (request.method === 'POST' && requestOrigin !== config.publicOrigin.origin)
  ) {
    return json({ error: 'API request origin is not allowed.' }, { status: 403 });
  }

  if (!API_METHODS.has(request.method)) {
    return json(
      { error: 'Method is not allowed for the research API.' },
      { status: 405, headers: { Allow: 'GET, HEAD, POST' } },
    );
  }

  const upstreamUrl = new URL(requestUrl.pathname + requestUrl.search, config.upstream);
  const init = {
    method: request.method,
    headers: configuredRequestHeaders(request, config.publicOrigin),
    redirect: 'manual',
  };
  if (!STATIC_METHODS.has(request.method)) init.body = request.body;

  return withSecurityHeaders(await fetch(upstreamUrl, init), true);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === '/api' || url.pathname.startsWith('/api/')) {
      return proxyApi(request, url, env);
    }

    if (!STATIC_METHODS.has(request.method)) {
      return response('Method Not Allowed', {
        status: 405,
        headers: { Allow: 'GET, HEAD', 'Cache-Control': 'no-store' },
      });
    }

    if (!env.ASSETS || typeof env.ASSETS.fetch !== 'function') {
      return response('Static assets are not configured.', {
        status: 503,
        headers: { 'Cache-Control': 'no-store' },
      });
    }

    // Assets supplies SPA fallback through wrangler's configured asset handler.
    // Explicitly keep unknown client routes in the shell as a defense against
    // stale deployments with a different asset fallback setting.
    const assetRequest =
      isStaticAsset(url.pathname) || url.pathname === '/'
        ? request
        : new Request(new URL('/index.html', url.origin), request);
    return withSecurityHeaders(await env.ASSETS.fetch(assetRequest));
  },
};
