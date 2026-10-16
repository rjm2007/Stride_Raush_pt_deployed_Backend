-- ONE-TIME clean-up of the client's production Supabase (taimrfktweamsnbbatux) before go-live.
-- On 2026-10-10 production was filled with a full copy of the demo database, so it holds only
-- demo/test rows (all 17 leads are is_test). This removes them and keeps the setup.
--
-- Run ONLY after `rpt migrate` has applied every migration (001-045) to production, and only with
-- the owner's go-ahead. Paste it into Supabase -> SQL Editor (production project) and Run.
-- Everything is in one transaction: any error rolls the whole thing back.
--
-- KEEPS: practices, practice_settings (booking engine off, outreach agent pinned below), global cadence versions,
-- cadence steps, message templates, case types (used to match "Ortho" = "Physical Therapy"),
-- schema_migrations.
-- REMOVES: every lead and everything hanging off it (calls, transcripts, texts, cadence runs,
-- history, Sheet queue, old per-lead cadence copies), the 3 test blocked numbers, demo booking data (clinics, clinicians,
-- slots, holds, offers, appointments), provider/integration logs, dashboard audit log, test
-- usage ledger, heartbeats, and the stray column stride_appointments.location_name_dummy_guard.

begin;

-- Guards: stop (and roll back) unless this is a fully migrated database holding test data only.
do $$
begin
  if not exists (select 1 from public.schema_migrations where version = '045_sheet_stage_trigger.sql') then
    raise exception 'run rpt migrate first (045_sheet_stage_trigger.sql is not applied)';
  end if;
  if exists (select 1 from public.leads where is_test is not true) then
    raise exception 'a real (non-test) lead exists; clean-up stopped, nothing was changed';
  end if;
end $$;

-- 1. Booking engine and Stride copies (none of it is used by this build).
delete from public.notification_log;
-- stride_busy_blocks exists in the live databases but no migration creates it.
do $$ begin
  if to_regclass('public.stride_busy_blocks') is not null then delete from public.stride_busy_blocks; end if;
end $$;
delete from public.appointments;
delete from public.slot_offers;
delete from public.slot_holds;
delete from public.availability_slots;
delete from public.availability_sync_state;
delete from public.clinician_assignments;
delete from public.clinicians;
delete from public.booking_locations;
delete from public.stride_appointments;
delete from public.stride_cases;
delete from public.stride_patients;
delete from public.stride_users;
delete from public.stride_locations;
delete from public.stride_other_records;
delete from public.stride_import_files;
delete from public.keap_sync;

-- 2. Leads and everything linked to them. call_logs (-> call_transcripts), lead_status_history and
--    lead_message_overrides follow the leads (on delete cascade). Old per-lead cadence copies
--    (cadence_versions.lead_id, no longer written) cascade with their lead, but their steps,
--    templates and outreach events are RESTRICT children, so they go first, explicitly.
delete from public.sms_messages;
delete from public.outreach_events;
delete from public.lead_message_overrides;
delete from public.message_templates
 where cadence_version_id in (select id from public.cadence_versions where lead_id is not null);
delete from public.cadence_steps
 where cadence_version_id in (select id from public.cadence_versions where lead_id is not null);
update public.cadence_versions set source_version_id = null
 where source_version_id in (select id from public.cadence_versions where lead_id is not null);
delete from public.cadence_versions where lead_id is not null;
delete from public.dashboard_sms_requests;
delete from public.test_usage_ledger;
delete from public.sheet_row_state;
delete from public.integration_outbox;
delete from public.lead_action_requests;
delete from public.leads;
delete from public.suppressed_numbers;

-- 3. Logs from demo testing (the worker would otherwise retry old unprocessed webhooks).
delete from public.provider_events;
delete from public.integration_events;
delete from public.dashboard_audit_log;
delete from public.service_heartbeats;

-- 4. Settings: this build never books in Stride, and calls use the outreach agent (the database
--    value wins over .env; demo had switched to the booking agent on 2026-10-14).
update public.practice_settings
   set stride_booking_enabled = false,
       vapi_assistant_id = '540ddb07-711e-4060-8753-f82d848b9a25',
       updated_at = now();

-- 5. The stray column created by mistake during the 2026-10-10 copy (not in any migration).
alter table public.stride_appointments drop column if exists location_name_dummy_guard;

commit;

-- After it runs, this should show 0 leads, 0 blocked numbers and the setup still there:
select (select count(*) from public.leads) as leads,
       (select count(*) from public.suppressed_numbers) as blocked_numbers,
       (select count(*) from public.cadence_versions where status = 'active') as active_cadences,
       (select count(*) from public.message_templates) as message_templates,
       (select count(*) from public.case_types) as case_types,
       (select vapi_assistant_id from public.practice_settings limit 1) as assistant;
