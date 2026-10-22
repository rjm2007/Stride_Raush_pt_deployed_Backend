import { clearChats } from './assistant-store.ts';
import { queryCache } from './query-cache.ts';

// Every dashboard request uses the same expired-session behavior, including editors.
// It is also the single place writes pass through, so it is where cached reads are invalidated.
export async function dashboardFetch(url: string, options?: RequestInit): Promise<Response> {
  const response = await fetch(url, { cache: 'no-store', ...options });
  if (response.status === 401) {
    // Nothing cached for this session may outlive it: data cache and assistant chats.
    queryCache.clear();
    clearChats();
    window.location.assign('/login');
    throw new Error('Your session has expired. Sign in again.');
  }
  const method = (options?.method ?? 'GET').toUpperCase();
  // A successful staff action makes the reads it touched stale, so no screen keeps showing the old
  // state (on-screen reads refetch at once).
  if (response.ok && method !== 'GET' && method !== 'HEAD') queryCache.invalidateForMutation(url, method);
  return response;
}

export class DashboardHttpError extends Error {
  readonly status: number;
  constructor(status: number) {
    super(`dashboard request failed (${status})`);
    this.status = status;
  }
}

// GET through the proxy for the cache. Reads cookies at request time (no token captured in a
// closure), so a prefetch that outlives its render still uses the current session.
export async function dashboardGet<T>(url: string): Promise<T> {
  const response = await dashboardFetch(url);
  if (!response.ok) throw new DashboardHttpError(response.status);
  return response.json() as Promise<T>;
}
