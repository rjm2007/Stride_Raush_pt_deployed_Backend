# supabase — database schema

The app talks to hosted Supabase Postgres directly through `SUPABASE_DB_URL` (psycopg, no ORM, no Supabase
client). Production: the client's project `taimrfktweamsnbbatux` (Singapore, ap-southeast-1).

| Path | Purpose |
| --- | --- |
| `migrations/NNN_name.sql` | Ordered, idempotent schema changes 001 … 045, **identical to the demo repo**. `rpt migrate` applies any file not yet recorded in `public.schema_migrations`, in filename order. |
| `seed.sql` | Fresh-sandbox seed (`rpt seed`): the `rausch-pt` practice, settings, default cadence. Local test DBs only. |
| `dev/reset_test_lead_by_name.sql` | Used by `rpt test-lead` to replace a synthetic test lead; can only match `is_test` synthetic leads. |
| `prod/2026-10-16_clear_demo_copy.sql` | One-time go-live clean-up of production (it was filled with a demo copy on 2026-10-10): removes test leads and demo data, keeps the setup. Guarded: stops if migrations are missing or any non-test lead exists. Run only with the owner's go-ahead. |

## Main tables (this build)

- `practices`, `practice_settings` — one practice (`slug='rausch-pt'`); business hours, caps, Vapi assistant
  and phone number IDs (override `.env`), `booking_link_url` (texted by the agent), `transfer_number`.
- `leads`, `lead_status_history` — lead state and every status transition (with `source`).
- `cadence_versions`, `cadence_steps`, `message_templates` — global cadence definitions; `outreach_events` —
  one row per scheduled call/SMS for a lead.
- `call_logs`, `call_transcripts`, `sms_messages`, `notification_log` (booking-link texts) — provider results.
- `suppressed_numbers` — per-phone do-not-contact list.
- `provider_events`, `integration_events`, `integration_outbox` — durable webhook intake and the Sheet update
  queue (`destination='n8n'` is the stored label for "the Sheet").
- `lead_action_requests` — idempotency for Sheet commands. `sheet_row_state` — profile fingerprint per linked
  Sheet lead. Trigger `leads_sheet_stage_change` (045) queues a Sheet update whenever a Sheet lead's status /
  cadence_state / needs_review changes.
- `dashboard_audit_log`, `dashboard_sms_requests` — staff actions. `test_usage_ledger` — provider cost for
  test runs. `service_heartbeats` — sheet-worker liveness.
- `case_types` — case names + aliases ("Ortho" = "Physical Therapy"), used by the "Already booked" rule.

**Present but unused here** (kept so the schema matches demo and Stride/Keap can be switched on later):
`appointments`, `stride_*`, `booking_locations`, `clinicians`, `clinician_assignments`, `availability_*`,
`slot_holds`, `slot_offers`, `keap_*`, `lead_message_overrides`. The live databases also hold a table
`stride_busy_blocks` and three `v_*` views that no migration creates; leave them.

## Rules

- Never edit a migration that has been applied; add the next number. Two files share 016 and 023 for
  historical reasons; ordering is by full filename.
- A new migration is written and tested in the demo repo first, then copied here under the same name, so
  both databases keep one schema.
- Write migrations to be re-runnable (`if not exists`, `drop constraint if exists`, guarded updates).
- Some invariants are enforced by triggers/constraints (migration 025's worker claim protocol, 028–030
  review-pause fallback); read the migration before changing related Python.
