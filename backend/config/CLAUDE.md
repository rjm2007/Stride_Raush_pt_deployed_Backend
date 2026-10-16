# config — backup of the live outreach voice agent

Written by `scripts/vapi_export.py` (read-only against Vapi). Secret values are replaced with placeholders,
so these files are safe in git. They are a **backup and a contract check**, not a deploy source: the agent
is edited in the Vapi dashboard, then this folder is refreshed.

| File | Contents |
| --- | --- |
| `vapi_assistant.json` | Assistant `540ddb07…` ("Outreach Agent - Test"): model, voice, transcriber, server URL (`/api/v1/vapi/webhook`), analysis plan |
| `vapi_assistant_prompt.md` | Its system prompt |
| `vapi_tools.json` | Its two tools: `update_lead_status` (→ `/api/v1/webhooks/vapi/lead-status`, header `X-Vapi-Secret` = `VAPI_WEBHOOK_SECRET`) and `transfer_tool_outreach` (transfer to the front desk) |

`tests/test_vapi_tool_config.py` checks that the agent has only these tools, that every status it can send
is handled, that it reads only variables the worker sends, and that no secret is committed.

The agent's tool and webhook URLs point at `https://stride.aibolt.ai`. If the domain changes, update them in
Vapi (and `PUBLIC_BASE_URL`), then re-run the export.
