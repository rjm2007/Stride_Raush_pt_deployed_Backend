import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createSessionCookieValue,
  getDashboardRoster,
  isDashboardAuthConfigured,
  readSessionCookieValue,
  verifyDashboardCredentials,
} from './session.ts';

const SECRET = 'test-session-secret-with-at-least-32-characters';
const USERS = [
  { id: 'admin', email: 'admin@example.test', name: 'Practice Administrator', password: 'admin-password-123', role: 'super_admin' },
  { id: 'sarah', email: 'sarah@example.test', name: 'Sarah Johnson', password: 'sarah-password-123', role: 'employee' },
];

function configure(users: unknown = USERS) {
  process.env.DASHBOARD_SESSION_SECRET = SECRET;
  process.env.DASHBOARD_USERS_JSON = JSON.stringify(users);
}

test('validates admin and employee credentials without exposing passwords', async () => {
  configure();
  assert.equal(isDashboardAuthConfigured(), true);
  assert.deepEqual(getDashboardRoster().map((user) => user.employee_id), ['admin', 'sarah']);
  assert.equal(JSON.stringify(getDashboardRoster()).includes('password'), false);
  assert.equal((await verifyDashboardCredentials('ADMIN', 'admin-password-123'))?.role, 'super_admin');
  assert.equal((await verifyDashboardCredentials('sarah', 'sarah-password-123'))?.role, 'employee');
  assert.equal((await verifyDashboardCredentials(' ADMIN@EXAMPLE.TEST ', 'admin-password-123'))?.employeeId, 'admin');
  assert.equal((await verifyDashboardCredentials('sarah@example.test', 'sarah-password-123'))?.employeeId, 'sarah');
  assert.equal(await verifyDashboardCredentials('sarah@example.test', 'admin-password-123'), null);
  assert.equal((await verifyDashboardCredentials('missing@example.test', 'sarah-password-123')), null);
  assert.equal(await verifyDashboardCredentials('sarah', 'wrong-password'), null);
  assert.equal(await verifyDashboardCredentials('missing', 'sarah-password-123'), null);
});

test('fails closed for invalid user configuration', () => {
  const invalid = [
    [],
    [{ ...USERS[1] }],
    [USERS[0], { ...USERS[0] }],
    [USERS[0], { ...USERS[1], id: 'Invalid ID' }],
    [USERS[0], { ...USERS[1], name: ' ' }],
    [USERS[0], { ...USERS[1], password: 'short' }],
    [USERS[0], { ...USERS[1], role: 'owner' }],
    [USERS[0], { ...USERS[1], role: 'super_admin' }],
    [USERS[0], { ...USERS[1], email: ' ' }],
    [USERS[0], { ...USERS[1], email: 'invalid' }],
    [USERS[0], { ...USERS[1], email: 42 }],
    [USERS[0], { ...USERS[1], email: 'ADMIN@EXAMPLE.TEST' }],
  ];
  for (const users of invalid) {
    configure(users);
    assert.equal(isDashboardAuthConfigured(), false);
  }
});

test('rejects tampered, expired, changed-password, and removed-user sessions', async () => {
  configure();
  const originalNow = Date.now;
  Date.now = () => 1_000_000;
  try {
    const session = await createSessionCookieValue('sarah');
    assert.equal((await readSessionCookieValue(session))?.employeeId, 'sarah');
    const last = session.at(-1);
    assert.equal(await readSessionCookieValue(`${session.slice(0, -1)}${last === 'A' ? 'B' : 'A'}`), null);

    configure([USERS[0], { ...USERS[1], password: 'new-sarah-password-123' }]);
    assert.equal(await readSessionCookieValue(session), null);

    configure([USERS[0]]);
    assert.equal(await readSessionCookieValue(session), null);

    configure();
    Date.now = () => 1_000_000 + (12 * 60 * 60 + 1) * 1000;
    assert.equal(await readSessionCookieValue(session), null);
  } finally {
    Date.now = originalNow;
  }
});
