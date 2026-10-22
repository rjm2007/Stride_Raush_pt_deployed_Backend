# tests — pytest suite

Run from the repo root (`backend/`):

```bash
~/.local/bin/uv run --frozen python -m pytest -q
~/.local/bin/uv run --frozen ruff check src tests scripts
```

Most tests need no database or network: they fake the psycopg connection (small `Connection` / `_Rows`
classes that match on SQL text) and monkeypatch provider clients. Follow that pattern for new tests.

DB suites (`*_integration.py`) run only with `TEST_DATABASE_URL` set, otherwise they skip. Point it at a
**local, throwaway** Postgres, never demo or production (a demo run once wiped demo data). Without Docker,
the `pgserver` pip package runs an embedded Postgres 16; it lacks `pgcrypto`, which migration 001 only
creates (`gen_random_uuid` is built in), so register an empty `pgcrypto` extension in that install first,
then `rpt migrate` and `rpt seed` with `SUPABASE_DB_URL` set to the same local URL.

| File | Covers |
| --- | --- |
| `test_worker.py` | Cadence materialization, claim rules, dispatch (call variables the outreach agent reads), sweepers |
| `test_dashboard.py` | Dashboard API: roles, board stages, cadence versions, activity feed, delete, no lead create |
| `test_lead_actions.py`, `test_lead_actions_integration.py` | Sheet commands (start/restart/DNC/booked, cooldown, Already booked), profile sync, Sheet snapshots, row model |
| `test_google_sheet.py`, `test_sheet_direct.py`, `test_sheet_direct_integration.py` | Sheet sync with `fake_sheet.FakeSheet`: header mapping, moved-row safety, labels; end to end on a real schema |
| `test_number_block_integration.py` | Block / unblock a number end to end |
| `test_delivery.py`, `test_unspoken_call.py`, `test_last_decision.py` | Vapi end-of-call settlement, outcomes, booking-link text |
| `test_review_pause.py`, `test_callback_timing.py` | Review/pause behaviour, callback scheduling |
| `test_lead_review.py`, `test_lead_review_integration.py` | Review codes/choices/Sheet words; every group's choices end to end, no Resume/board shortcut, history, phone change closes, calls only never texts; Booked / Do Not Contact / Restart typed on a flagged Sheet row; keep old name writes the old name back (no new review, no sync loop, a third name is kept) |
| `test_security.py` | Dashboard headers, Vapi/Twilio auth |
| `test_api_contract.py`, `test_vapi_contract.py`, `test_vapi_tool_config.py` | HTTP and Vapi contracts; the committed agent backup matches this backend; no booking routes |
| `test_retry.py` | Retry delays and production startup checks (no Stride/Keap/n8n secret needed) |
| `test_providers.py`, `test_mock_server.py` | Provider clients, mocks |
| `test_agent.py` | Staff assistant (no appointment context) |
| others | parsing, observability, usage report, test-lead reset |

Every bug fix should add a regression test here that fails without the fix.
