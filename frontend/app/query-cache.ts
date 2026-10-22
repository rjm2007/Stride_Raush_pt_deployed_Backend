// In-memory stale-while-revalidate cache for the dashboard's GET requests (browser only).
//
// Why: every screen used to refetch the whole snapshot on each click and flash a skeleton. Reads now
// return the last answer at once and refresh it in the background.
//
// Patient data rule: entries live in this module's memory only. Nothing is written to localStorage,
// sessionStorage or IndexedDB, so a reload, a sign-out (full page load) or a closed tab drops it all.
// The cache is also scoped to the signed-in staff member and cleared on a 401.
//
// Keys are the proxy paths the browser requests (e.g. `/api/dashboard/leads/<id>`), so a write knows
// which reads it can have changed (see `mutationTargets`).

export type CacheEntry<T = unknown> = {
  data?: T;
  error?: unknown;
  updatedAt: number;
  validating: boolean;
  stale: boolean;
};

type Fetcher<T = unknown> = () => Promise<T>;

export const DASHBOARD_PREFIX = '/api/dashboard/';

// Which cached reads a successful write can change. Kept narrow on purpose: refetching everything after
// each click would send a burst of requests to the backend.
export function mutationTargets(path: string, method: string): { keys: string[]; prefixes: string[]; drop: string[] } {
  const relative = path.split('?')[0].replace(/^\/api\/dashboard\//, '').replace(/^\/+/, '');
  const key = (value: string) => `${DASHBOARD_PREFIX}${value}`;
  const snapshot = key('snapshot');
  const blocked = key('blocked-numbers');
  const versions = key('cadence-versions');
  const lead = relative.match(/^leads\/([0-9a-f-]+)(\/.*)?$/i);
  if (lead) {
    const detail = key(`leads/${lead[1]}`);
    // A deleted lead has nothing left to refetch; dropping it avoids a pointless 404.
    if (!lead[2] && method.toUpperCase() === 'DELETE') return { keys: [snapshot, blocked], prefixes: [], drop: [detail] };
    // Do not contact / unblock change the blocked-number list as well as the lead.
    return { keys: [snapshot, detail, blocked], prefixes: [], drop: [] };
  }
  const review = relative.match(/^review\/([0-9a-f-]+)\/resolve$/i);
  if (review) return { keys: [snapshot, key(`leads/${review[1]}`)], prefixes: [], drop: [] };
  // Unblocking by number can touch every lead on that number.
  if (/^blocked-numbers/i.test(relative)) return { keys: [snapshot, blocked], prefixes: [key('leads/')], drop: [] };
  // The snapshot carries the active cadence and the templates, so both studios refresh it too.
  if (/^(cadence-versions|cadence-steps|message-templates)/i.test(relative)) return { keys: [snapshot, versions], prefixes: [], drop: [] };
  // The assistant only reads.
  if (/^assistant/i.test(relative)) return { keys: [], prefixes: [], drop: [] };
  // Unknown write: refresh the snapshot rather than risk stale data on screen.
  return { keys: [snapshot], prefixes: [], drop: [] };
}

export class QueryCache {
  private entries = new Map<string, CacheEntry>();
  private listeners = new Map<string, Set<() => void>>();
  private fetchers = new Map<string, Fetcher>();
  private inflight = new Map<string, { promise: Promise<unknown>; epoch: number }>();
  // Bumped per key by invalidate/drop: a request started before a write cannot overwrite newer data.
  private epochs = new Map<string, number>();
  // Bumped by clear(): a request started for the previous user can never write into the new cache.
  private generation = 0;
  private scope: string | null = null;

  get<T>(key: string): CacheEntry<T> | undefined {
    return this.entries.get(key) as CacheEntry<T> | undefined;
  }

  subscribe(key: string, listener: () => void): () => void {
    const set = this.listeners.get(key) ?? new Set();
    set.add(listener);
    this.listeners.set(key, set);
    return () => {
      set.delete(listener);
      if (!set.size) this.listeners.delete(key);
    };
  }

  setFetcher(key: string, fetcher: Fetcher): void {
    this.fetchers.set(key, fetcher);
  }

  /** Cached data if it is younger than maxAgeMs and not stale; otherwise one shared request. */
  fetch<T>(key: string, fetcher: Fetcher<T>, { maxAgeMs = 0 }: { maxAgeMs?: number } = {}): Promise<T> {
    const entry = this.entries.get(key) as CacheEntry<T> | undefined;
    const epoch = this.epochs.get(key) ?? 0;
    if (entry && entry.data !== undefined && !entry.stale && !entry.error && Date.now() - entry.updatedAt < maxAgeMs) {
      return Promise.resolve(entry.data);
    }
    const running = this.inflight.get(key);
    if (running && running.epoch === epoch) return running.promise as Promise<T>;

    const generation = this.generation;
    const current = () => generation === this.generation && epoch === (this.epochs.get(key) ?? 0);
    this.write(key, { ...(entry ?? { updatedAt: 0, stale: false }), validating: true });
    // Started on a microtask, so a fetcher that throws synchronously still settles through the same path.
    const promise = Promise.resolve().then(fetcher).then(
      (data) => {
        if (current()) this.write(key, { data, error: undefined, updatedAt: Date.now(), validating: false, stale: false });
        return data;
      },
      (error: unknown) => {
        if (current()) this.write(key, { ...(this.entries.get(key) ?? { updatedAt: 0, stale: false }), error, validating: false });
        throw error;
      },
    ).finally(() => {
      if (this.inflight.get(key)?.promise === promise) this.inflight.delete(key);
    });
    this.inflight.set(key, { promise, epoch });
    return promise;
  }

  /** Background fetch that never throws; skipped while the entry is younger than maxAgeMs. */
  prefetch(key: string, fetcher: Fetcher, maxAgeMs = 15_000): void {
    this.setFetcher(key, fetcher);
    void this.fetch(key, fetcher, { maxAgeMs }).catch(() => {});
  }

  /** Optimistic update after a write. A refetch already running was started by that write's
   * invalidation, so it is newer than this guess and is allowed to replace it with the server's answer. */
  set<T>(key: string, next: T | ((previous: T | undefined) => T)): void {
    const previous = this.entries.get(key)?.data as T | undefined;
    const data = typeof next === 'function' ? (next as (previous: T | undefined) => T)(previous) : next;
    this.write(key, { data, error: undefined, updatedAt: Date.now(), validating: this.inflight.has(key), stale: false });
  }

  /** Pre-fill a key without ever overwriting data that is already there. */
  seed<T>(key: string, data: T): void {
    if (this.entries.get(key)?.data !== undefined) return;
    this.write(key, { data, updatedAt: 0, validating: false, stale: true });
  }

  /** Marks keys stale; keys on screen refetch now, the rest on their next read. */
  invalidate(match: (key: string) => boolean): void {
    for (const [key, entry] of [...this.entries]) {
      if (!match(key)) continue;
      this.bump(key);
      this.inflight.delete(key);
      this.write(key, { ...entry, validating: false, stale: true });
      const fetcher = this.fetchers.get(key);
      if (fetcher && this.listeners.get(key)?.size) void this.fetch(key, fetcher).catch(() => {});
    }
  }

  invalidateForMutation(path: string, method: string): void {
    const { keys, prefixes, drop } = mutationTargets(path, method);
    drop.forEach((key) => this.drop(key));
    if (!keys.length && !prefixes.length) return;
    this.invalidate((key) => keys.includes(key) || prefixes.some((prefix) => key.startsWith(prefix)));
  }

  drop(key: string): void {
    this.bump(key);
    this.inflight.delete(key);
    this.fetchers.delete(key);
    if (this.entries.delete(key)) this.notify(key);
  }

  /** Drops everything when the signed-in staff member changes. */
  setScope(scope: string): void {
    if (this.scope !== null && this.scope !== scope) this.clear();
    this.scope = scope;
  }

  /** Forget every entry (sign-out, 401, user change). */
  clear(): void {
    this.generation += 1;
    const keys = [...this.entries.keys()];
    this.entries.clear();
    this.inflight.clear();
    this.fetchers.clear();
    this.epochs.clear();
    keys.forEach((key) => this.notify(key));
  }

  private bump(key: string) {
    this.epochs.set(key, (this.epochs.get(key) ?? 0) + 1);
  }

  // A new object on every write: useSyncExternalStore compares snapshots by identity.
  private write(key: string, entry: CacheEntry) {
    this.entries.set(key, { ...entry });
    this.notify(key);
  }

  private notify(key: string) {
    this.listeners.get(key)?.forEach((listener) => listener());
  }
}

// One instance per browser tab. The server never imports a reader of it (every user is a client
// component that only fetches in effects), so it cannot mix data between requests on the server.
export const queryCache = new QueryCache();
