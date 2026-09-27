import assert from 'node:assert/strict';
import test from 'node:test';
import worker from './worker.js';

const origin = 'https://tradecentral.example.com';

function assets() {
  return {
    async fetch(request) {
      return new Response(request.url, { status: 200 });
    },
  };
}

function apiRequest(path = '/api/health', init = {}) {
  return new Request(`${origin}${path}`, {
    ...init,
    headers: { Origin: origin, ...init.headers },
  });
}

test('the default Worker deployment never fetches an API upstream', async () => {
  const originalFetch = globalThis.fetch;
  let fetched = false;
  globalThis.fetch = async () => {
    fetched = true;
    throw new Error('unexpected upstream fetch');
  };

  try {
    const result = await worker.fetch(apiRequest(), { ASSETS: assets() });
    assert.equal(result.status, 503);
    assert.equal(fetched, false);
    assert.match(await result.text(), /disabled/i);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('an enabled proxy fails closed when either exact HTTPS origin is malformed', async () => {
  const originalFetch = globalThis.fetch;
  let fetched = false;
  globalThis.fetch = async () => {
    fetched = true;
    throw new Error('unexpected upstream fetch');
  };

  try {
    const result = await worker.fetch(apiRequest(), {
      ASSETS: assets(),
      API_PROXY_ENABLED: 'true',
      PUBLIC_ORIGIN: origin,
      API_UPSTREAM: 'https://api.example.com/not-an-origin',
    });
    assert.equal(result.status, 503);
    assert.equal(fetched, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('an enabled proxy rejects a request made through another Worker hostname', async () => {
  const originalFetch = globalThis.fetch;
  let fetched = false;
  globalThis.fetch = async () => {
    fetched = true;
    throw new Error('unexpected upstream fetch');
  };

  try {
    const request = new Request('https://preview.workers.dev/api/health', {
      headers: { Origin: origin },
    });
    const result = await worker.fetch(request, {
      ASSETS: assets(),
      API_PROXY_ENABLED: 'true',
      PUBLIC_ORIGIN: origin,
      API_UPSTREAM: 'https://api.example.com',
    });
    assert.equal(result.status, 403);
    assert.equal(fetched, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('an enabled proxy forwards only the Clerk bearer token and safe request headers', async () => {
  const originalFetch = globalThis.fetch;
  let received;
  globalThis.fetch = async (url, init) => {
    received = { url: String(url), init };
    return new Response('{"ok":true}', { headers: { 'Content-Type': 'application/json' } });
  };

  try {
    const result = await worker.fetch(
      apiRequest('/api/health?full=1', {
        headers: {
          Authorization: 'Bearer clerk-token',
          Cookie: 'session=do-not-forward',
          Referer: 'https://attacker.example',
          'X-Forwarded-Host': 'attacker.example',
        },
      }),
      {
        ASSETS: assets(),
        API_PROXY_ENABLED: 'true',
        PUBLIC_ORIGIN: origin,
        API_UPSTREAM: 'https://api.example.com',
      },
    );
    assert.equal(result.status, 200);
    assert.equal(received.url, 'https://api.example.com/api/health?full=1');
    assert.equal(received.init.headers.get('Authorization'), 'Bearer clerk-token');
    assert.equal(received.init.headers.get('Cookie'), null);
    assert.equal(received.init.headers.get('Referer'), null);
    assert.equal(received.init.headers.get('X-Forwarded-Host'), 'tradecentral.example.com');
    assert.equal(result.headers.get('Cache-Control'), 'no-store');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('same-origin GET works without Origin, while a POST without Origin is blocked', async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({ ok: true });
  };
  const env = {
    ASSETS: assets(),
    API_PROXY_ENABLED: 'true',
    PUBLIC_ORIGIN: origin,
    API_UPSTREAM: 'https://api.example.com',
  };
  try {
    const get = await worker.fetch(new Request(`${origin}/api/status`), env);
    const post = await worker.fetch(new Request(`${origin}/api/trigger_scan`, { method: 'POST' }), env);
    assert.equal(get.status, 200);
    assert.equal(post.status, 403);
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('the static waitlist stays available without API configuration', async () => {
  const result = await worker.fetch(new Request(`${origin}/waitlist`), { ASSETS: assets() });
  assert.equal(result.status, 200);
  assert.equal(await result.text(), `${origin}/index.html`);
  assert.equal(result.headers.get('X-Frame-Options'), 'DENY');
});
