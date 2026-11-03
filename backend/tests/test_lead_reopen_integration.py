"""A closed lead goes back into outreach from the board or its page, end to end (fake Sheet).

Incident 2026-11-02 (production): a patient said "not a good time", the call was labelled declined,
and staff moved the card back to In cadence four times. Each move only flipped the status: nothing
was planned, so the spent-cadence sweep closed the lead again within a minute. In cadence now
continues where the lead stopped; New still restarts from Day 0, and the Sheet hears about both.

Needs TEST_DATABASE_URL (a disposable local database with the migrations applied).
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_sheet_direct_integration import _phone, env  # noqa: F401 - the shared Sheet fixture

from rpt_agent.api import app
from rpt_agent.config import get_settings
from rpt_agent.observability import WorkflowTrace
from rpt_agent.services.lead_reopen import CONTINUE_REASON, NOTHING_LEFT
from rpt_agent.services.review import REPLACED_REASON
from rpt_agent.worker import run_safety_checks

pytestmark = pytest.mark.integration

HEADERS = {"X-Dashboard-Token": "x" * 32, "X-Dashboard-User-ID": "emma01",
           "X-Dashboard-User-Name": "Emma", "X-Dashboard-User-Role": "employee"}


@pytest.fixture
def reopen_env(env, monkeypatch):  # noqa: F811 - pytest fixture injection
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "x" * 32)
    get_settings.cache_clear()
    return env


def _move(lead_id, stage):
    return TestClient(app).post(f"/api/v1/dashboard/leads/{lead_id}/stage", json={"stage": stage},
                                headers=HEADERS)


def _detail(lead_id):
    return TestClient(app).get(f"/api/v1/dashboard/leads/{lead_id}", headers=HEADERS).json()


def _events(senv, lead_id):
    return senv.db.execute(
        "select id,channel,day_offset,status,failure_reason,scheduled_for from outreach_events "
        "where lead_id=%s order by day_offset,id", (lead_id,)).fetchall()


def _declined_after_day0(senv, phone=None, **cells):
    """Day 0 call and text went out, then the call outcome closed the lead as declined."""
    number = senv.start_row(phone=phone, **cells)
    senv.tick()
    lead_id = senv.cell(number, "lead_id")
    senv.db.execute(
        "update outreach_events set status='delivered',executed_at=now(),settled_at=now() "
        "where lead_id=%s and day_offset=0", (lead_id,))
    # What lead_status.apply_call_outcome does for "not_interested".
    senv.db.execute(
        "update leads set status='declined',cadence_state='terminated',last_call_outcome="
        "'not_interested',status_reason='The patient said it was not a convenient time',"
        "status_changed_at=now() where id=%s", (lead_id,))
    senv.db.execute(
        "update outreach_events set status='skipped',updated_at=now() "
        "where lead_id=%s and status='planned'", (lead_id,))
    return number, lead_id


def test_in_cadence_continues_a_declined_lead_where_it_stopped(reopen_env):
    senv = reopen_env
    number, lead_id = _declined_after_day0(senv)
    before = {e["day_offset"]: e["scheduled_for"] for e in _events(senv, lead_id)}
    reopen = _detail(lead_id)["lead"]["reopen"]
    assert reopen == {"can_continue": True, "continue_refusal": None, "steps_left": 2,
                      "can_restart": True}

    moved = _move(lead_id, "cadence")
    assert moved.status_code == 200, moved.text
    assert moved.json()["events_created"] == 2

    events = _events(senv, lead_id)
    assert [(e["day_offset"], e["status"]) for e in events] == [
        (0, "delivered"), (0, "delivered"), (3, "planned"), (5, "planned")]
    day3, day5 = events[2]["scheduled_for"], events[3]["scheduled_for"]
    assert abs(day3 - datetime.now(UTC)) < timedelta(minutes=1)  # the next step goes out now
    assert day5 - day3 == before[5] - before[3]  # and the rest keep their spacing
    lead = senv.lead(lead_id)
    assert (lead["status"], lead["cadence_state"], lead["status_reason"]) == (
        "in_progress", "active", CONTINUE_REASON)

    # The regression: the spent-cadence sweep closed the lead again a minute later.
    run_safety_checks(WorkflowTrace("t", "test"))
    assert senv.lead(lead_id)["cadence_state"] == "active"
    assert _detail(lead_id)["lead"]["stage"] == "cadence"

    senv.tick()
    assert senv.cell(number, "outcome_status") == "Cadence continued in dashboard"
    assert senv.cell(number, "lead_status") == "In cadence"
    assert senv.cell(number, "action") == "Start cadence"
    senv.tick()
    assert len(senv.leads()) == 1  # the Sheet row does not start anything again
    history = senv.db.execute(
        "select from_status,to_status,reason from lead_status_history where lead_id=%s "
        "order by id desc limit 1", (lead_id,)).fetchone()
    assert history == {"from_status": "declined", "to_status": "in_progress",
                       "reason": "moved to cadence from the board"}


def test_continue_brings_back_only_the_channels_still_allowed(reopen_env):
    senv = reopen_env
    _, lead_id = _declined_after_day0(senv)
    senv.db.execute("update leads set sms_disabled=true where id=%s", (lead_id,))  # calls only
    assert _move(lead_id, "cadence").json()["events_created"] == 1
    remaining = {e["day_offset"]: e["status"] for e in _events(senv, lead_id) if e["day_offset"]}
    assert remaining == {3: "planned", 5: "skipped"}

    _, other = _declined_after_day0(senv)
    senv.db.execute("update leads set call_opt_out=true,sms_opt_out=true where id=%s", (other,))
    refused = _move(other, "cadence")
    assert refused.status_code == 409 and refused.json()["detail"] == NOTHING_LEFT
    assert senv.lead(other)["status"] == "declined"


def test_a_finished_cadence_has_nothing_to_continue_but_can_restart(reopen_env):
    senv = reopen_env
    number = senv.start_row()
    senv.tick()
    lead_id = senv.cell(number, "lead_id")
    senv.db.execute("update outreach_events set status='delivered',executed_at=now(),"
                    "settled_at=now() where lead_id=%s", (lead_id,))
    run_safety_checks(WorkflowTrace("t", "test"))
    assert senv.lead(lead_id)["status"] == "closed_no_response"
    reopen = _detail(lead_id)["lead"]["reopen"]
    assert (reopen["can_continue"], reopen["continue_refusal"], reopen["can_restart"]) == (
        False, NOTHING_LEFT, True)
    refused = _move(lead_id, "cadence")
    assert refused.status_code == 409 and refused.json()["detail"] == NOTHING_LEFT

    senv.tick()
    assert _move(lead_id, "new").status_code == 200  # Restart from Day 0
    events = [e for e in _events(senv, lead_id) if e["status"] == "planned"]
    assert len(events) == 4
    senv.tick()
    assert senv.cell(number, "outcome_status") == "Cadence restarted"
    assert senv.cell(number, "action") == "Restart cadence"
    senv.tick()
    assert len([e for e in _events(senv, lead_id) if e["status"] == "planned"]) == 4  # not run twice


def test_continue_is_refused_where_outreach_must_not_come_back(reopen_env):
    senv = reopen_env
    # Do Not Contact: no Continue, no Restart.
    _, dnc = _declined_after_day0(senv)
    senv.db.execute("update leads set status='do_not_contact',call_opt_out=true,sms_opt_out=true "
                    "where id=%s", (dnc,))
    assert _detail(dnc)["lead"]["reopen"]["can_restart"] is False
    assert _move(dnc, "cadence").status_code == 409

    # Blocked number.
    _, blocked = _declined_after_day0(senv)
    phone = senv.lead(blocked)["phone_e164"]
    senv.db.execute("insert into suppressed_numbers(phone_e164,reason,source,list_type) "
                    "values(%s,'test','dashboard','internal')", (phone,))
    refused = _move(blocked, "cadence")
    assert refused.status_code == 409 and "blocked" in refused.json()["detail"]

    # Replaced by a newer row on the same number.
    _, replaced = _declined_after_day0(senv)
    senv.db.execute("update leads set status_reason=%s where id=%s", (REPLACED_REASON, replaced))
    refused = _move(replaced, "cadence")
    assert refused.status_code == 409 and "newer Sheet row" in refused.json()["detail"]

    # Another lead on the same phone is still being worked: one phone, one cadence.
    phone = _phone()
    _, old = _declined_after_day0(senv, phone=phone)
    senv.start_row(phone=phone, name="Asha Rao", case="Pelvic")
    senv.tick()
    refused = _move(old, "cadence")
    assert refused.status_code == 409 and "Another lead" in refused.json()["detail"]
    for lead_id in (dnc, blocked, replaced, old):
        assert senv.lead(lead_id)["cadence_state"] == "terminated"
