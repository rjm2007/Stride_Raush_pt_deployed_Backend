"""After-call outcome v2 end to end on a real schema (fake Sheet): the end-of-call report settles the
call from the structured output, stores it on the call log (migration 053), and the dashboard and the
Sheet say what happened. Ported from demo 08beb3f / 2d1e00e (2026-11-02).

Needs TEST_DATABASE_URL (a disposable local database with the migrations applied).
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_sheet_direct_integration import env  # noqa: F401 - the shared Sheet fixture

from rpt_agent.api import app
from rpt_agent.config import get_settings
from rpt_agent.observability import WorkflowTrace
from rpt_agent.services.delivery import process_vapi_end_report

pytestmark = pytest.mark.integration

HEADERS = {"X-Dashboard-Token": "x" * 32, "X-Dashboard-User-ID": "emma01",
           "X-Dashboard-User-Name": "Emma", "X-Dashboard-User-Role": "employee"}
SPOKE = [("user", "Hello?"), ("bot", "Hi, am I speaking with Asha Rao?"), ("user", "Yes, this is Asha."),
         ("bot", "Great. This is Elliot calling from Rausch Physical Therapy. Do you have a moment?")]


@pytest.fixture
def senv(env, monkeypatch):  # noqa: F811 - pytest fixture injection
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "x" * 32)
    get_settings.cache_clear()
    return env


def _get(path):
    return TestClient(app).get(f"/api/v1/dashboard/{path}", headers=HEADERS)


def _post(path, body):
    return TestClient(app).post(f"/api/v1/dashboard/{path}", json=body, headers=HEADERS)


def _call(senv, result, turns, *, ended="customer-ended-call"):
    """Start a Sheet row, put its Day 0 call on the line, and send the end-of-call report."""
    number = senv.start_row()
    senv.tick()
    lead_id = senv.cell(number, "lead_id")
    call_id = f"call-{uuid4().hex[:12]}"
    with senv.db.transaction():
        # Migration 025: only a worker using the claim protocol may put a step in flight.
        senv.db.execute("select set_config('rpt.worker_claim_protocol','v1',true)")
        event = senv.db.execute(
            "update outreach_events set status='in_flight',executed_at=now(),vapi_call_id=%s "
            "where id=(select id from outreach_events where lead_id=%s and channel='call' "
            "order by day_offset,id limit 1) returning id", (call_id, lead_id)).fetchone()["id"]
    outputs = {"so-v2": {"name": "Cadence Call Outcome v2", "result": result}}
    body = {"message": {
        "type": "end-of-call-report", "endedReason": ended,
        "call": {"id": call_id, "assistantOverrides": {"variableValues": {
            "lead_id": lead_id, "outreach_event_id": str(event)}}},
        "artifact": {"structuredOutputs": outputs, "transcript": "AI: hi\nUser: hello",
                     "messages": [{"role": r, "message": m} for r, m in turns]},
    }}
    outcome = process_vapi_end_report(WorkflowTrace("test", "test"), body)
    senv.tick()
    return number, lead_id, event, call_id, outputs, outcome


def _event(senv, event_id):
    return senv.db.execute("select status,outcome from outreach_events where id=%s", (event_id,)).fetchone()


def _planned(senv, lead_id):
    return senv.db.execute("select count(*) as n from outreach_events where lead_id=%s and status='planned'",
                           (lead_id,)).fetchone()["n"]


def test_no_decision_is_a_missed_call_and_the_output_is_stored(senv):
    number, lead_id, _, call_id, outputs, outcome = _call(
        senv, {"status": "no_decision", "summary": "Picked up, then silence."},
        [("user", "Hi."), ("bot", "Hi, am I speaking with Asha Rao?")])
    assert outcome == "no_answer"
    lead = senv.lead(lead_id)
    assert lead["cadence_state"] == "active" and not lead["needs_review"]
    assert _planned(senv, lead_id) > 0
    stored = senv.db.execute("select structured_output from call_logs where vapi_call_id=%s",
                             (call_id,)).fetchone()["structured_output"]
    assert stored == outputs
    assert senv.cell(number, "call_outcome") == "No answer"


def test_old_outcome_without_a_status_still_continues_the_cadence(senv):
    _, lead_id, _, _, _, outcome = _call(senv, {"summary": "Hung up during the introduction."}, SPOKE)
    assert outcome == "no_answer"
    assert senv.lead(lead_id)["cadence_state"] == "active"


def test_already_booked_closes_the_lead_with_that_reason(senv):
    number, lead_id, event, *_ = _call(
        senv, {"status": "already_booked", "summary": "Said she booked last week."},
        SPOKE + [("user", "Oh, I already booked with you last week.")])
    lead = senv.lead(lead_id)
    assert (lead["status"], lead["cadence_state"]) == ("declined", "terminated")
    assert lead["status_reason"] == "Already booked or already a patient"
    assert _event(senv, event)["outcome"] == "not_interested"
    assert _planned(senv, lead_id) == 0
    assert senv.cell(number, "outcome_status") == "Closed: already booked or already a patient"
    assert senv.cell(number, "call_outcome") == "Already booked or a patient"
    assert senv.cell(number, "action") == ""
    assert senv.cell(number, "lead_status") == "Closed"
    detail = _get(f"leads/{lead_id}").json()
    assert detail["lead"]["next_step"] == "Already booked or already a patient"
    titles = [entry["title"] for entry in detail["activity"]]
    assert "Closed: already booked or already a patient" in titles


def test_declined_on_the_call_says_so_in_the_sheet(senv):
    number, lead_id, *_ = _call(senv, {"status": "declined", "summary": "Not interested."},
                                SPOKE + [("user", "No thanks, I'm not interested.")])
    assert senv.lead(lead_id)["status"] == "declined"
    assert senv.cell(number, "outcome_status") == "Declined on the call"
    assert senv.cell(number, "call_outcome") == "Answered - declined"
    assert senv.cell(number, "action") == ""


def test_wrong_person_from_hi_then_silence_keeps_the_cadence(senv):
    """Production 28 Oct: "Hi" then silence was paused as wrong person from the summary alone."""
    _, lead_id, *_ = _call(senv, {"status": "wrong_person", "summary": "Wrong person."},
                           [("user", "Hi."), ("bot", "Hi, am I speaking with Asha Rao?")])
    lead = senv.lead(lead_id)
    assert lead["status"] != "invalid_phone" and not lead["needs_review"]
    assert lead["cadence_state"] == "active"


def test_a_real_wrong_person_pauses_with_a_wrong_number_card(senv):
    number, lead_id, *_ = _call(senv, {"status": "wrong_person", "summary": "Not Asha."},
                                [("user", "Yes?"), ("bot", "Hi, am I speaking with Asha Rao?"),
                                 ("user", "No, this is Maria. Wrong number.")])
    lead = senv.lead(lead_id)
    assert (lead["status"], lead["cadence_state"], lead["needs_review"]) == ("invalid_phone", "paused", True)
    card = _get(f"review/{lead_id}").json()["review"]
    assert card["code"] == "wrong_person"
    assert senv.cell(number, "outcome_status") == "Needs review: wrong number"


def test_family_member_keeps_the_cadence(senv):
    _, lead_id, *_ = _call(senv, {"status": "wrong_person"},
                           [("bot", "Hi, am I speaking with Asha Rao?"), ("user", "No, this is her mom.")])
    assert senv.lead(lead_id)["cadence_state"] == "active"


def test_transferred_without_a_transfer_keeps_the_cadence(senv):
    _, lead_id, event, *_ = _call(senv, {"status": "transferred_human", "summary": "Transferred."},
                                  SPOKE + [("user", "Yep.")])
    lead = senv.lead(lead_id)
    assert lead["status"] != "transferred_human" and lead["cadence_state"] == "active"
    assert _event(senv, event)["outcome"] == "no_answer"


def test_transferred_with_a_real_transfer_is_recorded(senv):
    _, lead_id, *_ = _call(senv, {"status": "transferred_human", "summary": "Transferred."},
                           SPOKE + [("user", "Can I talk to someone?")], ended="assistant-forwarded-call")
    assert senv.lead(lead_id)["status"] == "transferred_human"


def test_callback_with_no_time_is_its_own_card_with_two_choices(senv):
    number, lead_id, event, _, _, outcome = _call(
        senv, {"status": "callback_scheduled", "summary": "Call me later."},
        SPOKE + [("user", "Can you call me later?")])
    assert outcome == "manual"  # the call is counted with the card, not left for the sweeper
    assert _event(senv, event) == {"status": "delivered", "outcome": "manual"}
    lead = senv.lead(lead_id)
    assert lead["needs_review"] and lead["cadence_state"] == "paused"
    card = _get(f"review/{lead_id}").json()
    assert card["review"]["code"] == "callback_no_time"
    assert card["review"]["title"] == "Asked to be called later, no time given"
    assert "gave no time" in card["review"]["reason"]
    assert [(o["choice"], o["label"]) for o in card["options"]] == [
        ("continue", "Continue cadence"), ("front_desk", "Front desk will handle")]
    assert senv.cell(number, "outcome_status") == "Needs review: asked to be called later, no time given"
    refused = _post(f"review/{lead_id}/resolve", {"choice": "number_ok"})
    assert refused.status_code == 409
    done = _post(f"review/{lead_id}/resolve", {"choice": "continue"})
    assert done.status_code == 200 and done.json()["label"] == "Continue cadence"
    assert senv.lead(lead_id)["cadence_state"] == "active"


def test_callback_with_a_bare_california_time_is_scheduled(senv):
    _, lead_id, *_ = _call(
        senv, {"status": "callback_scheduled", "summary": "Tuesday 3 PM.", "callback_type": "absolute",
               "callback_datetime_iso": "2026-11-17T15:00:00"},
        SPOKE + [("user", "Call me Tuesday the 17th at three.")])
    lead = senv.lead(lead_id)
    assert lead["status"] == "callback_scheduled"
    local = senv.db.execute("select (callback_requested_at at time zone 'America/Los_Angeles') as t "
                            "from leads where id=%s", (lead_id,)).fetchone()["t"]
    assert (local.hour, local.minute) == (15, 0)
