export type LeadStage = 'new' | 'cadence' | 'attention' | 'booked' | 'closed';

export type Lead = {
  id: string;
  display_id: string;
  full_name: string;
  phone: string | null;
  email?: string | null;
  source: string;
  status: string;
  stage: LeadStage;
  cadence_state: string;
  needs_review: boolean;
  review_reason: string | null;
  next_event_id: number | null;
  next_event_status?: string | null;
  next_step: string | null;
  next_channel: string | null;
  next_scheduled_for: string | null;
  created_at: string;
  last_contacted_at: string | null;
  location?: string;
  cadence_progress?: number;
  cadence_total?: number;
  cadence_version_name?: string | null;
  owner?: string;
  owner_user_id?: string | null;
  date_of_birth?: string;
  referred_by?: string;
  lead_type?: 'Physical Therapy' | 'Wellness';
  is_test?: boolean;
  number_block?: NumberBlock | null;
};

// Set when the lead's phone is on the do-not-contact list. Calls and texts to
// it never go out, whatever stage the lead is in.
export type NumberBlock = {
  reason: string | null;
  source: string | null;
  blocked_at: string;
};

export type CadenceStep = {
  id?: number;
  step_order: number;
  day_offset: number;
  channel: 'call' | 'sms';
  key?: string;
  description: string;
  is_active: boolean;
  sms_body: string | null;
};

export type CadenceVersion = {
  id: number;
  practice_id: number;
  lead_id: string | null;
  scope: 'global' | 'lead';
  version_number: number;
  name: string;
  status: 'draft' | 'active' | 'archived' | 'deleted';
  source_version_id: number | null;
  activated_at: string | null;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
  steps: CadenceStep[];
};

export type Metrics = {
  total_leads: number;
  messages_sent: number;
  messages_delivered: number;
  messages_failed: number;
  messages_pending: number;
  messages_delivery_rate: number | null;
  calls_completed: number;
  calls_completion_rate: number | null;
  calls_reached_rate: number | null;
  voice_minutes: number;
  voice_seconds: number;
  voice_cost: number;
  calls_logged: number;
  review_rate: number | null;
  booked_rate: number | null;
};

export type Snapshot = {
  // TESTING_MODE on the server: new Sheet leads run a one-minute-per-day cadence.
  testing_mode?: boolean;
  counts: Record<LeadStage, number>;
  leads: Lead[];
  cadence: Array<Record<string, unknown>>;
  templates: Array<Record<string, unknown>>;
  providers: Array<Record<string, unknown>>;
  system: Record<string, number>;
  metrics?: Metrics;
  generated_at?: string;
};

export type LeadDetail = {
  lead: Record<string, unknown> & { id: string; full_name: string; display_id: string };
  events: Array<Record<string, unknown>>;
  messages: Array<Record<string, unknown>>;
  calls: Array<Record<string, unknown>>;
  history: Array<Record<string, unknown>>;
  activity: ActivityEntry[];
  cadence_actions?: Array<Record<string, unknown>>;
  cadence_version?: CadenceVersion | null;
};

export type ActivityEntry = {
  id: string;
  action: string;
  occurred_at: string;
  actor_type: 'employee' | 'automation';
  actor_name: string;
  category: 'employee' | 'calls' | 'messages' | 'cadence';
  title: string;
  details: Record<string, unknown>;
};

export type StaffMember = {
  user_id: string;
  employee_id: string;
  display_name: string;
  role: 'super_admin' | 'employee';
};

export const emptySnapshot: Snapshot = {
  counts: { new: 0, cadence: 0, attention: 0, booked: 0, closed: 0 },
  leads: [],
  cadence: [],
  templates: [],
  providers: [],
  system: { provider_queue: 0, unknown_events: 0, review_queue: 0 },
};
