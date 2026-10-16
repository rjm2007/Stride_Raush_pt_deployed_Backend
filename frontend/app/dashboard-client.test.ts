import assert from 'node:assert/strict';
import test from 'node:test';
import { dashboardFetch } from './dashboard-client.ts';

test('dashboard requests preserve errors and redirect expired sessions without retrying writes', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  let redirects = 0;
  let requests = 0;
  globalThis.window = { location: { assign: (url: string) => { assert.equal(url, '/login'); redirects += 1; } } } as unknown as Window & typeof globalThis;
  try {
    for (const status of [200, 403, 503, 401]) {
      globalThis.fetch = async (_url, options) => {
        requests += 1;
        assert.equal(options?.cache, 'no-store');
        assert.equal(options?.method, 'POST');
        return new Response(null, { status });
      };
      if (status === 401) await assert.rejects(dashboardFetch('/api/dashboard/leads', { method: 'POST' }), /session has expired/);
      else assert.equal((await dashboardFetch('/api/dashboard/leads', { method: 'POST' })).status, status);
    }
    assert.equal(requests, 4);
    assert.equal(redirects, 1);
    globalThis.fetch = async () => { throw new TypeError('Network unavailable'); };
    await assert.rejects(dashboardFetch('/api/dashboard/snapshot'), /Network unavailable/);
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.window = originalWindow;
  }
});
