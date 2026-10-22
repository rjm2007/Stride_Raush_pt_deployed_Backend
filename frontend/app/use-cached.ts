'use client';

import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react';
import { dashboardGet } from './dashboard-client';
import { DASHBOARD_PREFIX, queryCache, type CacheEntry } from './query-cache';
import type { CadenceVersion, LeadDetail, Snapshot } from './dashboard-data';

export type BlockedNumber = {
  phone: string;
  reason: string | null;
  source: string | null;
  blocked_at: string;
  leads: Array<{ id: string; full_name: string; status: string }>;
  open_lead_id: string | null;
};

// One key and one fetcher per resource, so a hover prefetch and the screen that later reads the
// data share the same cache entry.
export const cacheKeys = {
  snapshot: `${DASHBOARD_PREFIX}snapshot`,
  lead: (id: string) => `${DASHBOARD_PREFIX}leads/${id}`,
  blockedNumbers: `${DASHBOARD_PREFIX}blocked-numbers`,
  cadenceVersions: `${DASHBOARD_PREFIX}cadence-versions`,
};

export const cachedFetchers = {
  snapshot: () => dashboardGet<Snapshot>(cacheKeys.snapshot),
  lead: (id: string) => () => dashboardGet<LeadDetail>(cacheKeys.lead(id)),
  blockedNumbers: () => dashboardGet<{ numbers: BlockedNumber[] }>(cacheKeys.blockedNumbers),
  cadenceVersions: () => dashboardGet<{ versions: CadenceVersion[] }>(cacheKeys.cadenceVersions),
};

const noSubscription = () => () => {};
const noEntry = () => undefined;

// Stale-while-revalidate read. Cached data renders on the first render (no skeleton on a revisit),
// and a background request refreshes it. `key = null` turns the query off.
export function useCached<T>(key: string | null, fetcher: () => Promise<T>, { dedupeMs = 2_000, refreshMs }: { dedupeMs?: number; refreshMs?: number } = {}) {
  const fetcherRef = useRef(fetcher);
  useEffect(() => { fetcherRef.current = fetcher; });
  const subscribe = useCallback((listener: () => void) => (key ? queryCache.subscribe(key, listener) : () => {}), [key]);
  const getEntry = useCallback(() => (key ? queryCache.get<T>(key) : undefined), [key]);
  const entry = useSyncExternalStore<CacheEntry<T> | undefined>(key ? subscribe : noSubscription, getEntry, noEntry);

  useEffect(() => {
    if (!key) return;
    const run = () => fetcherRef.current();
    queryCache.setFetcher(key, run);
    // Each visit refreshes the cached answer quietly (within dedupeMs it is reused as is).
    void queryCache.fetch(key, run, { maxAgeMs: dedupeMs }).catch(() => {});
    if (!refreshMs) return;
    // Quiet poll only while the tab is visible, plus a refresh when staff come back to it.
    const refresh = () => { if (!document.hidden) void queryCache.fetch(key, run, { maxAgeMs: dedupeMs }).catch(() => {}); };
    const interval = window.setInterval(refresh, refreshMs);
    document.addEventListener('visibilitychange', refresh);
    return () => { window.clearInterval(interval); document.removeEventListener('visibilitychange', refresh); };
  }, [key, dedupeMs, refreshMs]);

  // Stable identities, so screens can list them as effect dependencies.
  const mutate = useCallback((next: T | ((previous: T | undefined) => T)) => { if (key) queryCache.set<T>(key, next); }, [key]);
  const revalidate = useCallback(() => (key ? queryCache.fetch(key, () => fetcherRef.current()).catch(() => undefined) : Promise.resolve(undefined)), [key]);

  return {
    data: entry?.data,
    error: entry?.error,
    // Only true before anything is cached: skeletons never show during a background refresh.
    isLoading: Boolean(key) && entry?.data === undefined && !entry?.error,
    isValidating: entry?.validating ?? false,
    mutate,
    revalidate,
  };
}

// Hover intent: sweeping the mouse down the board must not fire a request per card.
const HOVER_INTENT_MS = 120;
let hoverTimer: ReturnType<typeof setTimeout> | null = null;

// Loads a lead's record while the pointer rests on its row or card, so the workspace opens with data.
// `alsoRun` lets a caller warm the route too (cards navigate with router.push, not a <Link>).
export function prefetchLeadOnHover(id: string, alsoRun?: () => void) {
  if (hoverTimer) clearTimeout(hoverTimer);
  hoverTimer = setTimeout(() => {
    hoverTimer = null;
    queryCache.prefetch(cacheKeys.lead(id), cachedFetchers.lead(id));
    alsoRun?.();
  }, HOVER_INTENT_MS);
}

export function cancelLeadPrefetch() {
  if (hoverTimer) clearTimeout(hoverTimer);
  hoverTimer = null;
}
