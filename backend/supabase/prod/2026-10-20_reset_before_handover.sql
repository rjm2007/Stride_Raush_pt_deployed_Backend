-- Reset the client's production Supabase (taimrfktweamsnbbatux) after our final tests, before the clinic
-- starts with real patients (2026-10-20). At that point it held only our 4 test leads: 3 on Emma's test
-- number and 1 real-mode lead on Rudraksh's number (the 14-day check), which the 2026-10-16 script refuses.
--
-- KEEPS: practice settings (calling hours, holidays, limits, agent), cadence versions and steps, message
-- templates, case types, schema_migrations.
-- REMOVES: every lead and everything linked to it (calls, transcripts, texts, cadence runs, history, Sheet
-- queue and row memory, Sheet request ids), blocked numbers (from the Do Not Contact tests), provider and
-- integration logs, the dashboard audit log, the test usage ledger.
--
-- Guard: stops (nothing changed) if more than 4 leads exist, i.e. if real patients were already added.
-- Paste into Supabase -> SQL Editor (production project) and Run. One transaction: any error rolls back.
-- Clear the Google Sheet rows too, or the Sheet would point at leads that no longer exist.

begin;

do $$
begin
  if (select count(*) from public.leads) > 4 then
    raise exception 'more than 4 leads exist (real patients may have been added); reset stopped, nothing was changed';
  end if;
end $$;

delete from public.notification_log;
delete from public.sms_messages;
delete from public.outreach_events;
delete from public.lead_message_overrides;
delete from public.dashboard_sms_requests;
delete from public.test_usage_ledger;
delete from public.sheet_row_state;
delete from public.integration_outbox;
delete from public.lead_action_requests;
delete from public.leads;              -- call_logs, call_transcripts, lead_status_history follow (cascade)
delete from public.suppressed_numbers;
delete from public.provider_events;
delete from public.integration_events;
delete from public.dashboard_audit_log;

commit;

-- Should show 0 leads and 0 blocked numbers, with the setup still there:
select (select count(*) from public.leads) as leads,
       (select count(*) from public.suppressed_numbers) as blocked_numbers,
       (select count(*) from public.cadence_versions where status = 'active') as active_cadences,
       (select count(*) from public.message_templates) as message_templates,
       (select business_hours -> '6' ->> 'close' from public.practice_settings limit 1) as saturday_close,
       (select jsonb_array_length(holidays) from public.practice_settings limit 1) as holidays;
