import { NextRequest, NextResponse } from 'next/server';
import {
  createSessionCookieValue,
  SESSION_COOKIE,
  SESSION_MAX_AGE,
  verifyDashboardCredentials,
} from '../../../session';

export async function POST(request: NextRequest) {
  let body: { employee_id?: unknown; password?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: 'invalid request' }, { status: 400 });
  }

  if (typeof body.employee_id !== 'string' || typeof body.password !== 'string') {
    return NextResponse.json({ detail: 'employee ID and password are required' }, { status: 400 });
  }
  const employeeId = body.employee_id.trim().toLowerCase();
  const password = body.password;
  if (!employeeId || !password) {
    return NextResponse.json({ detail: 'employee ID and password are required' }, { status: 400 });
  }

  try {
    const user = await verifyDashboardCredentials(employeeId, password);
    if (!user) return NextResponse.json({ detail: 'invalid employee ID or password' }, { status: 401 });
    const response = NextResponse.json({ employee_id: user.employeeId, role: user.role });
    response.cookies.set({
      name: SESSION_COOKIE,
      value: await createSessionCookieValue(user.employeeId),
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      path: '/',
      maxAge: SESSION_MAX_AGE,
    });
    return response;
  } catch {
    return NextResponse.json({ detail: 'sign-in is not configured' }, { status: 503 });
  }
}
