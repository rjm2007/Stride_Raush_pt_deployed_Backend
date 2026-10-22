import assert from 'node:assert/strict';
import test from 'node:test';
import { mutationTargets, QueryCache } from './query-cache.ts';

const SNAPSHOT = '/api/dashboard/snapshot';
const LEAD = '/api/dashboard/leads/abc-123';
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

test('concurrent reads of one key share a single request', async () => {
  const cache = new QueryCache();
  let calls = 0;
  const fetcher = async () => { calls += 1; return { n: calls }; };
  const [a, b] = await Promise.all([cache.fetch(SNAPSHOT, fetcher), cache.fetch(SNAPSHOT, fetcher)]);
  assert.equal(calls, 1);
  assert.equal(a, b);
});

test('a read within maxAge reuses the cached answer; an older one refetches', async () => {
  const cache = new QueryCache();
  let calls = 0;
  const fetcher = async () => ++calls;
  await cache.fetch(SNAPSHOT, fetcher);
  assert.equal(await cache.fetch(SNAPSHOT, fetcher, { maxAgeMs: 60_000 }), 1);
  assert.equal(await cache.fetch(SNAPSHOT, fetcher, { maxAgeMs: 0 }), 2);
});

test('every write creates a new entry object and notifies subscribers', async () => {
  const cache = new QueryCache();
  let notified = 0;
  cache.subscribe(SNAPSHOT, () => { notified += 1; });
  await cache.fetch(SNAPSHOT, async () => 'one');
  const first = cache.get(SNAPSHOT);
  cache.set(SNAPSHOT, 'two');
  assert.notEqual(cache.get(SNAPSHOT), first);
  assert.equal(cache.get(SNAPSHOT)?.data, 'two');
  assert.ok(notified >= 3);
});

test('errors keep the last good data and clear on the next success', async () => {
  const cache = new QueryCache();
  await cache.fetch(SNAPSHOT, async () => 'good');
  await assert.rejects(cache.fetch(SNAPSHOT, async () => { throw new Error('offline'); }));
  assert.equal(cache.get(SNAPSHOT)?.data, 'good');
  assert.ok(cache.get(SNAPSHOT)?.error);
  await cache.fetch(SNAPSHOT, async () => 'fresh');
  assert.equal(cache.get(SNAPSHOT)?.error, undefined);
});

test('invalidation refetches keys on screen at once and the rest on next read', async () => {
  const cache = new QueryCache();
  let leadCalls = 0;
  let snapshotCalls = 0;
  const leadFetcher = async () => ++leadCalls;
  const snapshotFetcher = async () => ++snapshotCalls;
  cache.setFetcher(LEAD, leadFetcher);
  cache.setFetcher(SNAPSHOT, snapshotFetcher);
  await cache.fetch(LEAD, leadFetcher);
  await cache.fetch(SNAPSHOT, snapshotFetcher);
  cache.subscribe(LEAD, () => {});
  cache.invalidateForMutation('/api/dashboard/leads/abc-123/cadence', 'POST');
  await tick();
  assert.equal(leadCalls, 2, 'mounted lead refetched');
  assert.equal(snapshotCalls, 1, 'unmounted snapshot only marked stale');
  assert.equal(cache.get(SNAPSHOT)?.stale, true);
  // A stale entry is never served from cache, whatever maxAge says.
  assert.equal(await cache.fetch(SNAPSHOT, snapshotFetcher, { maxAgeMs: 60_000 }), 2);
});

test('a request started before a write cannot overwrite the data after it', async () => {
  const cache = new QueryCache();
  const old = deferred<string>();
  const before = cache.fetch(LEAD, () => old.promise);
  cache.invalidate((key) => key === LEAD);
  await cache.fetch(LEAD, async () => 'after write');
  old.resolve('before write');
  await before;
  assert.equal(cache.get(LEAD)?.data, 'after write');
});

test('clear and a user change drop everything, and late answers for the old user are ignored', async () => {
  const cache = new QueryCache();
  cache.setScope('alice');
  await cache.fetch(SNAPSHOT, async () => 'alice data');
  const late = deferred<string>();
  const pending = cache.fetch(LEAD, () => late.promise);
  cache.setScope('bob');
  assert.equal(cache.get(SNAPSHOT), undefined);
  late.resolve('alice lead');
  await pending;
  assert.equal(cache.get(LEAD), undefined);
  cache.setScope('bob');
  await cache.fetch(SNAPSHOT, async () => 'bob data');
  cache.clear();
  assert.equal(cache.get(SNAPSHOT), undefined);
});

test('seed never overwrites data and prefetch never throws', async () => {
  const cache = new QueryCache();
  await cache.fetch(LEAD, async () => 'server');
  cache.seed(LEAD, 'row');
  assert.equal(cache.get(LEAD)?.data, 'server');
  cache.prefetch('/api/dashboard/leads/other', async () => { throw new Error('down'); });
  await tick();
});

test('deleting a lead drops its record instead of refetching it', async () => {
  const cache = new QueryCache();
  let calls = 0;
  const fetcher = async () => ++calls;
  cache.setFetcher(LEAD, fetcher);
  cache.subscribe(LEAD, () => {});
  await cache.fetch(LEAD, fetcher);
  cache.invalidateForMutation(LEAD, 'DELETE');
  await tick();
  assert.equal(cache.get(LEAD), undefined);
  assert.equal(calls, 1);
});

test('each staff action invalidates the reads it can change', () => {
  const blocked = '/api/dashboard/blocked-numbers';
  const versions = '/api/dashboard/cadence-versions';
  for (const action of ['cadence', 'stage', 'contact-rules', 'sms', 'outreach-events/7']) {
    assert.deepEqual(mutationTargets(`/api/dashboard/leads/abc-123/${action}`, 'POST').keys, [SNAPSHOT, LEAD, blocked], action);
  }
  assert.deepEqual(mutationTargets('/api/dashboard/review/abc-123/resolve', 'POST').keys, [SNAPSHOT, LEAD, '/api/dashboard/blocked-numbers']);
  assert.deepEqual(mutationTargets('/api/dashboard/blocked-numbers/unblock', 'POST'), { keys: [SNAPSHOT, blocked], prefixes: ['/api/dashboard/leads/'], drop: [] });
  assert.deepEqual(mutationTargets('/api/dashboard/cadence-versions/3/activate', 'POST').keys, [SNAPSHOT, versions]);
  assert.deepEqual(mutationTargets('/api/dashboard/cadence-steps/9', 'PATCH').keys, [SNAPSHOT, versions]);
  assert.deepEqual(mutationTargets('/api/dashboard/message-templates/2', 'PATCH').keys, [SNAPSHOT, versions]);
  assert.deepEqual(mutationTargets('/api/dashboard/assistant/stream', 'POST').keys, []);
  assert.deepEqual(mutationTargets('/api/dashboard/something-new', 'POST').keys, [SNAPSHOT]);
});
