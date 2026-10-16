# routes — FastAPI routers

Thin HTTP layer: authenticate, validate with pydantic, call a service, shape the response. Business logic
belongs in `services/`. Every router is exported from `__init__.py` and registered in `api.py`.

| File | Prefix | Caller | Endpoints |
| --- | --- | --- | --- |
| `health.py` | — | ops / Docker | `GET /health` (liveness), `GET /ready` (config + DB) |
| `leads.py` | `/api/v1/webhooks/vapi` | Vapi outreach agent | `POST /lead-status` — the `update_lead_status` tool: booking link, callback, transfer, declined, do not contact, wrong person, no answer |
| `vapi.py` | `/api/v1/vapi` | Vapi | `POST /tools` (compat tool endpoint, `update_lead_status` only), `POST /webhook` (end-of-call report, stored durably then processed) |
| `twilio.py` | `/api/v1/twilio` | Twilio | `POST /inbound-sms` (replies, STOP, CALL), `POST /message-status` (delivery callbacks); signature-checked |
| `dashboard.py` | `/api/v1/dashboard` | dashboard proxy | snapshot, lead detail/delete, cadence pause/resume, contact rules (block/unblock), board stage moves, review resolve, outreach reschedule, cadence versions/steps, message templates, manual SMS |
| `tool_request.py` | — | helper | shared Vapi tool-request authentication |

The staff assistant router (`/api/v1/dashboard/assistant`) lives in `../agent/router.py`.

There is no lead-create endpoint (leads come only from the Google Sheet) and no booking, Stride, Keap or
n8n route; `tests/test_api_contract.py::test_booking_tools_are_not_served` keeps it that way.

## dashboard.py essentials

- `_stage(row)` (from `services/lead_stage.py`) decides the board column (new / cadence / attention / booked /
  closed). Order of checks matters: booked → attention → closed statuses → new/pending → paused stays
  `cadence` → spent cadence = closed.
- `_lead(row)` shapes a lead for the board; `GET /snapshot` returns all leads + metrics; `GET /leads/{id}`
  returns detail with events, calls, messages, history and the `activity` feed. Booked leads carry no
  booking record (none exists): their outcome reads "Booked (marked by staff)".
- `_audit(...)` writes `dashboard_audit_log` with actor name and lead id; call it for every staff mutation.
- `_require_super_admin` guards global cadence/template writes and deletes (call it before opening a
  transaction).
- `POST /leads/{id}/stage` drives board drag-and-drop (Booked marks the lead booked; New restarts from Day 0).

## When adding a dashboard endpoint

Also add its path to `ALLOWED_PATH` in `../../../../frontend/app/api/dashboard/[[...path]]/route.ts`, or the
dashboard proxy rejects it with "dashboard path not allowed". Deploy both together.
