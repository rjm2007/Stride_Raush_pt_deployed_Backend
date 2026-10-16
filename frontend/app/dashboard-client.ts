// Every dashboard request uses the same expired-session behavior, including editors.
export async function dashboardFetch(url: string, options?: RequestInit): Promise<Response> {
  const response = await fetch(url, { cache: 'no-store', ...options });
  if (response.status === 401) {
    window.location.assign('/login');
    throw new Error('Your session has expired. Sign in again.');
  }
  return response;
}
