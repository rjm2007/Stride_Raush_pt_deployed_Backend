# RPT outreach backend (production, cadence only)

Read `context/PROJECT_CONTEXT.md` before changing this code. It is the canonical description of what this
production build does and why. After a material change, update it and add a dated changelog entry.

Never place `.env` values, patient data, or real phone numbers in source control or documentation.

## What this is

Python 3.12 FastAPI service for the Rausch PT 14-day outreach cadence, **production build**. It is a cut-down
copy of the demo backend (`../../demo/aws_deployed_raush_pt_stride_keap`, commit 2ec1cd3, 2026-10-15) with
everything for Stride, Keap, the booking voice agent and n8n removed:

- Leads come **only from the Google Sheet**, read and written directly with a Google service account.
- The voice agent is the **outreach agent** (Vapi `540ddb07…`): it texts the booking link, transfers to the
  front desk, or books a callback. It never books an appointment.
- A lead is **Booked only when staff mark it** (Sheet `Booked` or the dashboard board). The cadence keeps
  running after a link, a transfer or a callback until then.
- Everything else from demo is kept: blocked numbers / Do Not Contact, STOP replies, pause / resume /
  restart, callbacks, review queue, cadence and template studio, staff roles, audit, staff assistant (off).

Three processes, one image (`docker-compose.yml` at the repo root):

| Process | Entry point | Job |
| --- | --- | --- |
| `api` | `uvicorn rpt_agent.api:app` | HTTP: Vapi lead-status tool + end-of-call webhook, Twilio webhooks, dashboard API, staff assistant |
| `worker` | `rpt-worker` (`worker.py`) | Claims due outreach events, places Vapi calls / sends Twilio SMS (incl. booking-link texts), runs sweepers. Exactly one instance. |
| `sheet-worker` | `rpt-sheet-worker` (`sheet_sync_worker.py`) | Reads the Google Sheet (commands, profile edits, stuck rows) and writes results into it (`services/sheet_direct.py`). |

CLI: `rpt migrate | verify | seed | tick | test-lead | sheet-check | sheet-archive | agent` (`cli.py`).

## Folder map

| Path | Contents | Has CLAUDE.md |
| --- | --- | --- |
| `src/rpt_agent/` | Application package (config, db, worker, security, observability) | yes |
| `src/rpt_agent/routes/` | FastAPI routers (thin HTTP layer) | yes |
| `src/rpt_agent/services/` | Business workflows and provider clients | yes |
| `src/rpt_agent/agent/` | Read-only staff assistant (LangChain + OpenAI), off in production | yes |
| `supabase/` | Ordered SQL migrations (same 001–045 as demo), seed, dev SQL, one-time prod SQL | yes |
| `tests/` | pytest suite (unit, contract, scenario; DB tests on a local Postgres) | yes |
| `config/` | Backup of the live outreach voice agent (prompt, settings, tools; secrets masked) | yes |
| `scripts/` | `vapi_export.py` (back up the agent), Sheet load test, usage report | yes |
| `docs/GOOGLE_SHEET.md` | The Sheet contract: columns, commands, labels, rules | |
| `context/PROJECT_CONTEXT.md` | Canonical context + changelog for production | |

## Commands

```bash
~/.local/bin/uv sync --frozen --extra dev --python 3.12
~/.local/bin/uv run --frozen python -m pytest -q        # full suite, must stay green
~/.local/bin/uv run --frozen ruff check src tests scripts
# after changing dependencies in pyproject.toml:
~/.local/bin/uv lock && ~/.local/bin/uv export --frozen --no-dev --no-hashes --no-emit-project \
  --format requirements-txt -o requirements.txt   # the Dockerfile installs exactly these versions
```

DB tests (`*_integration.py`) need `TEST_DATABASE_URL` pointing at a **local, throwaway** Postgres
(pgserver) with `rpt migrate` + `rpt seed` applied. Never point it at demo or production.

Deploy: see `../Deployment-AWS-EC2.md` (server, `docker compose`, `.env`).

## Core concepts (read before editing logic)

- **Lead** (`leads`): `status` (new, in_progress, callback_scheduled, needs_attention, booked, declined,
  do_not_contact, invalid_phone, closed_no_response, transferred_human, booking_link_sent) and
  `cadence_state` (pending, active, paused, completed, terminated) are separate fields.
- **Board column** comes from `services/lead_stage.py` (`stage_of`); the Sheet's Lead Status mirrors it.
- **Outreach event** (`outreach_events`): planned → in_flight → attempted → delivered / failed / unknown, or
  skipped.
- **Cadence**: global `cadence_versions` → `cadence_steps` → `message_templates`. `materialize_cadence()`
  (worker.py) creates one `outreach_events` row per step. A lead keeps the version it started on.
- **What stops a cadence**: staff Booked, Do Not Contact (patient or staff), "not interested", wrong person
  (paused for review), or the last step done (→ Closed, `closed_no_response`). A booking link, a transfer
  or a callback does **not** stop it.
- **Pause** skips remaining planned events; **resume** restores and shifts them. **Restart** re-plans from
  Day 0 (Sheet restarts have a 10-minute cooldown).
- **Suppression**: `suppressed_numbers` is per phone number; the worker skips any number on it. Admins can
  unblock from the dashboard (`services/number_block.py`).
- **Kill switch**: `OUTBOUND_ENABLED=false` stops every call and text (worker and provider layer).
- **Testing switch**: `TESTING_MODE=true` makes every lead the Sheet creates an `is_test` lead; for those the
  cadence day is `TESTING_DAY_MINUTES` (1) and `CLAIM_SQL` skips calling hours and daily limits. Leads keep
  the mode they were created in. Allowed in production (it is how the live server is tested); the worker
  logs `testing_mode_on`, `/ready` and the dashboard snapshot report it. With `TEST_TWILIO_*` and
  `TEST_VAPI_PHONE_NUMBER_ID` set, testing mode also sends every text and call from the test numbers
  (`Settings.twilio_account()`, `testing_vapi_phone_number_id()`, which beats the database value); Twilio
  webhooks verify with either account's token.
- **Idempotency**: provider callbacks dedupe on provider IDs; Sheet commands dedupe on the row's Action
  Request ID (`lead_action_requests`).
- **Roles**: dashboard requests carry `X-Dashboard-User-ID/Name/Role` plus the server token; `super_admin`
  is required for global cadence/template changes and deletes.
- **Stored "n8n" words**: `integration_outbox.destination='n8n'` (`SHEET_DESTINATION`), history source
  `n8n_sheet` and request keys `n8n:<id>` are plain labels kept so the schema matches demo. Nothing talks
  to n8n.

## Conventions

- Raw SQL via psycopg (`db.transaction()`), no ORM. Keep queries in the module that owns the workflow.
- Routes stay thin; logic lives in `services/`.
- **Schema stays identical to demo.** New migrations are written and tested in the demo repo first, then
  copied here with the same file name. Never edit an applied migration.
- Production data is real patient data: never print names, phone numbers or message bodies in full.
- Never write to the production database without the owner's go-ahead for that change.
- Comments explain *why* (often a past incident); match that style and keep them.
- Every behavior fix gets a regression test in `tests/`.
