import type { ActivityEntry, NumberBlock } from './dashboard-data';

export const CLINIC_TZ = 'America/Los_Angeles';
export const CLINIC_TZ_LABEL = 'PT';

const LABELS: Record<string, string> = {
  declined: 'Not interested',
  callback_scheduled: 'Callback scheduled',
  booking_link_sent: 'Booking link sent',
  transferred_human: 'Transferred to staff',
  closed_no_response: 'Closed, no response',
  do_not_contact: 'Do not contact',
  invalid_phone: 'Invalid phone number',
  wrong_person: 'Wrong person',
};

function key(value: unknown) {
  return String(value ?? '').trim().toLowerCase().replace(/[\s-]+/g, '_');
}

export function displayEnum(value: unknown) {
  const raw = String(value ?? '').trim();
  if (!raw) return 'Unknown';
  const normalized = key(raw);
  return LABELS[normalized] ?? normalized.replaceAll('_', ' ').replace(/^\w/, (letter) => letter.toUpperCase());
}

export function sourceLabel(value: unknown) {
  const normalized = key(value).replace(/_+/g, '_');
  if (/^(google|n8n)_sheets?$/.test(normalized) || normalized === 'n8n') return 'Google Sheets';
  if (normalized === 'twilio') return 'Messaging';
  if (normalized === 'vapi') return 'Phone';
  if (/^stri(?:de|pe)$/.test(normalized)) return 'Scheduling';
  if (normalized === 'keap') return 'Staff handoff';
  if (/^(api|provider|webhook|worker)$/.test(normalized)) return 'System';
  return displayEnum(value);
}

export function timezoneLabel(value: unknown) {
  const raw = String(value ?? '').trim();
  return raw ? raw.replace(/[\/_-]+/g, ' ').replace(/\s+/g, ' ') : 'Not recorded';
}

export type StatusTone = 'success' | 'warning' | 'error' | 'neutral';
export function statusTone(value: unknown): StatusTone {
  const normalized = key(value).replaceAll('_', ' ');
  if (/failed|undelivered|invalid|error|rejected/.test(normalized)) return 'error';
  if (/attention|pending|busy|voicemail|no answer|did not answer|cancel|gated|disabled|unknown|awaiting|manual/.test(normalized)) return 'warning';
  if (/booked|delivered|completed|connected|active|scheduled|permitted|ready|published|yes/.test(normalized)) return 'success';
  return 'neutral';
}

export type ActivityKind = 'appointment' | 'link' | 'handoff' | 'call' | 'message' | 'created' | 'closed' | 'history';
export function teamActivity(entries: ActivityEntry[], query = '') {
  const search = query.trim().toLowerCase();
  return entries.filter((entry) => entry.actor_type === 'employee' &&
    `${entry.title} ${entry.actor_name} ${entry.action} ${Object.values(entry.details).join(' ')}`.toLowerCase().includes(search));
}

export function activityKind(item: Record<string, unknown>): ActivityKind {
  const value = `${item.to_status ?? ''} ${item.reason ?? ''} ${item.source ?? ''}`.toLowerCase().replaceAll('_', ' ').replaceAll('-', ' ');
  if (/booking link/.test(value)) return 'link';
  if (/transfer|handoff|staff|human/.test(value)) return 'handoff';
  if (/appointment|booked|stride/.test(value)) return 'appointment';
  if (/sms|message|text|twilio/.test(value)) return 'message';
  if (/call|callback|vapi|in progress/.test(value)) return 'call';
  if (/created|new lead/.test(value)) return 'created';
  if (/closed|do not contact|dnc/.test(value)) return 'closed';
  return 'history';
}

export type OperationalContext = 'message' | 'call' | 'appointment' | 'handoff' | 'review' | 'action' | 'assistant';

const OPERATIONAL_DEFAULTS: Record<OperationalContext, string> = {
  message: 'Message was not sent. Review the phone number before trying again.',
  call: 'Call could not be completed. Review the phone number before trying again.',
  appointment: 'Appointment status could not be confirmed. Review it before trying again.',
  handoff: 'Staff handoff could not be confirmed. Review it before trying again.',
  review: 'This lead needs staff review before outreach continues.',
  action: 'The update could not be completed. Please try again.',
  assistant: 'The assistant is temporarily unavailable. Please try again.',
};

const TECHNICAL_DETAIL = /\b(?:twilio|vapi|stride|stripe|keap|moonshot|kimi|openai|n8n|supabase|postgres(?:ql)?|database|sql|http|api|webhook|worker|provider|dispatch|transport|socket|timeout|error|exception|traceback|json|status code|response code|bad request|internal server|service unavailable|gateway|fetch|network|connection|failed to|econn\w*|enotfound)\b|\b[45]\d{2}\b|https?:\/\//i;
const UNCERTAIN_RESULT = /ambiguous|unknown|not reported|not recorded|requires? reconciliation|stale|pending result/i;

export function operationalMessage(value: unknown, context: OperationalContext = 'review') {
  const text = String(value ?? '').trim().toLowerCase().replace(/[_-]+/g, ' ');
  if (!text) return OPERATIONAL_DEFAULTS[context];
  if (/^number blocked/.test(text)) return 'Number blocked: this patient asked not to be contacted. An admin can unblock it on this page to start outreach.';
  if (/moved to review from the board/.test(text)) return 'Moved to staff review.';
  if (/wrong (?:phone|number|person)|invalid phone/.test(text)) return 'The phone number needs review before outreach continues.';
  if (/replaced by sheet lead|phone number change/.test(text)) return 'Contact details changed and need staff review.';
  if (/do not contact|\bdnc\b/.test(text)) return 'Outreach stopped because this lead should not be contacted.';
  if (/sms|text|message|twilio|carrier/.test(text)) {
    return UNCERTAIN_RESULT.test(text) || /delivery status|confirmation/.test(text)
      ? 'Message delivery could not be confirmed. Review it before trying again.'
      : OPERATIONAL_DEFAULTS.message;
  }
  if (/call|voice|vapi/.test(text)) {
    return UNCERTAIN_RESULT.test(text) || /outcome/.test(text)
      ? 'Call result could not be confirmed. Review it before continuing.'
      : OPERATIONAL_DEFAULTS.call;
  }
  if (/appointment|booking|stride|stripe/.test(text)) return OPERATIONAL_DEFAULTS.appointment;
  if (/handoff|transfer|keap/.test(text)) return OPERATIONAL_DEFAULTS.handoff;
  return OPERATIONAL_DEFAULTS[context];
}

export function clientErrorMessage(value: unknown, fallback = OPERATIONAL_DEFAULTS.action) {
  const text = String(value ?? '').trim();
  if (!text) return fallback;
  if (!TECHNICAL_DETAIL.test(text)) return text;
  const specific = operationalMessage(text, 'action');
  return specific === OPERATIONAL_DEFAULTS.action ? fallback : specific;
}

export function activityDescription(item: Record<string, unknown>) {
  const reason = String(item.reason ?? '').trim();
  if (!reason) return 'Status updated';
  if (TECHNICAL_DETAIL.test(reason) || /failed|failure|not delivered|not reported|ambiguous|unknown|replaced by sheet lead|phone number change/i.test(reason)) {
    const context: OperationalContext = ({ message: 'message', call: 'call', appointment: 'appointment', handoff: 'handoff' } as const)[activityKind(item) as 'message' | 'call' | 'appointment' | 'handoff'] ?? 'review';
    return operationalMessage(reason, context);
  }
  return displayEnum(reason).replace(/\b(?:google|n8n) sheets?\b/gi, 'Google Sheets');
}

type WallParts = { year: number; month: number; day: number; hour: number; minute: number };
const clinicFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: CLINIC_TZ, year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

function zonedParts(date: Date): WallParts {
  const parts = Object.fromEntries(clinicFormatter.formatToParts(date).map((part) => [part.type, part.value]));
  return { year: Number(parts.year), month: Number(parts.month), day: Number(parts.day), hour: Number(parts.hour), minute: Number(parts.minute) };
}

function sameWallTime(left: WallParts, right: WallParts) {
  return left.year === right.year && left.month === right.month && left.day === right.day && left.hour === right.hour && left.minute === right.minute;
}

function parseWallTime(value: string): WallParts {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);
  if (!match) throw new Error('Choose a valid date and time.');
  const wall = { year: +match[1], month: +match[2], day: +match[3], hour: +match[4], minute: +match[5] };
  const check = new Date(Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute));
  if (check.getUTCFullYear() !== wall.year || check.getUTCMonth() !== wall.month - 1 || check.getUTCDate() !== wall.day || wall.hour > 23 || wall.minute > 59) {
    throw new Error('Choose a valid date and time.');
  }
  return wall;
}

export function clinicDateTimeValue(value: unknown) {
  const parsed = new Date(String(value ?? ''));
  if (Number.isNaN(parsed.valueOf())) return '';
  const wall = zonedParts(parsed);
  return `${wall.year}-${String(wall.month).padStart(2, '0')}-${String(wall.day).padStart(2, '0')}T${String(wall.hour).padStart(2, '0')}:${String(wall.minute).padStart(2, '0')}`;
}

export function clinicWallTimeToIso(value: string, now = new Date()) {
  const wall = parseWallTime(value);
  const target = Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute);
  let candidate = target;
  for (let pass = 0; pass < 3; pass += 1) {
    const shown = zonedParts(new Date(candidate));
    const offset = Date.UTC(shown.year, shown.month - 1, shown.day, shown.hour, shown.minute) - candidate;
    candidate = target - offset;
  }
  const matches = [...new Set([candidate - 3_600_000, candidate, candidate + 3_600_000])]
    .filter((instant) => sameWallTime(zonedParts(new Date(instant)), wall));
  if (matches.length !== 1) throw new Error(matches.length ? 'Choose a time outside the daylight-saving transition hour.' : 'That time does not exist in Pacific Time because of daylight saving.');
  if (matches[0] <= now.valueOf()) throw new Error('Choose a future time.');
  return new Date(matches[0]).toISOString();
}

// Who put the number on the do-not-contact list, in staff words.
function blockedBy(source: unknown) {
  const normalized = key(source);
  if (/^(n8n_sheet|google_sheets?|n8n)$/.test(normalized)) return 'staff in the Google Sheet';
  if (/^(tool|webhook|vapi)$/.test(normalized)) return 'the patient during a call';
  if (normalized === 'dashboard') return 'staff in the dashboard';
  if (/^(twilio|sms)$/.test(normalized)) return 'the patient by text';
  return 'the system';
}

export function numberBlockMessage(block: NumberBlock) {
  const parsed = new Date(block.blocked_at);
  const when = Number.isNaN(parsed.valueOf()) ? '' : ` on ${new Intl.DateTimeFormat('en-US', {
    timeZone: CLINIC_TZ, month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  }).format(parsed)} ${CLINIC_TZ_LABEL}`;
  return `Blocked by ${blockedBy(block.source)}${when}.`;
}

export type AfterUnblock = 'continue' | 'restart';

// A short block was usually a mistake, so the patient picks up where they left
// off. After a week the remaining steps ("final reminder") no longer make sense
// on their own, so starting over is the better default.
export function defaultAfterUnblock(blockedAt: string | null | undefined, now = new Date()): AfterUnblock {
  const since = new Date(String(blockedAt ?? ''));
  if (Number.isNaN(since.valueOf())) return 'continue';
  return now.valueOf() - since.valueOf() < 7 * 24 * 60 * 60 * 1000 ? 'continue' : 'restart';
}

export const UNBLOCK_RESULT: Record<AfterUnblock, string> = {
  continue: 'Number unblocked. Outreach continues from the next step.',
  restart: 'Number unblocked. Outreach starts again from Day 0.',
};
