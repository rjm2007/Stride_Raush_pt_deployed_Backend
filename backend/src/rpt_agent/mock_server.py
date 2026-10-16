from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from itertools import count

from fastapi import FastAPI, HTTPException, Request

from .observability import WorkflowTrace, configure_logging

configure_logging("mock-provider")
app = FastAPI(title="RPT Deterministic Provider Mocks", version="0.1.0")
_ids = count(int(time.time()))  # restart-safe: never re-issues an id a previous run stored


def scenario(request: Request) -> str:
    return request.headers.get("x-mock-scenario", "success")


async def apply_scenario(value: str) -> None:
    if value in {"delay", "timeout"}:
        await asyncio.sleep(15 if value == "timeout" else 1)
    if value in {"provider_error", "failure"}:
        raise HTTPException(status_code=503, detail="mock provider error")
    if value == "rate_limit":
        raise HTTPException(status_code=429, detail="mock rate limit")


@app.get("/health")
def health():
    return {"status": "ok", "service": "mock-provider"}


@app.post("/mock/vapi/calls", status_code=201)
async def create_call(request: Request):
    trace = WorkflowTrace("mock_vapi_call", "mock-provider", request.headers.get("x-trace-id", ""))
    selected = scenario(request)
    trace.log("mock_scenario_selected", scenario=selected)
    await apply_scenario(selected)
    if selected == "malformed":
        return {"unexpected": True}
    call_id = f"mock-call-{next(_ids)}"
    trace.complete(call_id=call_id)
    return {"id": call_id, "status": "queued"}


@app.get("/mock/vapi/tool-call/{outcome}")
def generated_tool_call(outcome: str, lead_id: str = "synthetic-lead", event_id: int = 1):
    allowed = {"booked", "no_answer", "voicemail", "declined", "callback", "malformed"}
    if outcome not in allowed:
        raise HTTPException(status_code=400, detail="unknown mock outcome")
    if outcome == "malformed":
        return {"message": {"toolCallList": [{"unexpected": True}]}}
    mapped = "not_interested" if outcome == "declined" else outcome
    return {"message": {"type": "tool-calls", "toolCallList": [{
        "id": f"mock-tool-{next(_ids)}", "name": "record_call_outcome",
        "arguments": {"lead_id": lead_id, "outreach_event_id": event_id, "outcome": mapped},
    }]}}


@app.get("/mock/vapi/end-of-call/{outcome}")
def generated_end_of_call(outcome: str, lead_id: str = "synthetic-lead", event_id: int = 1):
    reasons = {
        "booked": "assistant-ended-call", "no_answer": "customer-did-not-answer",
        "voicemail": "voicemail", "declined": "customer-ended-call", "callback": "assistant-ended-call",
    }
    if outcome not in reasons:
        raise HTTPException(status_code=400, detail="unknown mock outcome")
    now = datetime.now().astimezone()
    return {"message": {"type": "end-of-call-report", "endedReason": reasons[outcome],
        "startedAt": (now - timedelta(seconds=30)).isoformat(), "endedAt": now.isoformat(),
        "call": {"id": f"mock-call-{next(_ids)}", "assistantOverrides": {"variableValues": {
            "lead_id": lead_id, "outreach_event_id": str(event_id)
        }}}}}


@app.post("/mock/twilio/messages", status_code=201)
async def create_message(request: Request):
    trace = WorkflowTrace("mock_twilio_message", "mock-provider", request.headers.get("x-trace-id", ""))
    selected = scenario(request)
    trace.log("mock_scenario_selected", scenario=selected)
    await apply_scenario(selected)
    if selected == "malformed":
        return {"unexpected": True}
    sid = f"SM{next(_ids):032d}"
    trace.complete(provider_message_id=sid)
    return {"sid": sid, "status": "queued"}


@app.get("/mock/twilio/inbound/{command}")
def generated_twilio_inbound(command: str, phone: str = "+15555550123"):
    if command.lower() not in {"stop", "call", "hello"}:
        raise HTTPException(status_code=400, detail="unknown inbound scenario")
    return {"From": phone, "Body": command.upper(), "MessageSid": f"SM{next(_ids):032d}"}


@app.get("/mock/twilio/status/{status}")
def generated_twilio_status(status: str, sid: str = "SM00000000000000000000000000000001"):
    if status not in {"queued", "sent", "delivered", "undelivered", "failed"}:
        raise HTTPException(status_code=400, detail="unknown delivery status")
    return {"MessageSid": sid, "MessageStatus": status}


@app.post("/mock/reset")
def reset():
    return {"ok": True}
