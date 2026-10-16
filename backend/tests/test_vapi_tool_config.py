"""The committed backup of the live outreach agent (scripts/vapi_export.py) matches this backend."""

import inspect
import json
from pathlib import Path

from rpt_agent.services import lead_status

TOOLS = json.loads(Path("config/vapi_tools.json").read_text(encoding="utf-8"))
ASSISTANT = json.loads(Path("config/vapi_assistant.json").read_text(encoding="utf-8"))


def _tool(name):
    return next(t for t in TOOLS if (t.get("name") or t.get("function", {}).get("name")) == name)


def test_the_agent_has_only_the_status_and_transfer_tools():
    # No booking tools: the agent texts the booking link, transfers, or agrees a callback.
    names = {t.get("name") or t.get("function", {}).get("name") for t in TOOLS}
    assert names == {"update_lead_status", "transfer_tool_outreach"}
    assert _tool("transfer_tool_outreach")["type"] == "transferCall"


def test_status_tool_posts_to_our_lead_status_endpoint():
    tool = _tool("update_lead_status")
    assert tool["server"]["url"].endswith("/api/v1/webhooks/vapi/lead-status")
    assert ASSISTANT["server"]["url"].endswith("/api/v1/vapi/webhook")


def test_every_status_the_agent_can_send_is_handled():
    statuses = _tool("update_lead_status")["function"]["parameters"]["properties"]["status"]["enum"]
    source = inspect.getsource(lead_status.report_lead_status)
    for status in statuses:
        assert f'"{status}"' in source, status
    # Booking is never a voice outcome in this build.
    assert "booked" not in statuses


def test_no_secret_is_committed():
    for path in ("config/vapi_tools.json", "config/vapi_assistant.json"):
        text = Path(path).read_text(encoding="utf-8")
        for headers in [t.get("server", {}).get("headers", {}) for t in TOOLS] + [
            ASSISTANT.get("server", {}).get("headers", {})
        ]:
            assert all(value.startswith("<secret") for value in headers.values()), path
        assert "Bearer " not in text


def test_prompt_reads_only_variables_the_worker_sends():
    prompt = Path("config/vapi_assistant_prompt.md").read_text(encoding="utf-8")
    sent = {"Patient_name", "call_attempt", "lead_id", "outreach_event_id", "patient_name",
            "booking_link", "day_offset"}
    import re

    used = set(re.findall(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", prompt))
    liquid_locals = set(re.findall(r"assign\s+([A-Za-z_][A-Za-z0-9_]*)", prompt))
    assert used - liquid_locals <= sent
