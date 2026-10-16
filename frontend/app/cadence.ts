import type { CadenceStep } from './dashboard-data';

export type CadenceEvent = Record<string, unknown>;
export type CallSession = Record<string, unknown>;

export function splitCadenceRuns(events: CadenceEvent[]) {
  const batches = new Map<string, CadenceEvent[]>();
  const order: string[] = [];
  for (const event of events) {
    const key = String(event.created_at ?? event.id);
    if (!batches.has(key)) {
      batches.set(key, []);
      order.push(key);
    }
    batches.get(key)!.push(event);
  }

  const runs: CadenceEvent[][] = [];
  for (const key of order) {
    const batch = batches.get(key)!;
    const standalone = batch.every((event) => event.day_offset === null || event.day_offset === undefined);
    if (standalone && runs.length) runs[runs.length - 1].push(...batch);
    else runs.push(batch);
  }

  for (const run of runs) {
    run.sort((a, b) => String(a.scheduled_for ?? '').localeCompare(String(b.scheduled_for ?? '')));
  }
  runs.sort((a, b) => String(a[0]?.created_at ?? '').localeCompare(String(b[0]?.created_at ?? '')));
  return runs;
}

export function isCadenceStep(event: CadenceEvent) {
  return event.day_offset !== null && event.day_offset !== undefined;
}

export function cadenceActionDescription(description: string) {
  return description.trim().replace(/^day\s+\d+\b[\s:–—-]*/i, '');
}

export function cadenceStepName(step: Pick<CadenceStep, 'day_offset' | 'description'>) {
  return `Day ${step.day_offset} ${cadenceActionDescription(step.description)}`.trim();
}

export function cadenceRunSummary(run: CadenceEvent[]) {
  const steps = run.filter(isCadenceStep);
  const attempted = steps.filter((event) => event.executed_at).length;
  const expectedValues = steps
    .map((event) => Number(event.cadence_step_count))
    .filter((value) => Number.isInteger(value) && value > 0);
  const expectedSteps = expectedValues.length ? Math.max(...expectedValues) : null;
  const unresolved = steps.some((event) => ['planned', 'in_flight', 'attempted'].includes(String(event.status)));
  const skipped = steps.some((event) => event.status === 'skipped');

  if (unresolved) return { label: 'In progress', tone: 'warn', attempted, expectedSteps, inProgress: true } as const;
  if (expectedSteps !== null && attempted >= expectedSteps && !skipped) {
    return { label: 'Ran in full', tone: 'ok', attempted, expectedSteps, inProgress: false } as const;
  }
  if (expectedSteps !== null || skipped) {
    return {
      label: attempted === 0 ? 'Ended before first step' : `Ended after ${attempted} step${attempted === 1 ? '' : 's'}`,
      tone: 'warn', attempted, expectedSteps, inProgress: false,
    } as const;
  }
  return {
    label: `Completed ${attempted} step${attempted === 1 ? '' : 's'}`,
    tone: 'idle', attempted, expectedSteps, inProgress: false,
  } as const;
}

export function cadenceCallNames(events: CadenceEvent[], calls: CallSession[]) {
  const eventRuns = new Map<string, number>();
  splitCadenceRuns(events).forEach((run, runIndex) => {
    for (const event of run) eventRuns.set(String(event.id), runIndex);
  });

  const callsByRun = new Map<number, CallSession[]>();
  for (const call of calls) {
    const runIndex = eventRuns.get(String(call.outreach_event_id));
    if (runIndex === undefined) continue;
    const grouped = callsByRun.get(runIndex) ?? [];
    grouped.push(call);
    callsByRun.set(runIndex, grouped);
  }

  const names = new Map<string, string>();
  for (const [runIndex, grouped] of callsByRun) {
    grouped.sort((a, b) => {
      const byTime = String(a.dialed_at ?? '').localeCompare(String(b.dialed_at ?? ''));
      return byTime || String(a.id).localeCompare(String(b.id));
    });
    grouped.forEach((call, callIndex) => {
      names.set(String(call.id), `Outreach ${runIndex + 1} · Call ${callIndex + 1}`);
    });
  }
  return names;
}

export function reorderCadenceSteps(steps: CadenceStep[], from: number, to: number) {
  if (from === to || from < 0 || to < 0 || from >= steps.length || to >= steps.length) return steps;
  const next = [...steps];
  const destinationDay = next[to].day_offset;
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, { ...moved, day_offset: destinationDay, description: cadenceStepName({ ...moved, day_offset: destinationDay }) });
  return next;
}
