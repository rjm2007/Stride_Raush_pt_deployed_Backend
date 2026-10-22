// Needs Review: grouping, filtering and wording for the review cards (no React, unit tested).
//
// 2026-10-21: two leads sat in "needs review" and staff pressed Resume. The review stayed open, the
// worker sent nothing, and the page still read "Pause cadence". Staff could not see WHAT had changed.
// Each flagged lead now carries a `review` from the backend (reason, proof, choices); a choice is the
// only way to put a flagged lead back into outreach.
import type { Lead, Review, ReviewChoice, ReviewGroup } from './dashboard-data';

export const REVIEW_GROUPS: Array<{ value: ReviewGroup | 'all'; label: string }> = [
  { value: 'all', label: 'All reasons' },
  { value: 'name', label: 'Name changed' },
  { value: 'text', label: 'Text failed' },
  { value: 'call', label: 'Call problem' },
  { value: 'technical', label: 'Not confirmed' },
  { value: 'blocked', label: 'Number blocked' },
  { value: 'phone', label: 'Phone changed' },
  { value: 'other', label: 'Other' },
];

// A flagged lead from before the review records existed, or one the snapshot has not caught up on.
export function reviewOf(lead: Pick<Lead, 'review' | 'review_reason' | 'needs_review'>): Review | null {
  if (lead.review) return lead.review;
  if (!lead.needs_review) return null;
  return {
    id: null, code: 'other', group: 'other', group_label: 'Other', title: 'Needs review',
    reason: lead.review_reason || 'This lead needs staff review.', proof: [], flagged_at: null,
    source: null, source_label: 'System', landline: false, transcript_url: null,
    options: [{ choice: 'continue', label: 'Continue' }, { choice: 'front_desk', label: 'Front desk will handle' }],
  };
}

export function filterReviews<T extends Pick<Lead, 'review' | 'review_reason' | 'needs_review'>>(leads: T[], group: ReviewGroup | 'all'): T[] {
  return group === 'all' ? leads : leads.filter((lead) => reviewOf(lead)?.group === group);
}

export function groupCounts(leads: Array<Pick<Lead, 'review' | 'review_reason' | 'needs_review'>>): Record<string, number> {
  const counts: Record<string, number> = { all: leads.length };
  for (const lead of leads) {
    const group = reviewOf(lead)?.group ?? 'other';
    counts[group] = (counts[group] ?? 0) + 1;
  }
  return counts;
}

const CLOSING: ReadonlySet<ReviewChoice> = new Set(['different_person', 'wrong_number', 'close_phone_changed', 'front_desk']);

// Where the card goes once the choice is saved (the optimistic board update before the refetch).
export function stageAfter(choice: ReviewChoice): 'closed' | 'cadence' {
  return CLOSING.has(choice) ? 'closed' : 'cadence';
}

export const RESOLVED_MESSAGE: Record<ReviewChoice, string> = {
  use_new_name: 'New name saved. Outreach continues.',
  keep_old_name: 'Old name kept. Outreach continues.',
  different_person: 'Lead closed. Add the new person as a new row in the Sheet.',
  calls_only: 'Texts are off for this lead. Calls continue.',
  retry_texts: 'Texts stay on. The text is sent again.',
  number_ok: 'Number confirmed. Outreach continues.',
  wrong_number: 'Lead closed. Add the right number as a new row in the Sheet.',
  continue: 'Outreach continues.',
  close_phone_changed: 'Lead closed. Add the new number as a new row in the Sheet.',
  front_desk: 'Lead closed: handled by front desk.',
};
