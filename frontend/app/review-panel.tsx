'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useState } from 'react';
import { ModalShell } from './dashboard-controls';
import { dashboardGet } from './dashboard-client';
import type { Review, ReviewChoice, ReviewPreview } from './dashboard-data';
import { CLINIC_TZ, CLINIC_TZ_LABEL } from './display';
import { RESOLVED_MESSAGE } from './review';

type ResolveAction = (path: string, method: string, body?: unknown, successMessage?: string) => Promise<Record<string, unknown> | null>;

function flaggedOn(value: string | null) {
  if (!value) return 'Date not recorded';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return 'Date not recorded';
  return `${parsed.toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: CLINIC_TZ })} ${CLINIC_TZ_LABEL}`;
}

// What was flagged, the proof, when and where from, and one button per choice.
export function ReviewCard({ review, onChoose, busy = false, compact = false }: { review: Review; onChoose?: (choice: ReviewChoice) => void; busy?: boolean; compact?: boolean }) {
  return <div className="review-card">
    <header><span className="status-pill review-group">{review.group_label}</span><strong>{review.title}</strong></header>
    <p className="review-reason">{review.reason}</p>
    <dl className="detail-list review-proof">
      {review.proof.map((item) => <div key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}
      <div><dt>Flagged</dt><dd>{flaggedOn(review.flagged_at)}</dd></div>
      <div><dt>Source</dt><dd>{review.source_label}</dd></div>
    </dl>
    {review.transcript_url && <p><Link className="text-action" href={review.transcript_url}>Read the call transcript →</Link></p>}
    {review.group === 'blocked' && <p className="muted">An admin can unblock the number on this lead’s page (continue or start over).</p>}
    {Boolean(review.also?.length) && <p className="muted">Also open: {review.also!.map((item) => item.title).join(', ')}. Reviews are resolved one at a time, oldest first; the lead stays paused until the last one.</p>}
    {onChoose && !compact && <div className="review-options">{review.options.map((option) =>
      <button key={option.choice} type="button" className={option.choice === 'front_desk' ? 'secondary' : 'primary'} disabled={busy} onClick={() => onChoose(option.choice)}>{option.label}</button>)}</div>}
  </div>;
}

// The confirm pop-up: what the choice does and the next step, from the backend, plus an optional note.
export function ResolveDialog({ leadId, choice, action, onClose, onResolved }: { leadId: string; choice: ReviewChoice; action: ResolveAction; onClose: () => void; onResolved?: (choice: ReviewChoice) => void }) {
  const [preview, setPreview] = useState<ReviewPreview | null>(null);
  const [failed, setFailed] = useState(false);
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    let live = true;
    // Never cached: the next step depends on the clock and on the lead's schedule right now.
    dashboardGet<ReviewPreview>(`/api/dashboard/review/${leadId}`)
      .then((data) => { if (live) setPreview(data); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [leadId]);
  const option = preview?.options.find((item) => item.choice === choice);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    // With another review still open the lead stays paused; say so instead of "Outreach continues".
    const more = option?.next_step.includes('next open review');
    const result = await action(`review/${leadId}/resolve`, 'POST', { choice, note: note.trim() || undefined }, more ? 'Saved. The next open review for this lead is shown now.' : RESOLVED_MESSAGE[choice]);
    setSaving(false);
    if (result) { onResolved?.(choice); onClose(); }
  }
  return <ModalShell className="resolve-dialog" labelId="resolve-title" onClose={onClose}>
    <header><div><h2 id="resolve-title">{option?.label ?? 'Resolve review'}</h2><p>{preview ? preview.full_name : 'Loading…'}</p></div><button className="close-button" type="button" onClick={onClose} aria-label="Close">×</button></header>
    <form onSubmit={submit}>
      {failed ? <p className="field-error" role="alert">The review could not be loaded. Close this and try again.</p>
        : !preview ? <p className="muted">Checking what this will do…</p>
        : !option ? <p className="field-error" role="alert">This choice is no longer available. The review may already be resolved.</p>
        : <div className="resolve-summary"><p><strong>{option.effect}.</strong></p><p>{option.next_step}</p></div>}
      <label className="field-label">Note (optional)<textarea value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} placeholder="e.g. Called the patient, the number is a landline" /></label>
      <footer><button className="secondary" type="button" onClick={onClose} disabled={saving}>Cancel</button><button className="primary" type="submit" disabled={saving || !option}>{saving ? 'Saving…' : 'Confirm'}</button></footer>
    </form>
  </ModalShell>;
}
