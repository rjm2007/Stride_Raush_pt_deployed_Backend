import assert from 'node:assert/strict';
import test from 'node:test';
import { activityDescription, activityKind, clientErrorMessage, clinicWallTimeToIso, defaultAfterUnblock, displayEnum, numberBlockMessage, UNBLOCK_RESULT, operationalMessage, sourceLabel, statusTone, teamActivity, timezoneLabel } from './display.ts';
import type { ActivityEntry } from './dashboard-data';

test('team activity shows staff changes across categories but never automated events', () => {
  const entry: ActivityEntry = { id: 'created', action: 'lead.created', occurred_at: '2026-10-02T12:00:00Z', actor_type: 'employee', actor_name: 'Test Staff', category: 'employee', title: 'Lead created', details: {} };
  const entries: ActivityEntry[] = [entry,
    { ...entry, id: 'paused', action: 'lead.cadence', category: 'cadence', title: 'Cadence paused', details: { mode: 'paused' } },
    { ...entry, id: 'message', category: 'messages', title: 'SMS requested' },
    ...(['calls', 'messages', 'cadence', 'employee'] as const).map((category) => ({ ...entry, id: `auto-${category}`, category, actor_type: 'automation' as const, actor_name: 'Automation' })),
  ];
  assert.deepEqual(teamActivity(entries).map((item) => item.id), ['created', 'paused', 'message']);
  assert.deepEqual(teamActivity(entries, ' PAUSED ').map((item) => item.id), ['paused']);
  assert.equal(teamActivity(entries, 'test staff').length, 3);
  assert.deepEqual(teamActivity(entries, 'automation'), []);
  assert.deepEqual(teamActivity([]), []);
  assert.equal(entries.length, 7);
});

test('normalizes machine values without changing stored data', () => {
  for (const value of ['google_sheets', 'google-sheet', 'n8n_sheet', 'n8n_sheets', 'N8N Sheets']) assert.equal(sourceLabel(value), 'Google Sheets');
  assert.equal(displayEnum('customer_did-not-answer'), 'Customer did not answer');
  assert.equal(timezoneLabel('America/Los_Angeles'), 'America Los Angeles');
});

test('selects semantic activity icons and status tones', () => {
  assert.equal(activityKind({ to_status: 'booking_link_sent' }), 'link');
  assert.equal(activityKind({ to_status: 'transferred_human' }), 'handoff');
  assert.equal(activityKind({ to_status: 'booked' }), 'appointment');
  assert.equal(statusTone('customer-did-not-answer'), 'warning');
  assert.equal(statusTone('undelivered'), 'error');
  assert.equal(statusTone('booked'), 'success');
});

test('replaces technical provider failures with client-safe messages', () => {
  assert.equal(operationalMessage('dispatch failed: twilio returned HTTP 400'), 'Message was not sent. Review the phone number before trying again.');
  assert.equal(operationalMessage('call outcome was not reported'), 'Call result could not be confirmed. Review it before continuing.');
  assert.equal(activityDescription({ reason: 'stale Stride booking requires reconciliation', source: 'worker' }), 'Appointment status could not be confirmed. Review it before trying again.');
  assert.equal(activityDescription({ reason: 'Replaced by Sheet lead 123 after phone number change' }), 'Contact details changed and need staff review.');
  assert.equal(activityDescription({ reason: 'cadence started from google_sheets' }), 'Cadence started from Google Sheets');
  assert.equal(clientErrorMessage('Postgres connection timeout', 'The lead could not be saved.'), 'The lead could not be saved.');
  assert.equal(clientErrorMessage('TypeError: Failed to fetch', 'The update could not be completed.'), 'The update could not be completed.');
  assert.equal(clientErrorMessage('Phone number is required.'), 'Phone number is required.');
  assert.equal(sourceLabel('twilio'), 'Messaging');
  assert.equal(sourceLabel('vapi'), 'Phone');
  assert.equal(sourceLabel('keap'), 'Staff handoff');
});

test('converts valid Pacific wall time and rejects DST edge cases', () => {
  const before = new Date('2026-01-01T00:00:00Z');
  assert.equal(clinicWallTimeToIso('2026-01-15T09:30', before), '2026-01-15T17:30:00.000Z');
  assert.throws(() => clinicWallTimeToIso('2026-03-08T02:30', before), /does not exist/);
  assert.throws(() => clinicWallTimeToIso('2026-11-01T01:30', before), /transition hour/);
  assert.throws(() => clinicWallTimeToIso('2025-01-15T09:30', before), /future/);
});

test('blocked number message says who blocked it and when, in clinic time', () => {
  // 17:37 UTC on Oct 6 is 10:37 AM Pacific (daylight time).
  const at = '2026-10-06T17:37:04Z';
  assert.equal(numberBlockMessage({ reason: 'staff selected Do Not Contact', source: 'n8n_sheet', blocked_at: at }),
    'Blocked by staff in the Google Sheet on Oct 6, 10:37 AM PT.');
  assert.equal(numberBlockMessage({ reason: 'explicit do-not-contact request', source: 'tool', blocked_at: at }),
    'Blocked by the patient during a call on Oct 6, 10:37 AM PT.');
  assert.equal(numberBlockMessage({ reason: null, source: 'webhook', blocked_at: at }),
    'Blocked by the patient during a call on Oct 6, 10:37 AM PT.');
  assert.equal(numberBlockMessage({ reason: null, source: null, blocked_at: at }),
    'Blocked by the system on Oct 6, 10:37 AM PT.');
  // A missing or broken date still gives a readable sentence.
  assert.equal(numberBlockMessage({ reason: null, source: 'n8n_sheet', blocked_at: 'not a date' }),
    'Blocked by staff in the Google Sheet.');
});

test('unblock suggests continuing after a short block and starting over after a week', () => {
  const now = new Date('2026-10-20T12:00:00Z');
  assert.equal(defaultAfterUnblock('2026-10-19T12:00:00Z', now), 'continue');
  assert.equal(defaultAfterUnblock('2026-10-13T12:00:01Z', now), 'continue');
  assert.equal(defaultAfterUnblock('2026-10-13T12:00:00Z', now), 'restart');
  assert.equal(defaultAfterUnblock(null, now), 'continue');
  assert.equal(defaultAfterUnblock('not a date', now), 'continue');
  assert.match(UNBLOCK_RESULT.continue, /next step/);
  assert.match(UNBLOCK_RESULT.restart, /Day 0/);
});
