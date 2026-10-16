import json

from fastapi.testclient import TestClient

import rpt_agent.api as api_module
import rpt_agent.routes.leads as lead_routes
import rpt_agent.routes.tool_request as tool_request_routes
import rpt_agent.routes.vapi as vapi_routes
from rpt_agent.config import get_settings


def test_vapi_tools_require_auth(monkeypatch):
    client = TestClient(api_module.app)
    response = client.post("/api/v1/vapi/tools", json={})
    assert response.status_code == 401


def test_vapi_results_preserve_order_and_business_errors_use_200(monkeypatch):
    seen = {}

    def fake_outcome(trace, **kwargs):
        seen.update(kwargs)
        return "recorded"

    monkeypatch.setattr(vapi_routes, "apply_call_outcome", fake_outcome)
    client = TestClient(api_module.app)
    payload = {"message": {"toolCallList": [
        {"id": "one", "name": "update_lead_status",
         "arguments": {"lead_id": "lead-1", "outreach_event_id": "7", "outcome": "no_answer"}},
        {"id": "two", "name": "unknown", "arguments": {}},
    ]}}
    response = client.post(
        "/api/v1/vapi/tools", json=payload,
        headers={
            "Authorization": f"Bearer {get_settings().vapi_webhook_secret}",
            "X-Trace-ID": "trace-api",
        },
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert [item["toolCallId"] for item in results] == ["one", "two"]
    assert json.loads(results[0]["result"])["status"] == "recorded"
    assert (seen["lead_id"], seen["event_id"], seen["outcome"]) == ("lead-1", 7, "no_answer")
    assert "error" in results[1]
    assert "\n" not in results[1]["error"]
    assert response.headers["X-Trace-ID"] == "trace-api"


def test_booking_tools_are_not_served(monkeypatch):
    # This build has no Stride booking: the old availability / booking tools must not answer,
    # and the compatibility tool endpoint refuses their names.
    client = TestClient(api_module.app)
    auth = {"Authorization": f"Bearer {get_settings().vapi_webhook_secret}"}
    for path in ("/api/v1/tools/check-availability", "/api/v1/tools/create-appointment",
                 "/api/v1/tools/find-slots", "/api/v1/tools/book-appointment",
                 "/api/v1/integrations/n8n/lead-actions"):
        assert client.post(path, json={}, headers=auth).status_code == 404
    payload = {"message": {"toolCallList": [
        {"id": "one", "name": "check_availability", "arguments": {"lead_id": "lead-1"}},
    ]}}
    results = client.post("/api/v1/vapi/tools", json=payload, headers=auth).json()["results"]
    assert "unsupported tool" in results[0]["error"]


def test_direct_lead_status_threads_call_id_and_status(monkeypatch):
    seen = {}

    def fake_report(trace, **kwargs):
        seen.update(kwargs)
        return "recorded"

    monkeypatch.setattr(lead_routes, "report_lead_status", fake_report)
    monkeypatch.setattr(tool_request_routes, "record_integration_event", lambda *args, **kwargs: None)
    client = TestClient(api_module.app)
    response = client.post(
        "/api/v1/webhooks/vapi/lead-status",
        json={"message": {
            "call": {"id": "call-1", "assistantOverrides": {"variableValues": {
                "lead_id": "lead-1", "outreach_event_id": "7",
            }}},
            "toolCallList": [{
                "id": "tool-status",
                "name": "update_lead_status",
                "arguments": {"status": "declined", "notes": "declined scheduling"},
            }],
        }},
        headers={"X-Vapi-Secret": get_settings().vapi_webhook_secret},
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["toolCallId"] == "tool-status"
    assert seen["call_id"] == "call-1"
    assert seen["event_id"] == 7
    assert seen["status"] == "declined"
