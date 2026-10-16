import assert from 'node:assert/strict';
import test from 'node:test';
import {
  cadenceCallNames,
  cadenceActionDescription,
  cadenceStepName,
  cadenceRunSummary,
  reorderCadenceSteps,
  splitCadenceRuns,
} from './cadence.ts';

const event = (change: Record<string, unknown> = {}) => ({
  id: 1,
  cadence_step_id: 1,
  cadence_version_id: 3,
  cadence_scope: 'standard',
  cadence_step_count: 2,
  day_offset: 0,
  channel: 'call',
  status: 'delivered',
  scheduled_for: '2026-09-01T10:00:00Z',
  created_at: '2026-09-01T09:00:00Z',
  executed_at: '2026-09-01T10:00:00Z',
  ...change,
});

test('groups restart batches and keeps standalone callbacks in the interrupted run', () => {
  const runs = splitCadenceRuns([
    event(),
    event({ id: 2, day_offset: 1, scheduled_for: '2026-09-02T10:00:00Z' }),
    event({ id: 9, cadence_step_id: null, cadence_version_id: null, day_offset: null,
      created_at: '2026-09-02T09:30:00Z', scheduled_for: '2026-09-02T12:00:00Z' }),
    event({ id: 3, created_at: '2026-09-03T09:00:00Z', scheduled_for: '2026-09-03T10:00:00Z' }),
  ]);

  assert.equal(runs.length, 2);
  assert.deepEqual(runs[0].map((item) => item.id), [1, 2, 9]);
  assert.equal(runs[1][0].id, 3);
});

test('labels complete, interrupted, unresolved, and legacy runs honestly', () => {
  assert.equal(cadenceRunSummary([
    event(), event({ id: 2, day_offset: 1, scheduled_for: '2026-09-02T10:00:00Z' }),
  ]).label, 'Ran in full');
  assert.equal(cadenceRunSummary([event({ cadence_step_count: 8 })]).label, 'Ended after 1 step');
  assert.equal(cadenceRunSummary([
    event({ cadence_step_count: 8 }),
    event({ id: 2, day_offset: 1, cadence_step_count: 8 }),
  ]).label, 'Ended after 2 steps');
  assert.equal(cadenceRunSummary([
    event({ cadence_step_count: 8, status: 'failed', delivery_status: 'undelivered' }),
  ]).label, 'Ended after 1 step');
  assert.equal(cadenceRunSummary([
    event({ executed_at: null, status: 'skipped', cadence_step_count: 8 }),
  ]).label, 'Ended before first step');
  assert.equal(cadenceRunSummary([
    event({ executed_at: null, status: 'planned', cadence_step_count: 8 }),
  ]).label, 'In progress');
  assert.equal(cadenceRunSummary([
    event({ cadence_step_count: null }),
  ]).label, 'Completed 1 step');
});

test('does not count a standalone callback as a cadence step', () => {
  const summary = cadenceRunSummary([
    event({ cadence_step_count: 2 }),
    event({ id: 9, cadence_step_id: null, cadence_version_id: null, day_offset: null,
      cadence_step_count: null }),
  ]);

  assert.equal(summary.attempted, 1);
  assert.equal(summary.label, 'Ended after 1 step');
});

test('automatically names steps using their actual day and preserves the action', () => {
  assert.equal(cadenceStepName({ day_offset: 5, description: 'Day 0 initial scheduling call' }), 'Day 5 initial scheduling call');
  assert.equal(cadenceStepName({ day_offset: 0, description: 'Follow-up message' }), 'Day 0 Follow-up message');
  assert.equal(cadenceStepName({ day_offset: 365, description: 'DAY 1: Follow-up' }), 'Day 365 Follow-up');
  assert.equal(cadenceActionDescription('Day 3 Scheduling call'), 'Scheduling call');
});

test('names calls by absolute outreach and chronological call order', () => {
  const events = [
    event(),
    event({ id: 2, created_at: '2026-09-02T09:00:00Z', scheduled_for: '2026-09-02T10:00:00Z' }),
  ];
  const names = cadenceCallNames(events, [
    { id: 12, outreach_event_id: 2, dialed_at: '2026-09-02T10:00:00Z' },
    { id: 11, outreach_event_id: 1, dialed_at: '2026-09-01T10:00:00Z' },
  ]);

  assert.equal(names.get('11'), 'Outreach 1 · Call 1');
  assert.equal(names.get('12'), 'Outreach 2 · Call 1');
});

test('dragging across days adopts the destination day', () => {
  const steps = [
    { step_order: 0, day_offset: 0, channel: 'call' as const, description: 'A', is_active: true, sms_body: null },
    { step_order: 1, day_offset: 1, channel: 'sms' as const, description: 'B', is_active: true, sms_body: 'B' },
    { step_order: 2, day_offset: 3, channel: 'call' as const, description: 'C', is_active: true, sms_body: null },
  ];
  const moved = reorderCadenceSteps(steps, 0, 2);

  assert.deepEqual(moved.map((step) => step.description), ['B', 'C', 'Day 3 A']);
  assert.equal(moved[2].day_offset, 3);
  assert.equal(steps[0].day_offset, 0);
});
