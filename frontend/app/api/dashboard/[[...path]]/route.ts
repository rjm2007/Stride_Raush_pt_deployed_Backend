import { NextRequest, NextResponse } from 'next/server';
import { backendOrigin } from '../../../dashboard-origin';
import { getStaffUser } from '../../../session';

const ALLOWED_METHODS = new Set(['GET', 'POST', 'PATCH', 'PUT', 'DELETE']);
// Every backend route the browser may reach, listed explicitly. A path missing
// from here is rejected with "dashboard path not allowed", so this must be
// updated whenever a new dashboard endpoint is added.
// Leads come only from the Google Sheet, so there is no bare `leads` (create) path.
const ALLOWED_PATH = /^(snapshot|leads\/[0-9a-f-]+(?:\/(?:cadence|contact-rules|stage|sms|outreach-events\/\d+))?|review\/[0-9a-f-]+\/resolve|cadence-versions(?:\/\d+(?:\/(?:activate|name|permanent))?)?|cadence-steps\/\d+|message-templates(?:\/\d+)?|assistant(?:\/stream)?)$/i;

async function proxy(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  if (!ALLOWED_METHODS.has(request.method)) {
    return NextResponse.json({ detail: 'method not allowed' }, { status: 405 });
  }

  // A valid signed session is required in every environment. The old build
  // allowed an unauthenticated local preview here; that is deliberately gone,
  // because this route reaches real patient data whatever NODE_ENV says.
  const user = await getStaffUser();
  if (!user) {
    return NextResponse.json({ detail: 'authentication required' }, { status: 401 });
  }

  const { path = [] } = await context.params;
  const relativePath = path.join('/');
  if (!ALLOWED_PATH.test(relativePath)) {
    return NextResponse.json({ detail: 'dashboard path not allowed' }, { status: 404 });
  }
  if (/^leads\/[0-9a-f-]+$/i.test(relativePath) && !['GET', 'DELETE'].includes(request.method)) {
    return NextResponse.json({ detail: 'method not allowed' }, { status: 405 });
  }

  const token = process.env.DASHBOARD_API_TOKEN;
  if (!process.env.DASHBOARD_API_ORIGIN || !token) {
    return NextResponse.json({ detail: 'dashboard API is not configured' }, { status: 503 });
  }
  // HTTPS, or http://api:8000 inside the server's Docker network (see dashboard-origin.ts).
  const origin = backendOrigin(process.env.DASHBOARD_API_ORIGIN, process.env.NODE_ENV);
  if (!origin) {
    return NextResponse.json({ detail: 'dashboard API must use HTTPS' }, { status: 503 });
  }

  // The assistant carries up to 20k characters of conversation; the backend caps it there too.
  const limit = relativePath.startsWith('assistant') ? 64_000 : 20_000;
  if (Number(request.headers.get('content-length') ?? 0) > limit) {
    return NextResponse.json({ detail: 'request too large' }, { status: 413 });
  }
  const requestBody = request.method === 'GET' ? undefined : await request.text();
  // A chunked body has no content-length, so the real size is checked too.
  if (requestBody && new TextEncoder().encode(requestBody).length > limit) {
    return NextResponse.json({ detail: 'request too large' }, { status: 413 });
  }
  let response: Response;
  try {
    response = await fetch(`${origin}/api/v1/dashboard/${relativePath}${request.nextUrl.search}`, {
      method: request.method,
      cache: 'no-store',
      signal: AbortSignal.timeout(relativePath.startsWith('assistant') ? 90_000 : 20_000),
      headers: {
        'Content-Type': 'application/json',
        'X-Dashboard-Token': token,
        'X-Dashboard-User-ID': user.employeeId,
        'X-Dashboard-User-Name': encodeURIComponent(user.displayName),
        'X-Dashboard-User-Role': user.role,
        'X-Trace-ID': crypto.randomUUID(),
      },
      body: requestBody,
    });
  } catch {
    // No upstream URL, headers, patient payload, or raw exception enters logs.
    console.warn('[dashboard proxy] backend connection unavailable');
    return NextResponse.json({ detail: 'The dashboard service is unavailable. Please try again.' }, {
      status: 503,
      headers: { 'Cache-Control': 'no-store' },
    });
  }

  // The staff session was checked above, so a 401 from the backend means the two halves disagree on
  // DASHBOARD_API_TOKEN. Passing it on would send the browser to /login, which sends a signed-in
  // user straight back: an endless loop. Report a service problem instead.
  if (response.status === 401) {
    console.warn('[dashboard proxy] backend rejected the server token');
    return NextResponse.json({ detail: 'The dashboard service is unavailable. Please try again.' }, {
      status: 502,
      headers: { 'Cache-Control': 'no-store' },
    });
  }

  return new NextResponse(response.body, {
    status: response.status,
    headers: {
      'Content-Type': response.headers.get('content-type') ?? 'application/json',
      'Cache-Control': 'no-store',
    },
  });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
