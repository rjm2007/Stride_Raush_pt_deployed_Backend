# services — business workflows and provider clients

Routes and the workers call into these. Each workflow owns its SQL and runs inside the caller's
`transaction()` connection unless noted.

## Workflows

| File | What it owns |
| --- | --- |
| `lead_actions.py` | Google Sheet commands: `execute_lead_action()` (start / restart / DNC / booked, idempotent on request ID via `lead_action_requests`) and `sync_sheet_lead()` (profile sync; a name change is flagged for review with old/new name, a phone change closes the lead at once). `_restart_cadence` has a 10-min cooldown. "Already booked" = same phone + name + DOB + case marked Booked in the last 30 days. |
| `sheet_models.py` | Pydantic shape of one Sheet row (`SheetLeadInput`, `LeadActionRequest`): field rules, Case/lead_type alias. |
| `lead_status.py` | Lead/call state machine: `apply_call_outcome()`, `report_lead_status()` (the agent's tool), callbacks clamped to business hours, booking-link text queued 2 min after the call decision, explicit opt-outs, `mark_booked()`, status history. A voice "booked" is refused (it needs an appointment row, which this build never creates). |
| `delivery.py` | Settles provider results: Vapi end-of-call reports (`process_vapi_end_report`, transcripts, structured outcome), Twilio delivery status, the booking-link text (`process_pending_integrations`, the only notification this build sends), reprocessing of failed webhooks. |
| `lead_stage.py` | `stage_of()` (board column, used by `routes/dashboard.py` as `_stage`) and `sheet_lead_status()` (the Sheet's Lead Status mirrors the column: New / In cadence / Paused / Needs Review / Booked / Do not outreach / Closed). |
| `review.py` | `skip_remaining_planned` / `restore_pause_skipped` (pause/resume mechanics), `flag_lead_for_review` + `record_review` (every flag gets a `lead_reviews` row with a code), `hand_over_number` (one active lead per phone; new lead inherits opt-outs). |
| `lead_review.py` | Review codes → groups → choices, plain reasons (Twilio codes), `describe()` card, `options_preview()` (confirm pop-up), `resolve_review()` (resume/close), `close_for_phone_change()`, Sheet review texts. |
| `number_block.py` | Dashboard Do not contact switch: `block_number()` (same effect as the Sheet command) and `unblock_number()` (admin only; must choose `continue` or `restart`, clears opt-outs on the number, tells the Sheet). |
| `google_sheet.py` | Google Sheet access (gspread, service account): narrow scans and full reads, columns by header text, queued cell writes that re-check each row's identity (Lead ID, Action Request ID, Name, Phone) just before writing. |
| `sheet_direct.py` | The Sheet rules and labels: claim → `execute_lead_action`, stuck-row recovery with the same request ID, profile sync by fingerprint (`sheet_row_state`), snapshot → row, nightly archive. Contract: `../../../docs/GOOGLE_SHEET.md`. |
| `sheet_sync.py` | Builds the Sheet snapshot (`build_sheet_snapshot`) and queues it (`enqueue_sheet_update` → `integration_outbox`, `destination=SHEET_DESTINATION`). Omits `action_status` unless booked / DNC / completed so the Sheet keeps the existing cell. |

## Provider clients

| File | Provider |
| --- | --- |
| `provider_http.py` | `ProviderService` base: bounded timeouts, retries, `ProviderError` classification, the `OUTBOUND_ENABLED` stop. All provider clients extend it. |
| `vapi_service.py` | Vapi outbound call creation. |
| `twilio_service.py` | Twilio message send (uses `TWILIO_FROM_NUMBER`). |

## Notes

- Anything that skips or creates `outreach_events` changes who gets called; add a test in `tests/`.
- Sheet-facing result codes (`*_needs_review`, `restart_too_soon`, `lead_already_exists`, …) are turned into
  Sheet text in `sheet_direct.py`; keep `docs/GOOGLE_SHEET.md` in sync when adding one.
- Provider mode (real/mock) is chosen in config; never branch business logic on it.
