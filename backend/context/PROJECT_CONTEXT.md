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

Schema identical to demo (migrations 001–045 and 048; demo also has 046–047). Unused Stride/Keap/booking tables stay empty. Production was
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

### 2026-10-16 — Wrong-number leads can be resumed; clearer refusals

- A "wrong number" call sets `invalid_phone`, pauses the lead and flags it for review. Resume on the
  dashboard refused it ("terminal leads cannot resume cadence") and Sheet Restart refuses `invalid_phone`,
  so the lead was stuck. Resume now means staff confirmed the number: status back to `in_progress`, review
  cleared, paused steps restored. Booked, declined and Do Not Contact still refuse, each with its own reason.
- Sheet Restart refusal names the real reason ("An invalid phone lead…" / "A Do Not Contact lead…").
- The Sheet's Lead Status already writes `Closed` for a finished cadence, a declined patient and a confirmed
  wrong number; the Lead Status dropdown in the Sheet must list it (with New and Paused).

### 2026-10-19 — Real cadence checked end to end; order fix

- Simulated the real cadence (TESTING_MODE=false, production's Standard v13 and settings) on a local
  database for leads started every weekday, after hours and at weekends, with the worker's own claim and
  close rules on a moving clock. Weekends, 9–5 California hours and the daily limits held; all 9 steps ran
  and each lead closed after the last one.
- Fixed: a weekend shift could put two cadence days on the same Monday, and the later one went first (a
  Sunday lead got the Day 1 reminder before the Day 0 call). Each cadence day now gets its own business
  day, in order (`materialize_cadence`). A cadence can therefore end a day or two after calendar day 14.
- First contact is now immediate (owner, 2026-10-19). A lead added in calling hours gets its Day 0 call
  right away (in practice 1–2 minutes: Sheet settle + polls), then the Day 0 text 3 minutes later. Added
  before 9 AM → at 9:00; added in the last 15 minutes before closing, after hours or at a weekend/holiday →
  9:00 on the next business day. Later cadence days run at the same time of day as Day 0, counted from
  the Day 0 date. The old hash-of-lead-id spread over the day (`compute_send_time`) is gone
  (`first_contact_time`, `cadence_day_time`). Simulated again for 10 start times: all rules held.
- Clinic hours and holidays confirmed by the clinic (Emma): Mon–Fri 8 AM–7 PM, Sat 8 AM–1:30 PM, Sun
  closed; last new contact 15 min before closing (6:45 PM / 1:15 PM); limits unchanged; 8 holidays (dates
  to the end of 2028). Applied with `supabase/prod/2026-10-19_clinic_hours_holidays.sql`. The worker's
  claim now also skips holidays (before, only planning did, so a held-back step could go out on one).

### 2026-10-22 — Clear review reasons, resolve with a choice (migration 048)

Incident 2026-10-21: one lead was flagged because its Name cell was edited, another because its Day 0 text
failed with Twilio 30006 (landline). Staff pressed Resume: the steps came back but `needs_review` stayed, so
the worker sent nothing while the page said "Pause cadence". Nothing recorded what changed or who decided.

- `lead_reviews` (migration 048): one row per flag (reason code, plain message, details such as old/new
  name or the Twilio code, source, time) and its resolution (who, choice, note, time). Every flag path
  passes a code (`review.flag_lead_for_review` / `record_review`); the 030 fail-safe (replaced in 048) writes
  a row too; a deferred trigger gives any other flag a row from its `review_reason`; clearing
  `needs_review` closes open rows (booked, DNC, restart, unblock…). Existing flagged leads were backfilled.
- Groups and choices (`services/lead_review.py`): name (use new name / keep old name / different person),
  text (calls only / try texting again, hidden for landline-type codes / front desk), call (number is
  right / wrong number / front desk), not confirmed + other (continue / front desk), number blocked (front
  desk; unblock stays on the lead page). Any staff member or admin may resolve.
- Continue choices fully resume: review closed, status `in_progress`, cadence `active`, the
  `paused_for_review` steps restored and shifted by the time in review (at least enough that the earliest
  step lands now, so one step goes out promptly and the rest keep their spacing; the worker still applies
  calling hours). Front desk: `closed_no_response` + `terminated`, reason "Handled by front desk". Wrong
  number / different person / phone changed: `invalid_phone` + `terminated` = closed for good (Resume, the
  board's In cadence/New and Sheet Restart all refuse).
- A phone number changed in the Sheet is no longer a review: the old lead closes at once; staff add a row.
- Calls only: `leads.sms_disabled` (not `sms_opt_out`, which means the patient sent STOP, is inherited by a
  new referral on the number and is cleared by an unblock). CLAIM_SQL never texts it, booking-link texts
  are cancelled, a restart plans its texts as skipped. Not inherited by a new lead on the number.
- `leads.sheet_name_accepted`: "keep old name" remembers the Sheet value so profile sync never re-flags it.
- Resume and the board's In cadence refuse a flagged lead (409, plain message); board New/Closed/Booked on
  a flagged lead record the resolution with the staff name. `GET /review/{id}` returns the card and, per
  choice, the effect and next step for the confirm pop-up; `POST /review/{id}/resolve` takes `choice` + `note`.
- Sheet: Outcome Status texts only (docs/GOOGLE_SHEET.md); Message Outcome `Calls only (texts off)`.
- Twilio's own error code (e.g. 21614) now travels in a refused-send error, so the card can say "landline".
- QA fixes (same day): reviews on one lead are settled one at a time, oldest first (a choice applies its
  effect, e.g. texts off, and the lead stays paused until the last review), so "use new name" can no longer
  turn texts back on for a landline. A phone change blocks restart/resume/New/unblock-continue on the old
  number whatever the status (a Booked lead stays Booked). Pre-048 name reviews show the name on file, do
  not offer "use new name", and "keep old name" accepts whatever the Sheet row holds at the next profile
  sync. Review texts in the Sheet never overwrite a command staff typed and the worker has not run yet.
  Resume refuses a closed lead (front desk, finished). Legacy wrong-person cards show the agent's note.
- QA round 2: no "accept the next Sheet name" marker. sheet_row_state.sheet_name keeps the Name the
  Sheet worker last read; a pre-048 name review gets old -> new filled from it on the next read (nothing
  resolved or flagged), and "keep old name" before that accepts only that recorded name (refused if none
  is recorded). Any phone_changed record blocks restart/resume on the old number, however it was settled.
  "Try texting again" chosen while another review is open is planned when the lead finally resumes.
  Pause is refused on a closed lead like Resume.

### 2026-10-23 — Sheet: commands typed on a row in review (port of demo 392b9ff)
- QA (demo): a Booked typed on a "Needs review: wrong number" row was ignored without a word, and resolving
  "Number is right" then wrote "Start cadence" over it: the lead was never booked and calls restarted.
- On a row whose Outcome Status is a review text this backend writes ("Needs review: ...", "Number blocked;
  needs review"), Booked and Do Not Contact run as on any row and close the review ("booked" /
  "do_not_contact"). Old n8n texts ("Phone number changed; needs review") still block every command.
- Restart cadence on such a row waits: the row says "<review text>; resolve it on the dashboard first, then
  the restart runs" and keeps the Action; it runs once the review is resolved. It is dropped when the
  dashboard ends the lead (close choices, front desk, board Booked, Do not contact, phone change): Outcome
  Status "<result>; the Restart in Action was not run", Action reset. Clearing Action removes the words.
- The backend never leaves a Restart next to a review text it writes (a flag, or a Restart that ends in
  "Number blocked; needs review", turns it into "Start cadence"), so a Restart there was typed by staff.
- `apply_snapshot` decides on the row before it writes: Action is never written over a command staff typed
  that has not run, nor over a waiting Restart. Tests: `test_sheet_direct.py`, `test_lead_review_integration.py`.

### 2026-10-23 — Resolve pop-up says why a review is already closed (port of demo ca47b79 + c1b6acb)
- A lead page opened before its review closed (e.g. a newer Sheet row on the same phone replaced the lead)
  still showed Resolve review, and Confirm only said "no longer available".
- `lead_review.closed_review()` / `resolution_label()`; `OUTCOME_LABELS` moved out of `routes/dashboard.py`.
  `GET /dashboard/review/{id}` keeps `review: null, options: []` and adds `closed: {reason, message}`; the
  resolve 409 detail carries the same message. Dashboard: "Review already closed" + Refresh page.

### 2026-10-23 — Sheet: "keep old name" writes the old name back into the row (port of demo 3722cc5)
- Demo test: after "Same person, keep old name & continue" calls resumed under the old name, but the row's Name
  still showed the new one.
- `resolve_review` (choice `keep_old_name` with a recorded new name) queues a second Sheet update, reason
  `name_kept`; `build_sheet_snapshot` adds `name` (on file) and `name_replaces` (reviewed new name).
  `apply_snapshot` writes the Name cell only while it still shows `name_replaces`; a third name is left alone.
- The cell is re-checked just before the write (`SheetGrid.set(expect=...)`, `FlushResult.skipped_rows`).
  After the write the stored fingerprint follows (`_save_renamed`, only if the row was otherwise in sync) and
  `leads.sheet_name_accepted` is cleared, so the same new name typed again opens a new review.
- A pre-048 name review takes its new name from the Name the Sheet worker last read (`_legacy_sheet_name`), so
  "keep old name" on it also writes the name on file back (`test_legacy_name_review_keep_old_name_...`).
