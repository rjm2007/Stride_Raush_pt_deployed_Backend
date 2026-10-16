from fastapi.testclient import TestClient

from rpt_agent.mock_server import app

client = TestClient(app)


def setup_function():
    client.post("/mock/reset")


def test_scenarios_and_provider_ids():
    created = client.post("/mock/vapi/calls", json={}, headers={"X-Trace-ID": "trace-x"})
    assert created.status_code == 201
    assert created.json()["id"].startswith("mock-call-")
    malformed = client.post("/mock/vapi/calls", json={}, headers={"X-Mock-Scenario": "malformed"})
    assert "id" not in malformed.json()
    rate = client.post("/mock/twilio/messages", headers={"X-Mock-Scenario": "rate_limit"})
    assert rate.status_code == 429
    tool = client.get("/mock/vapi/tool-call/booked").json()
    assert tool["message"]["toolCallList"][0]["arguments"]["outcome"] == "booked"
    report = client.get("/mock/vapi/end-of-call/voicemail").json()
    assert report["message"]["type"] == "end-of-call-report"
