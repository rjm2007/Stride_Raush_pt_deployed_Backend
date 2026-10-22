import assert from 'node:assert/strict';
import test from 'node:test';
import { dashboardFetch } from './dashboard-client.ts';
import { queryCache } from './query-cache.ts';

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
    // A successful write makes its cached reads stale; a failed write or a read leaves them alone.
    queryCache.set('/api/dashboard/snapshot', 'cached');
    globalThis.fetch = async (_url, options) => new Response(null, { status: options?.method === 'POST' ? 500 : 200 });
    await dashboardFetch('/api/dashboard/leads/abc-123/stage', { method: 'POST' });
    await dashboardFetch('/api/dashboard/snapshot');
    assert.equal(queryCache.get('/api/dashboard/snapshot')?.stale, false);
    globalThis.fetch = async () => new Response(null, { status: 200 });
    await dashboardFetch('/api/dashboard/leads/abc-123/stage', { method: 'POST' });
    assert.equal(queryCache.get('/api/dashboard/snapshot')?.stale, true);
    // An expired session forgets everything cached, including assistant chats.
    const removed: string[] = [];
    Object.assign(globalThis, { sessionStorage: { removeItem: (key: string) => removed.push(key) } });
    globalThis.fetch = async () => new Response(null, { status: 401 });
    await assert.rejects(dashboardFetch('/api/dashboard/snapshot'), /session has expired/);
    assert.equal(queryCache.get('/api/dashboard/snapshot'), undefined);
    assert.deepEqual(removed, ['rpt-assistant-session-chats']);
    delete (globalThis as { sessionStorage?: unknown }).sessionStorage;
    globalThis.fetch = async () => { throw new TypeError('Network unavailable'); };
    await assert.rejects(dashboardFetch('/api/dashboard/snapshot'), /Network unavailable/);
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.window = originalWindow;
  }
});
