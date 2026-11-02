"""After-call outcome v2 (ported from demo 08beb3f, e66e687, 90c350e, 84f0f72, 12d9500, 2d1e00e;
2026-11-02). The post-call structured output decides a call only when the agent's tool never
reported: a cut call, a hang-up, silence.

Statuses: booking_link, callback_scheduled, transferred_human, declined, do_not_contact, wrong_person,
no_decision, already_booked; fields summary, callback_type, delay_minutes, callback_datetime_iso (bare
California wall-clock time). The old outcome (32053ff0) sends the same names minus the two new ones,
or no status at all, and must keep working.
"""

from contextlib import contextmanager
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from rpt_agent.observability import WorkflowTrace
from rpt_agent.services import delivery, lead_status


def _settle_with(monkeypatch, structured, turns=None, *, ended="customer-ended-call", extra=()):
    """Run the post-call fallback on one extractor result; return what it passed to
    report_lead_status, or {"status": "review"} when the call went to staff instead."""
    applied = {}

    class Conn:
        def execute(self, sql, params=None):
            if "needs_review=true" in sql or "outcome='manual'" in sql:
                applied.setdefault("status", "review")
            return self

        def fetchone(self):
            return {"outcome": applied.get("status"), "id": 1}

        def fetchall(self):
            return []

    @contextmanager
    def fake_transaction():
        yield Conn()

    def fake_report(trace, **kwargs):
        applied.update(kwargs)

    monkeypatch.setattr(delivery, "transaction", fake_transaction)
    monkeypatch.setattr(lead_status, "report_lead_status", fake_report)
    message = {"endedReason": ended, "artifact": {
        "structuredOutputs": {"x": {"result": structured}},
        "messages": [{"role": r, "message": m} for r, m in (turns or [])] + list(extra),
    }}
    delivery._settle_from_structured_output(
        WorkflowTrace("t", "test"), message, lead_id="lead-1", event_id=1, call_id="c"
    )
    return applied


def _flag_for_rejected_outcome(monkeypatch, status, error):
    """The review a rejected post-call outcome leaves (report_lead_status raised `error`)."""
    flagged = {"sql": []}

    class FakeConn:
        def execute(self, sql, params=()):
            flagged["sql"].append((sql, params))
            row = {"outcome": "manual"} if "update outreach_events" in sql else None
            return type("Cursor", (), {"fetchone": lambda self: row})()

    @contextmanager
    def fake_transaction():
        yield FakeConn()

    def fake_report(trace, **kwargs):
        raise error

    def fake_flag(conn, lead_id, reason, **kwargs):
        flagged.update(reason=reason, **kwargs)

    monkeypatch.setattr(delivery, "transaction", fake_transaction)
    monkeypatch.setattr(delivery, "flag_lead_for_review", fake_flag)
    monkeypatch.setattr(lead_status, "report_lead_status", fake_report)
    message = {"artifact": {"structuredOutputs": {"x": {"result": {"status": status}}},
                            "messages": []}}
    # The call is settled with the card (lead locked first), not left for the sweeper to add a
    # second "Call result never arrived" card.
    assert delivery._settle_from_structured_output(
        WorkflowTrace("t", "test"), message, lead_id="lead-1", event_id=1, call_id="c") == "manual"
    lock, settle = flagged.pop("sql")
    assert "from leads" in lock[0] and "for update" in lock[0]
    assert "outcome='manual'" in settle[0] and "status in ('in_flight','attempted')" in settle[0]
    assert settle[1] == (flagged["reason"], 1, "lead-1")
    return flagged


SPOKE = [("user", "Hello?"), ("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "Yes."),
         ("bot", "Great. This is Elliot calling from Rausch Physical Therapy. Do you have a moment?")]


# --- 1. statuses --------------------------------------------------------------------------------


def test_no_decision_is_a_missed_contact_with_the_summary_kept(monkeypatch):
    applied = _settle_with(monkeypatch, {"status": "no_decision", "summary": "Line went quiet."},
                           [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "Hello?")])
    assert (applied["status"], applied["notes"]) == ("no_answer", "Line went quiet.")


@pytest.mark.parametrize("result", [{"summary": "Hung up."}, {"status": "", "summary": "x"},
                                    {"status": None, "summary": "x"}])
def test_missing_status_is_still_a_missed_contact(monkeypatch, result):
    assert _settle_with(monkeypatch, result, SPOKE)["status"] == "no_answer"


def test_status_case_and_spaces_do_not_matter(monkeypatch):
    assert _settle_with(monkeypatch, {"status": " No_Decision "}, SPOKE)["status"] == "no_answer"


def test_already_booked_closes_only_when_the_patient_spoke(monkeypatch):
    said = SPOKE + [("user", "Oh, I already booked with you guys last week.")]
    applied = _settle_with(monkeypatch, {"status": "already_booked", "summary": "Already booked."}, said)
    assert (applied["status"], applied["notes"]) == ("already_booked", "Already booked.")
    silent = [("bot", "Hi, am I speaking with Rpt Tester?")]
    assert _settle_with(monkeypatch, {"status": "already_booked"}, silent)["status"] == "no_answer"


@pytest.mark.parametrize("status", ["booking_link", "callback_scheduled", "declined", "do_not_contact"])
def test_old_and_new_outcome_statuses_still_pass_through(monkeypatch, status):
    turns = SPOKE + [("user", "No thanks, stop calling me.")]
    assert _settle_with(monkeypatch, {"status": status}, turns)["status"] == status


def test_callback_fields_are_passed_on(monkeypatch):
    result = {"status": "callback_scheduled", "summary": "Call back Tuesday at 3.",
              "callback_type": "absolute", "delay_minutes": None,
              "callback_datetime_iso": "2026-11-03T15:00:00"}
    applied = _settle_with(monkeypatch, result, SPOKE + [("user", "Call me Tuesday at three.")])
    assert applied["callback_type"] == "absolute"
    assert applied["callback_datetime_iso"] == "2026-11-03T15:00:00"
    assert applied["source"] == "call summary"


def test_bare_callback_time_is_california_wall_clock():
    """callback_datetime_iso has no offset: it is the clinic's (California) wall-clock time."""
    tz = ZoneInfo("America/Los_Angeles")
    when = lead_status.resolve_callback_time(
        tz, callback_requested_at=None, callback_type="absolute", delay_minutes=None,
        callback_datetime_iso="2026-11-03T15:00:00", now=datetime(2026, 11, 2, tzinfo=UTC))
    assert when == datetime(2026, 11, 3, 23, 0, tzinfo=UTC)  # 3 PM PST = 23:00 UTC


def test_callback_without_a_time_is_its_own_plain_card(monkeypatch):
    """Owner, 2026-10-28: "call me later" with no time goes to Needs Review, in plain words."""
    for status in ("callback_scheduled", "callback"):
        flagged = _flag_for_rejected_outcome(
            monkeypatch, status, ValueError(lead_status.CALLBACK_WITHOUT_TIME))
        assert flagged["code"] == "callback_no_time" and flagged["source"] == "call"
        assert flagged["reason"] == "Patient asked to be called later, no time given"


def test_other_rejected_outcomes_keep_the_not_applied_card(monkeypatch):
    flagged = _flag_for_rejected_outcome(
        monkeypatch, "booked", ValueError("booked requires a confirmed appointment"))
    assert flagged["code"] == "call_outcome_not_applied"
    assert flagged["reason"] == "structured outcome could not be applied: booked requires a confirmed appointment"


def test_callback_with_no_time_raises_the_matched_message():
    with pytest.raises(ValueError, match=lead_status.CALLBACK_WITHOUT_TIME):
        lead_status.resolve_callback_time(
            ZoneInfo("America/Los_Angeles"), callback_requested_at=None, callback_type=None,
            delay_minutes=None, callback_datetime_iso=None)


# --- 2. wrong person only if the person said so ------------------------------------------------


CALL_648 = [  # demo 2026-10-28: "Yes." then "No." over the greeting, then a hang-up
    ("bot", "Hi, am I speaking with Rpt Tester?"),
    ("user", "Yes."),
    ("bot", "Great. This is Elliot calling from Rausch Physical Therapy and Wellness."),
    ("user", "No."),
]
CALL_650 = [("user", "Hello?"), ("bot", "Hi, am I speaking with Rpt Tester?")]  # then a hang-up
PROD_HI_SILENCE = [("user", "Hi."), ("bot", "Hi, am I speaking with Rpt Tester?")]  # production 28 Oct


@pytest.mark.parametrize("turns", [CALL_648, CALL_650, PROD_HI_SILENCE,
                                   [("user", "Yes."), ("user", "No.")] + CALL_650[1:]],
                         ids=["648", "650", "hi-then-silence", "yes-before-the-question"])
def test_wrong_person_needs_the_person_to_say_so(monkeypatch, turns):
    applied = _settle_with(monkeypatch, {"status": "wrong_person", "summary": "Wrong person."}, turns)
    assert applied["status"] == "no_answer"
    assert applied["notes"].startswith("No answer from the patient; outreach continues.")


@pytest.mark.parametrize("reply", [
    "No, you have the wrong number.", "No.", "Wrong number.", "There's no one here by that name.",
    "No, this is not Rpt.", "Nope, sorry. Bye.", "I don't know who that is.",
    "No, this is Maria.", "There's no Rpt here.", "You must have the wrong one.",
    "Nope, not Rpt. This is Mike.", "I think you have the wrong number. I'm busy.",
    "Wrong number, sorry, I'm at work.",
    "No, I'm not Rpt.", "I just got this number, I don't know a Rpt.",
    "Sorry, I just got this number last month.", "Rpt? No, no Rpt here.",
])
def test_wrong_person_said_by_the_person_is_applied(monkeypatch, reply):
    turns = [("user", "Hello?"), ("bot", "Hi, am I speaking with Rpt Tester?"), ("user", reply)]
    assert _settle_with(monkeypatch, {"status": "wrong_person"}, turns)["status"] == "wrong_person"
    # "manual" is the old name for the same status.
    assert _settle_with(monkeypatch, {"status": "manual"}, turns)["status"] == "manual"


@pytest.mark.parametrize("turns", [
    # A family member is not a wrong number: the cadence goes on (owner, 2026-10-28).
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "No, she's not home right now.")],
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "No, this is her mom.")],
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "No, she's at work right now.")],
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "That's my husband, can I take a message?")],
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "No, I'm busy, call back later.")],
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "No, this is fine, who is calling?")],
    # A clear yes to the name: the patient, whatever comes after.
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "Speaking."),
     ("bot", "This is Elliot calling from Rausch."), ("user", "Wrong number.")],
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "Yes, this is Rpt."),
     ("bot", "This is Elliot calling from Rausch."), ("user", "No, this is Maria's phone.")],
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "That's me.")],
    # Asked back, never an answer: "Yes?" picking up is a greeting.
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "Who am I speaking with?")],
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "Yes?")],
    # A bare "no" after a bare "yes" is talking over the greeting (648).
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "Yeah."), ("user", "No.")],
    # "Not interested" is not about who they are.
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "No, I'm not interested.")],
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "Speaking."),
     ("bot", "This is Elliot from Rausch. Is now a good time?"), ("user", "No.")],
    # No identity question on the call at all.
    [("bot", "Hello, this is Elliot from Rausch."), ("user", "No.")],
])
def test_wrong_person_is_not_a_family_member_or_the_patient(monkeypatch, turns):
    assert _settle_with(monkeypatch, {"status": "wrong_person"}, turns)["status"] == "no_answer"


@pytest.mark.parametrize("turns", [
    # "Yes?" picking up the phone, then a clear wrong number.
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "Yes?"), ("user", "No, wrong number.")],
    [("user", "Yes?"), ("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "No, wrong number.")],
    # A greeting before the question is ignored, then a plain "No." is the answer.
    [("user", "Yes."), ("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "No.")],
    # The call contradicts itself: a bare yes, then a clear wrong number -> paused with a Wrong
    # number card, staff decide (owner, 2026-10-29).
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "Yeah."),
     ("bot", "This is Elliot calling from Rausch."), ("user", "Wait, wrong number.")],
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "Yeah? Who's this?"),
     ("bot", "This is Elliot calling from Rausch."), ("user", "There's no Rpt here.")],
    # A plain No after the agent asks the name again.
    [("bot", "Hi, am I speaking with Rpt Tester?"), ("user", "Who is this?"),
     ("bot", "This is Elliot from Rausch. Sorry, is this Rpt?"), ("user", "No.")],
])
def test_clear_wrong_person_beats_a_bare_or_asked_back_yes(monkeypatch, turns):
    assert _settle_with(monkeypatch, {"status": "wrong_person"}, turns)["status"] == "wrong_person"


def test_production_greeting_with_quotes_still_finds_the_name(monkeypatch):
    """The production agent's first message is sent with quotes around it."""
    turns = [("user", "Hello?"), ("bot", '"Hi, am I speaking with Rpt Tester?"'), ("user", "No, I'm not Rpt.")]
    assert _settle_with(monkeypatch, {"status": "wrong_person"}, turns)["status"] == "wrong_person"


def test_unknown_status_is_passed_on_for_review(monkeypatch):
    """report_lead_status flags an unknown status for review (`unrecognized_status`); no crash."""
    applied = _settle_with(monkeypatch, {"status": "Something New", "summary": "?"}, SPOKE)
    assert applied["status"] == "something new"


# --- 5. "transferred" only when a transfer really happened --------------------------------------


DEMO_01A17CE0 = SPOKE + [("user", "Yep. Yes. Yes."), ("bot", "So this is for your leg visit at our")]
TRANSFER_SUMMARY = {"status": "transferred_human",
                    "summary": "The patient was transferred to a team member."}


def _tool_call(name, arguments="{}", kind="function"):
    return {"role": "tool_calls", "message": "", "toolCalls": [
        {"id": "call_1", "type": kind, "function": {"name": name, "arguments": arguments}}]}


def test_transferred_summary_needs_a_real_transfer(monkeypatch):
    """Demo call 01a17ce0 (2026-10-27): no transfer happened, the summary said transferred."""
    applied = _settle_with(monkeypatch, TRANSFER_SUMMARY, DEMO_01A17CE0)
    assert applied["status"] == "no_answer"
    assert applied["notes"].startswith("No answer from the patient; outreach continues.")
    assert _settle_with(monkeypatch, {"status": "transferred"}, DEMO_01A17CE0)["status"] == "no_answer"
    for extra, ended in (([_tool_call("transfer_tool_outreach")], "customer-ended-call"),
                         ([_tool_call("transferCall", kind="transferCall")], "customer-ended-call"),
                         ([], "assistant-forwarded-call"),
                         ([], "customer-ended-call-during-transfer")):
        assert _settle_with(monkeypatch, TRANSFER_SUMMARY, DEMO_01A17CE0, ended=ended,
                            extra=extra)["status"] == "transferred_human"


def test_link_and_transfer_without_a_transfer_keeps_only_a_requested_link(monkeypatch):
    both = {"status": "booking_link_and_transfer", "summary": "Link sent and transferred."}
    assert _settle_with(monkeypatch, both, DEMO_01A17CE0)["status"] == "no_answer"
    link = _tool_call("update_lead_status", '{"status": "booking_link_and_transfer"}')
    assert _settle_with(monkeypatch, both, DEMO_01A17CE0, extra=[link])["status"] == "booking_link"
    assert _settle_with(monkeypatch, both, DEMO_01A17CE0, ended="assistant-forwarded-call",
                        extra=[link])["status"] == "booking_link_and_transfer"


# --- 3. structured output stored on the call log -----------------------------------------------


def test_structured_outputs_are_kept_as_sent():
    outputs = {"so-1": {"name": "Cadence Call Outcome", "result": {"status": "no_decision"}}}
    assert delivery._structured_outputs({"artifact": {"structuredOutputs": outputs}}) == outputs
    assert delivery._structured_outputs({"artifact": {"structuredOutputs": {}}}) is None
    assert delivery._structured_outputs({"artifact": {}}) is None
    assert delivery._structured_outputs({}) is None


def test_call_log_insert_writes_the_structured_output():
    import inspect

    source = inspect.getsource(delivery.process_vapi_end_report)
    assert "structured_output)" in source
    assert "structured_output=coalesce(excluded.structured_output,call_logs.structured_output)" in source
