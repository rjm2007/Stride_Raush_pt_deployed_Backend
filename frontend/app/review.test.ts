import assert from 'node:assert/strict';
import test from 'node:test';
import { filterReviews, groupCounts, RESOLVED_MESSAGE, reviewOf, stageAfter } from './review.ts';
import type { Review } from './dashboard-data.ts';

const textReview: Review = {
  id: 1, code: 'sms_failed', group: 'text', group_label: 'Text failed', title: 'Text not delivered',
  reason: "The Day 0 text was not delivered: this number can't receive texts (likely a landline).",
  proof: [], flagged_at: '2026-10-21T16:00:00Z', source: 'text', source_label: 'Text message',
  landline: true, transcript_url: null,
  options: [{ choice: 'calls_only', label: 'Continue with calls only' }, { choice: 'front_desk', label: 'Front desk will handle' }],
};

test('a flagged lead without a review record still gets Continue / Front desk', () => {
  const review = reviewOf({ needs_review: true, review_reason: 'old words', review: null });
  assert.equal(review?.group, 'other');
  assert.deepEqual(review?.options.map((o) => o.choice), ['continue', 'front_desk']);
  assert.equal(reviewOf({ needs_review: false, review_reason: null, review: null }), null);
});

test('the review tab filters and counts by reason group', () => {
  const leads = [
    { needs_review: true, review_reason: null, review: textReview },
    { needs_review: true, review_reason: 'x', review: null },
  ];
  assert.equal(filterReviews(leads, 'text').length, 1);
  assert.equal(filterReviews(leads, 'all').length, 2);
  assert.deepEqual(groupCounts(leads), { all: 2, text: 1, other: 1 });
});

test('closing choices move the card to Closed, the rest back into cadence', () => {
  assert.equal(stageAfter('front_desk'), 'closed');
  assert.equal(stageAfter('wrong_number'), 'closed');
  assert.equal(stageAfter('calls_only'), 'cadence');
  assert.match(RESOLVED_MESSAGE.calls_only, /Texts are off/);
});
