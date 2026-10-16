# src/rpt_agent — application package

Top-level modules. HTTP lives in `routes/`, business workflows in `services/`, the staff assistant in `agent/`.

| Module | Purpose |
| --- | --- |
| `api.py` | FastAPI app: trace middleware, registers every router. Add new routers here. |
| `config.py` | `Settings` (pydantic-settings, reads `.env`) and `get_settings()`. Vapi/Twilio `*_MODE` real/mock, `runtime_errors()` startup checks per process. New env vars go here and in `../../../.env.example`. |
| `db.py` | Psycopg connection pool and `transaction()` context manager (dict rows). Use it for all SQL. |
| `worker.py` | Cadence worker. `materialize_cadence()` builds a lead's schedule; `CLAIM_SQL` decides what is due (business hours, daily caps, opt-outs, suppression, TEST_MODE); `dispatch_job()` calls Vapi/Twilio; `run_tick()` runs claim → dispatch → sweepers; advisory lock keeps a single dispatcher. |
| `sheet_sync_worker.py` | The Google Sheet loop (`run_direct_tick`): one narrow read per poll (full read every 5 min), commands/recovery/profile sync via `services/sheet_direct.py`, outbox snapshots written into the lead's row, heartbeat in `service_heartbeats`. |
| `security.py` | Auth for every inbound caller: dashboard token + identity headers (`DashboardActor`), Vapi secret/HMAC, Twilio signature. |
| `vapi_contract.py` | Parses Vapi tool-call payloads and end-of-call reports; maps Vapi ended reasons to call outcomes; builds tool responses. |
| `providers.py` | `ProviderClients` facade bundling the Vapi and Twilio services. |
| `observability.py` | JSON logging, PHI/secret redaction, `WorkflowTrace` (trace IDs across API, worker, providers). |
| `cli.py` | `rpt` command: migrate, verify, seed, tick, test-lead, sheet-check, sheet-archive, agent. |
| `usage_report.py` | Test-provider cost ledger (`test_usage_ledger`) and its client report. |
| `mock_server.py` | Deterministic Twilio/Vapi mocks (tests only). |
| `parsing.py`, `retry.py`, `api_schemas.py` | Small helpers: flexible dates, retry delays, OpenAPI-only request models. |

## Notes

- `worker.py` and `CLAIM_SQL` are safety-critical: a wrong condition calls real patients. Change with tests
  in `tests/test_worker.py` and read the surrounding comments first.
- Exactly one cadence worker may run (rate governors are per process; migration 025 enforces the claim
  protocol).
- `get_settings()` is cached (`@cache`); restart processes after `.env` changes.
- The practice DB row (`practice_settings`) overrides some `.env` values: `vapi_assistant_id`,
  `vapi_phone_number_id`, `booking_link_url` (the link the agent texts), business hours, daily caps.
- The outreach agent's prompt reads `{{Patient_name}}`, `{{call_attempt}}` and `{{lead_id}}`; `dispatch_job`
  sends exactly the variables in `tests/test_worker.py::test_call_sends_the_variables_the_outreach_agent_reads`.
