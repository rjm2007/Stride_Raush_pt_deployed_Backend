// Where the dashboard proxy may send staff requests. Server-only logic, kept apart from the
// route so it can be unit tested.

// Docker service names the backend may answer on inside the server's own network.
const INTERNAL_HOSTS = new Set(['api', 'localhost']);

/** The backend origin to call, or null when it is missing or unsafe to use. */
export function backendOrigin(value: string | undefined, nodeEnv: string | undefined): string | null {
  const origin = value?.trim().replace(/\/+$/, '');
  if (!origin) return null;
  let url: URL;
  try {
    url = new URL(origin);
  } catch {
    return null;
  }
  if (url.pathname !== '/' || url.search || url.hash || url.username || url.password) return null;
  if (url.protocol === 'https:') return origin;
  // On the server the backend is http://api:8000 in the same Docker network: that hop never leaves
  // the machine. Everything that crosses a network must use HTTPS in production.
  if (url.protocol === 'http:' && (nodeEnv !== 'production' || INTERNAL_HOSTS.has(url.hostname))) return origin;
  return null;
}
