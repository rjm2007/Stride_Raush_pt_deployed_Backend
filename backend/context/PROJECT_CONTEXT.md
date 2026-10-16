# Project context — Rausch PT outreach, production build

Canonical context for the production backend. Read it before changing code; after a material change update
the relevant section and add a dated changelog entry at the bottom. The full history of how the system was
built (incidents, decisions, Stride/Keap/booking work) is in the demo repo's
`context/PROJECT_CONTEXT.md` (`../../demo/aws_deployed_raush_pt_stride_keap/`).

## 1. Purpose

New patient leads of Rausch Physical Therapy & Wellness (California) get a scripted 14-day cadence of AI
voice calls (Vapi) and texts (Twilio), with the goal that the patient books an Initial Evaluation. Until the
system is connected to Stride (the clinic's EHR) and Keap, production runs **cadence only**:

- Leads come in only from the clinic's **Google Sheet** (service account, no n8n).
- The voice agent is the **outreach agent**: it offers the online booking link by text, transfers the caller
  to the front desk, or agrees a callback time. It does not book.
- The clinic books the patient itself; **staff mark the lead Booked** in the Sheet (or on the dashboard
  board). There is no record of when, with whom or by whom the visit was booked.
- Staff manage everything on the dashboard (same server, same domain).

## 2. Architecture

```text
Google Sheet  <--service account-->  sheet-worker  (commands, profile edits, results)
Dashboard (Next.js, same server)  --http://api:8000-->  api  /api/v1/dashboard/*
worker  -->  Vapi (calls)  and  Twilio (texts, incl. the booking link)
Vapi  -->  api  /api/v1/webhooks/vapi/lead-status (agent tool),  /api/v1/vapi/webhook (end-of-call)
Twilio -->  api  /api/v1/twilio/message-status,  /api/v1/twilio/inbound-sms (replies, STOP)
All state: the client's Supabase Postgres (project taimrfktweamsnbbatux, Singapore).
```

One EC2 server, Docker Compose (repo root `docker-compose.yml`): `api`, `worker`, `sheet-worker`,
`dashboard`, `caddy`. Caddy serves `https://stride.aibolt.ai`: `/api/v1/*`, `/health`, `/ready` go to the
api (except `/api/v1/dashboard/*`, which is internal only), everything else to the dashboard.

## 3. Lead lifecycle

1. Staff add a row and pick Action `Start cadence`. After the row is unchanged for 60 s the sheet-worker
   creates the lead and plans the active cadence version (Standard v13: Day 0 call + text, Day 1 text, Day 3
   call, Day 5 call + text, Day 9 text, Day 13 text, Day 14 call). Outcome Status `Cadence started`.
2. The worker calls and texts only in business hours (Mon–Fri 9–5 Pacific, `practice_settings`), within
   daily caps, never to opted-out or blocked numbers.
3. On a call the agent reports one decision through `update_lead_status`:
   - `booking_link` → the link (`practice_settings.booking_link_url`) is texted 2 minutes later, unless
     the patient changes their mind first. Cadence continues.
   - `callback_scheduled` → next call at the agreed time (clamped to business hours). Cadence continues.
   - `transferred_human` → transfer to the front desk. Cadence continues.
   - `declined` → cadence ends (Closed). `do_not_contact` → cadence ends, number blocked.
   - `wrong_person` → paused for staff review.
4. Staff mark `Booked` (Sheet or board) → planned steps skipped, status booked, board column Booked.
5. No booking after the last step → Closed (`closed_no_response`).
6. A patient texting STOP is opted out; staff Do Not Contact (Sheet or dashboard) blocks the number;
   an admin can unblock from the dashboard (continue or restart).

## 4. Configuration

- `.env` (backend) and `dashboard.env` (dashboard) at the repo root on the server; templates
  `.env.example` and `dashboard.env.example`; built by `scripts/make-server-env.sh`.
- `practice_settings` (DB) holds the Vapi assistant and phone number ids, booking link, business hours,
  daily caps. It overrides the matching `.env` values.
- `OUTBOUND_ENABLED` is the master stop for calls and texts. The staff assistant is off
  (`ASSISTANT_ENABLED=false`) until a patient-data approval exists.
- `TESTING_MODE=true`: new Sheet leads are test leads (one minute per cadence day, no calling hours or daily
  limits), for checking the whole flow on the live server; `false` for real patients. Dashboard banner.

## 5. Database

Schema identical to demo (migrations 001–045). Unused Stride/Keap/booking tables stay empty. Production was
filled with a demo copy on 2026-10-10; `supabase/prod/2026-10-16_clear_demo_copy.sql` clears it before
go-live (owner's go-ahead required).

## 6. Removed from the demo build (and why)

| Removed | Reason |
| --- | --- |
| Stride booking engine (find-slots, book-appointment, list-providers, check-availability, create-appointment), slot cache, booking-worker | No Stride connection yet; the outreach agent does not book |
| Stride SFTP import (stride-worker) and the Stride link in "Already booked" | No Stride feed |
| Keap sync (keap-worker, OAuth, outbox handoff) | Not connected yet |
| n8n routes, HMAC, webhook push, `SHEET_SYNC_MODE` | The sheet-worker owns the Sheet directly |
| Dashboard Add lead, Appointments page, booking card | Leads only from the Sheet; no booking records exist |
| Demo/dev tooling (`rpt demo`, fixtures, local mock stack, booking voice tests, `sync_vapi.py`) | Not used in production |

When Stride and Keap are connected, production moves to the demo codebase rather than re-adding pieces
here (the schema already matches).

## 7. Operations

- Deploy and server steps: `../Deployment-AWS-EC2.md`.
- Health: `GET /health` (liveness), `GET /ready` (config + DB). Sheet-worker heartbeat in
  `service_heartbeats`. Logs: `docker compose logs -f <service>` and JSONL files under `logs/`.
- Production data is real patient data: mask names and phone numbers in any output.

## Changelog

### 2026-10-16 — Production build created from demo 2ec1cd3
- Copied the demo backend (2026-10-15, commit 2ec1cd3) and removed Stride, Keap, the booking engine, n8n and
  dev tooling (section 6). 326 tests pass on a local Postgres (pgserver), ruff clean.
- Sheet sync is direct-only (no mode switch); `N8N_PRACTICE_SLUG` became `PRACTICE_SLUG`; the queue label
  `n8n` is kept as `SHEET_DESTINATION` so the schema matches demo.
- "Already booked" now means: same phone + name + DOB + case marked Booked in the last 30 days (no visit
  dates without Stride).
- Calls send only the variables the outreach agent reads (`Patient_name`, `call_attempt`, `lead_id`,
  `outreach_event_id`, `patient_name`, `booking_link`, `day_offset`); checked against the live prompt.
- The booking-link text is the only notification sent; booked board cards and lead pages show
  "Booked (marked by staff)".
- Startup checks no longer ask for Stride/Keap/n8n secrets; `SLOT_TOKEN_SECRET` became
  `PHONE_FINGERPRINT_SECRET` (only the test-usage report uses it).
- `config/` now holds a masked backup of the live outreach agent (`scripts/vapi_export.py`).
- The Docker image installs exact versions from `requirements.txt` (exported from `uv.lock`).
- One-time production clean-up SQL written and tested on a throwaway database (guards: migrations applied,
  no non-test lead).
- Independent review fixes: the clean-up SQL also removes old per-lead cadence copies (RESTRICT children
  first) and pins `practice_settings.vapi_assistant_id` to the outreach agent (demo had switched to the
  booking agent; the DB value wins over `.env`); re-tested on a throwaway database.
- Dashboard proxy: a backend 401 now returns 502 "service unavailable" (a token mismatch used to loop
  between /login and /), the origin rule is a tested helper (`dashboard-origin.ts`: HTTPS, or http only to
  `api`/`localhost`), and the real body size is checked (chunked bodies had skipped the limit).
- Staff roster in `dashboard.env` is single-quoted so Docker keeps `$`/`#`; Caddy compression removed
  (the demo had none; it can delay streamed answers); deployment guide: Day 0 timing, rollback meaning,
  cutover timing, certificate note, Drive API, troubleshooting.

### 2026-10-16 — Testing switch, repo, cutover plan
- `TESTING_MODE` (replaces the dev-only `TEST_MODE`): when true every new Sheet lead is `is_test`, so the
  existing compressed path applies (`TESTING_DAY_MINUTES`, default 1; calling hours and daily limits skipped
  in `CLAIM_SQL`). Allowed in production; worker warning, `/ready` and snapshot `testing_mode`, dashboard
  banner. Tests: Sheet start in production+testing mode makes a fast test lead; without it a real lead.
- `make-server-env.sh` also copies `GOOGLE_SHEET_ID` from the old server `.env`.
- Repo: github.com/rjm2007/Stride_Raush_pt_deployed_Backend. Cutover plan: same EC2 and domain, old stack
  deleted (owner's decision), current Sheet + service account for now (old rows moved to another tab first).
- Test numbers: `TEST_TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM_NUMBER` and `TEST_VAPI_PHONE_NUMBER_ID`. In testing
  mode every text and call goes from them (the test Vapi id beats `practice_settings`); off = live number.
  Twilio webhook signatures are checked against both accounts' tokens.
