export type StaffRole = 'super_admin' | 'employee';

export type StaffUser = {
  userId: string;
  employeeId: string;
  displayName: string;
  role: StaffRole;
};

export type StaffRosterMember = {
  user_id: string;
  employee_id: string;
  display_name: string;
  role: StaffRole;
};

type ConfiguredUser = StaffUser & { password: string; email?: string };

const COOKIE = 'rpt_staff_session';
const MAX_AGE_SECONDS = 60 * 60 * 12;
const ID_PATTERN = /^[a-z0-9][a-z0-9._-]{2,31}$/;

function secret(): string {
  const value = process.env.DASHBOARD_SESSION_SECRET ?? '';
  if (value.length < 32) throw new Error('DASHBOARD_SESSION_SECRET must be at least 32 characters');
  return value;
}

function configuredUsers(): ConfiguredUser[] {
  let input: unknown;
  try {
    input = JSON.parse(process.env.DASHBOARD_USERS_JSON ?? '');
  } catch {
    throw new Error('DASHBOARD_USERS_JSON must be valid JSON');
  }
  if (!Array.isArray(input) || input.length === 0) throw new Error('DASHBOARD_USERS_JSON must contain users');

  const ids = new Set<string>();
  const emails = new Set<string>();
  const users = input.map((entry): ConfiguredUser => {
    if (!entry || typeof entry !== 'object') throw new Error('dashboard user must be an object');
    const value = entry as Record<string, unknown>;
    const id = String(value.id ?? '').trim().toLowerCase();
    const displayName = String(value.name ?? '').trim();
    const password = typeof value.password === 'string' ? value.password : '';
    const email = typeof value.email === 'string' ? value.email.trim().toLowerCase() : undefined;
    const role = value.role;
    if (!ID_PATTERN.test(id)) throw new Error('dashboard user ID is invalid');
    if (ids.has(id)) throw new Error('dashboard user IDs must be unique');
    if (value.email !== undefined && (!email || email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))) {
      throw new Error('dashboard user email is invalid');
    }
    if (email && emails.has(email)) throw new Error('dashboard user emails must be unique');
    if (!displayName || displayName.length > 120) throw new Error('dashboard user name is invalid');
    if (password.length < 12) throw new Error('dashboard user password is invalid');
    if (role !== 'super_admin' && role !== 'employee') throw new Error('dashboard user role is invalid');
    ids.add(id);
    if (email) emails.add(email);
    return { userId: id, employeeId: id, displayName, password, email, role };
  });
  if (users.filter((user) => user.role === 'super_admin').length !== 1) {
    throw new Error('exactly one super admin is required');
  }
  return users;
}

function base64url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function sign(payload: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret()), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  return base64url(new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payload))));
}

function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let index = 0; index < a.length; index += 1) diff |= a.charCodeAt(index) ^ b.charCodeAt(index);
  return diff === 0;
}

async function passwordDigest(value: string): Promise<string> {
  return base64url(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))));
}

async function credentialVersion(user: ConfiguredUser): Promise<string> {
  return sign(`credential:${user.userId}:${user.password}`);
}

function publicUser(user: ConfiguredUser): StaffUser {
  return { userId: user.userId, employeeId: user.employeeId, displayName: user.displayName, role: user.role };
}

export function isDashboardAuthConfigured(): boolean {
  try {
    secret();
    configuredUsers();
    return true;
  } catch {
    return false;
  }
}

export function getDashboardRoster(): StaffRosterMember[] {
  return configuredUsers().map((user) => ({
    user_id: user.userId,
    employee_id: user.employeeId,
    display_name: user.displayName,
    role: user.role,
  }));
}

export async function verifyDashboardCredentials(employeeId: string, password: string): Promise<StaffUser | null> {
  const login = employeeId.trim().toLowerCase();
  const user = configuredUsers().find((candidate) => candidate.userId === login || candidate.email === login);
  const expected = user?.password ?? 'invalid-dashboard-password';
  const [candidateDigest, expectedDigest] = await Promise.all([passwordDigest(password), passwordDigest(expected)]);
  return user && safeEqual(candidateDigest, expectedDigest) ? publicUser(user) : null;
}

export async function createSessionCookieValue(employeeId: string): Promise<string> {
  const user = configuredUsers().find((candidate) => candidate.userId === employeeId.trim().toLowerCase());
  if (!user) throw new Error('dashboard user is not configured');
  const payload = JSON.stringify({
    id: user.userId,
    version: await credentialVersion(user),
    exp: Math.floor(Date.now() / 1000) + MAX_AGE_SECONDS,
  });
  const encoded = base64url(new TextEncoder().encode(payload));
  return `${encoded}.${await sign(encoded)}`;
}

export async function readSessionCookieValue(raw: string | undefined): Promise<StaffUser | null> {
  if (!raw) return null;
  const [encoded, signature] = raw.split('.');
  if (!encoded || !signature || !safeEqual(signature, await sign(encoded))) return null;
  try {
    const parsed = JSON.parse(new TextDecoder().decode(Uint8Array.from(
      atob(encoded.replace(/-/g, '+').replace(/_/g, '/')), (character) => character.charCodeAt(0),
    ))) as { id?: string; version?: string; exp?: number };
    if (!parsed.id || !parsed.version || !parsed.exp || parsed.exp < Math.floor(Date.now() / 1000)) return null;
    const user = configuredUsers().find((candidate) => candidate.userId === parsed.id);
    if (!user || !safeEqual(parsed.version, await credentialVersion(user))) return null;
    return publicUser(user);
  } catch {
    return null;
  }
}

export async function getStaffUser(): Promise<StaffUser | null> {
  try {
    const { cookies } = await import('next/headers');
    return await readSessionCookieValue((await cookies()).get(COOKIE)?.value);
  } catch {
    return null;
  }
}

export const SESSION_COOKIE = COOKIE;
export const SESSION_MAX_AGE = MAX_AGE_SECONDS;
