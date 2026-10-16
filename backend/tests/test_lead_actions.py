import inspect
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest

from rpt_agent.config import Settings
from rpt_agent.services import lead_actions
from rpt_agent.services.sheet_sync import (
    _action_label,
    build_sheet_snapshot,
    dashboard_call_link,
    enqueue_sheet_update,
    format_cadence_columns,
    format_cadence_result,
    format_callback_time,
)


def test_sheet_name_parser_accepts_one_word_name():
    assert lead_actions._name_parts("Synthetic") == ("Synthetic", None)


def test_existing_sheet_lead_profile_updates_when_name_changes():
    calls = []

    class Connection:
        def execute(self, query, params=None):
            calls.append((" ".join(query.split()), params))

    lead_actions._update_lead_profile(
        Connection(),
        "00000000-0000-0000-0000-000000000002",
        {
            "full_name": "Updated Name",
            "email": "UPDATED@EXAMPLE.TEST",
            "location": "New Location",
            "title": "New Lead Type",
        },
    )

    query, params = calls[0]
    assert query.startswith("update leads set full_name=")
    assert params[0:4] == ("Updated Name", "Updated", "Updated Name", "Name")
    assert params[4] == "updated@example.test"
    assert params[6:8] == ("New Location", "New Lead Type")


def test_sheet_sync_same_identity_updates_existing_lead(monkeypatch):
    updates = []

    class Connection:
        def execute(self, query, params=None):
            normalized = " ".join(query.split())
            if normalized.startswith("select id from practices"):
                return _Rows({"id": 7})
            if normalized.startswith("select id,full_name,phone_e164 from leads"):
                return _Rows({
                    "id": params[0],
                    "full_name": "Original Name",
                    "phone_e164": "+15555550100",
                })
            updates.append((normalized, params))
            return _Rows(None)

    class _Rows:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    @contextmanager
    def fake_transaction():
        yield Connection()

    monkeypatch.setattr(lead_actions, "transaction", fake_transaction)
    result = lead_actions.sync_sheet_lead(
        request_id=UUID("00000000-0000-0000-0000-000000000001"),
        lead_id=UUID("00000000-0000-0000-0000-000000000002"),
        lead={
            "full_name": "Original Name",
            "phone": "+15555550100",
            "email": "changed@example.test",
        },
    )
    assert result.status_code == 200
    assert result.body["result"] == "profile_updated"
    assert updates[0][0].startswith("update leads set full_name=")


def test_sheet_sync_changed_name_requires_review(monkeypatch):
    queries = []

    class _Rows:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

        def fetchall(self):
            return []

    class Connection:
        def execute(self, query, params=None):
            normalized = " ".join(query.split())
            queries.append(normalized)
            if normalized.startswith("select id from practices"):
                return _Rows({"id": 7})
            if normalized.startswith("select id,full_name,phone_e164 from leads"):
                return _Rows({
                    "id": params[0],
                    "full_name": "Original Name",
                    "phone_e164": "+15555550100",
                })
            return _Rows(None)

    @contextmanager
    def fake_transaction():
        yield Connection()

    monkeypatch.setattr(lead_actions, "transaction", fake_transaction)
    result = lead_actions.sync_sheet_lead(
        request_id=UUID("00000000-0000-0000-0000-000000000001"),
        lead_id=UUID("00000000-0000-0000-0000-000000000002"),
        lead={"full_name": "Changed Name", "phone": "+15555550100"},
    )
    assert result.status_code == 409
    assert result.body["result"] == "name_changed_needs_review"
    assert any("update leads set needs_review=true" in query for query in queries)
    assert not any("update leads set full_name=" in query for query in queries)


@pytest.mark.parametrize(
    ("incoming_name", "expected_result"),
    [
        ("Changed Name", "phone_changed_needs_review"),
        ("Another Name", "name_and_phone_changed_needs_review"),
    ],
)
def test_sheet_sync_changed_phone_requires_review(
    monkeypatch, incoming_name, expected_result
):
    queries = []

    class _Rows:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

        def fetchall(self):
            return []

    class Connection:
        def execute(self, query, params=None):
            normalized = " ".join(query.split())
            queries.append(normalized)
            if normalized.startswith("select id from practices"):
                return _Rows({"id": 7})
            if normalized.startswith("select id,full_name,phone_e164 from leads"):
                return _Rows({
                    "id": params[0],
                    "full_name": "Changed Name",
                    "phone_e164": "+15555550100",
                })
            return _Rows(None)

    @contextmanager
    def fake_transaction():
        yield Connection()

    monkeypatch.setattr(lead_actions, "transaction", fake_transaction)
    old_id = UUID("00000000-0000-0000-0000-000000000002")
    result = lead_actions.sync_sheet_lead(
        request_id=UUID("00000000-0000-0000-0000-000000000001"),
        lead_id=old_id,
        lead={
            "full_name": incoming_name,
            "phone": "+15555550101",
            "date_of_birth": date(1990, 3, 15),
            "location": "Dana Point",
            "title": "Sports Rehab",
        },
    )
    assert result.status_code == 409
    assert result.body["result"] == expected_result
    assert result.body["lead_id"] == str(old_id)
    assert any("update leads set needs_review=true" in query for query in queries)
    assert any("update outreach_events set status='skipped'" in query for query in queries)
    assert not any("update leads set full_name=" in query for query in queries)


def test_sheet_result_combines_call_and_sms():
    lead = {"status": "in_progress", "cadence_state": "active"}
    event_label, outcome = format_cadence_result(
        [
            {"channel": "call", "status": "delivered", "outcome": "no_answer"},
            {"channel": "sms", "status": "delivered", "delivery_status": "delivered"},
        ],
        lead,
    )
    assert event_label == "Call + SMS"
    assert outcome == "Call: No answer, SMS: Delivered"


def test_sheet_result_has_separate_outcome_columns():
    cadence, call, message, email = format_cadence_columns(
        [
            {"channel": "call", "status": "delivered", "outcome": "transferred"},
            {"channel": "sms", "status": "failed", "delivery_status": "undelivered"},
        ],
        {"status": "transferred_human", "cadence_state": "paused"},
    )
    assert (cadence, call, message, email) == (
        "Call + SMS",
        "Call transferred",
        "Not delivered",
        None,
    )


def test_sheet_result_marks_missing_sms_callback_for_review():
    event_label, outcome = format_cadence_result(
        [{"channel": "sms", "status": "unknown", "delivery_status": "queued"}],
        {"status": "in_progress", "cadence_state": "active"},
    )
    assert event_label == "SMS"
    assert outcome == "Needs staff review"


def test_sheet_action_status_only_for_system_outcomes():
    assert _action_label({"status": "in_progress", "cadence_state": "active"}) is None
    assert _action_label({"status": "do_not_contact", "cadence_state": "terminated"}) == (
        "Do Not Contact applied"
    )
    assert _action_label({"status": "closed_no_response", "cadence_state": "completed"}) == (
        "Cadence completed"
    )
    assert _action_label({"status": "booked", "cadence_state": "completed"}) == "Booked"


class _Rows:
    def __init__(self, *, one=None, many=None):
        self.one = one
        self.many = many or []

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


class _SnapshotConnection:
    def execute(self, query, params=None):
        del params
        if query.startswith("select l.id,l.status"):
            return _Rows(one={
                "id": UUID("00000000-0000-0000-0000-000000000002"),
                "status": "callback_scheduled",
                "cadence_state": "active",
                "needs_review": True,
                "callback_requested_at": datetime(2026, 9, 20, 18, 0, tzinfo=UTC),
                "timezone": "America/Los_Angeles",
            })
        if query.startswith("select request_id from lead_action_requests"):
            return _Rows(one={
                "request_id": UUID("00000000-0000-0000-0000-000000000003"),
            })
        if "from lead_action_requests where lead_id" in query:
            return _Rows(one={
                "request_id": UUID("00000000-0000-0000-0000-000000000001"),
                "created_at": datetime(2026, 9, 18, tzinfo=UTC),
                "result": "cadence_started",
            })
        if "select oe.day_offset" in query:
            return _Rows(one={"day_offset": 0, "finished_at": datetime.now(UTC)})
        if "select oe.id,oe.channel" in query:
            return _Rows(many=[
                {
                    "id": 1,
                    "channel": "call",
                    "status": "delivered",
                    "outcome": "callback",
                    "delivery_status": None,
                }
            ])
        if "select ct.transcript_link" in query:
            return _Rows(one={"transcript_link": "https://dashboard.example.test/transcript"})
        raise AssertionError(query)


class _CallbackSnapshotConnection(_SnapshotConnection):
    """The call a patient asked for carries no day number."""

    def execute(self, query, params=None):
        if "select oe.day_offset" in query:
            return _Rows(one={"day_offset": None, "finished_at": datetime.now(UTC)})
        if "select oe.id,oe.channel" in query:
            assert "is not distinct from" in query, query
            return _Rows(many=[{
                "id": 9,
                "channel": "call",
                "status": "delivered",
                "outcome": "not_interested",
                "delivery_status": None,
            }])
        return super().execute(query, params)


def test_callback_call_reaches_the_sheet():
    """A standalone callback has no day_offset, which the Sheet query used to
    filter out - so the row stopped updating at the last numbered day even
    though a later call had happened."""
    snapshot = build_sheet_snapshot(
        _CallbackSnapshotConnection(),
        "00000000-0000-0000-0000-000000000002",
    )
    assert snapshot["sheet"]["cadence_day"] == "Callback"
    assert snapshot["sheet"]["call_outcome"] == "Answered - declined"


class _BookedSnapshotConnection(_SnapshotConnection):
    def execute(self, query, params=None):
        rows = super().execute(query, params)
        if query.startswith("select l.id,l.status"):
            rows.one = {**rows.one, "status": "booked", "cadence_state": "completed"}
        return rows


def test_booked_lead_sets_the_action_cell_too():
    """The Action cell kept the last command ("Restart cadence") next to a
    Booked status, which reads as an instruction still waiting to run."""
    booked = build_sheet_snapshot(_BookedSnapshotConnection(), "00000000-0000-0000-0000-000000000002")
    assert booked["sheet"]["action"] == "Booked"
    assert booked["sheet"]["action_status"] == "Booked"
    active = build_sheet_snapshot(_SnapshotConnection(), "00000000-0000-0000-0000-000000000002")
    assert "action" not in active["sheet"]


def test_sheet_snapshot_uses_lead_id_and_current_database_truth():
    snapshot = build_sheet_snapshot(
        _SnapshotConnection(),
        "00000000-0000-0000-0000-000000000002",
        practice_slug="rausch-pt",
    )
    assert snapshot["lead_id"] == "00000000-0000-0000-0000-000000000002"
    # Row matching follows the newest completed Sheet command, while cadence
    # history still uses the cadence-start request as its time anchor.
    assert snapshot["action_request_id"] == "00000000-0000-0000-0000-000000000003"
    # Intake owns Action Status / Lead ID; outreach snapshots omit action_status.
    assert "action_status" not in snapshot["sheet"]
    assert snapshot["sheet"]["cadence_day"] == "Day 0"
    assert snapshot["sheet"]["cadence"] == "Call"
    assert snapshot["sheet"]["cadence_status"] == "Callback requested"
    assert snapshot["sheet"]["call_outcome"] == "Callback requested"
    assert snapshot["sheet"]["message_outcome"] is None
    assert snapshot["sheet"]["email_outcome"] is None
    assert snapshot["sheet"]["needs_review"] == "Needs Review"
    assert snapshot["sheet"]["callback_at"] == "Sep 20, 2026 at 11:00 AM PT"


def test_sheet_snapshot_has_dashboard_link_before_a_transcript_exists(monkeypatch):
    class Connection(_SnapshotConnection):
        def execute(self, query, params=None):
            if "select ct.transcript_link" in query:
                return _Rows(one=None)
            return super().execute(query, params)

    monkeypatch.setattr(
        "rpt_agent.services.sheet_sync.dashboard_call_link",
        lambda lead_id: f"https://rpt-frontend-pi.vercel.app/leads/{lead_id}/conversations/calls",
    )
    snapshot = build_sheet_snapshot(
        Connection(),
        "00000000-0000-0000-0000-000000000002",
        practice_slug="rausch-pt",
    )
    assert snapshot["sheet"]["transcript_link"].endswith(
        "/leads/00000000-0000-0000-0000-000000000002/conversations/calls"
    )


def test_dashboard_call_link_uses_configured_frontend_base():
    settings = Settings(dashboard_public_url="https://rpt-frontend-pi.vercel.app/")
    assert dashboard_call_link("lead-1", settings) == (
        "https://rpt-frontend-pi.vercel.app/leads/lead-1/conversations/calls"
    )


def test_dashboard_call_link_removes_login_suffix():
    settings = Settings(dashboard_public_url="https://rpt-frontend-pi.vercel.app/login/")
    assert dashboard_call_link("lead-1", settings) == (
        "https://rpt-frontend-pi.vercel.app/leads/lead-1/conversations/calls"
    )


def test_callback_time_is_readable_and_uses_pacific_time():
    value = datetime(2026, 9, 21, 16, 0, tzinfo=UTC)
    assert format_callback_time(value, "America/Los_Angeles") == (
        "Sep 21, 2026 at 9:00 AM PT"
    )


class _DuplicateRequestConnection:
    def __init__(self, request_hash, response):
        self.request_hash = request_hash
        self.response = response

    def execute(self, query, params=None):
        if "select id,timezone from practices" in query:
            return _Rows(one={"id": 1, "timezone": "America/Los_Angeles"})
        if "insert into lead_action_requests" in query:
            return _Rows(one=None)
        if "from lead_action_requests where request_id" in query:
            return _Rows(one={
                "practice_id": "1",
                "action": "start_cadence",
                "request_hash": self.request_hash,
                "status": "completed",
                "response_body": {"http_status": 201, "body": self.response},
            })
        raise AssertionError((query, params))


def test_action_retry_returns_the_saved_response(monkeypatch):
    request_id = UUID("00000000-0000-0000-0000-000000000001")
    lead = {
        "full_name": "Synthetic Patient",
        "phone": "+15555550100",
        "email": None,
        "date_of_birth": "1990-01-01",
        "location": "Dana Point",
        "lead_type": "Physical Therapy",
    }
    request_hash = lead_actions._request_hash("start_cadence", None, lead)
    saved = {
        "request_id": str(request_id),
        "lead_id": "00000000-0000-0000-0000-000000000002",
        "action": "start_cadence",
        "result": "cadence_started",
        "created": True,
        "cadence_event_count": 8,
    }
    connection = _DuplicateRequestConnection(request_hash, saved)

    @contextmanager
    def fake_transaction():
        yield connection

    monkeypatch.setattr(lead_actions, "transaction", fake_transaction)
    result = lead_actions.execute_lead_action(
        request_id=request_id,
        action="start_cadence",
        lead_id=None,
        lead=lead,
    )
    assert result.status_code == 201
    assert result.body == saved


class _Result:
    def fetchone(self):
        return None


class _OutboxConnection:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((" ".join(query.split()), params))
        return _Result()


def test_sheet_outbox_event_is_minimal_and_idempotent():
    conn = _OutboxConnection()
    enqueue_sheet_update(
        conn,
        lead_id="00000000-0000-0000-0000-000000000002",
        event_type="call_settled",
        source_key="call-1:no_answer",
        outreach_event_id=12,
    )
    query, params = conn.calls[0]
    assert "destination" in query and params[4] == "n8n"  # SHEET_DESTINATION, the stored label
    assert "source_system='google_sheets'" in query
    assert "on conflict(event_id) do nothing" in query
    assert params[2] == "00000000-0000-0000-0000-000000000002"
    assert set(params[3].obj) == {"lead_id", "reason", "outreach_event_id"}


def test_repeat_patient_on_same_number_takes_over_and_warns(monkeypatch):
    """Repeat patients are referred again for another body region with the same
    number. The new lead starts; the older lead still in outreach stops, so the
    patient is never worked twice; staff get a warning naming the older lead."""
    older = {"id": UUID("00000000-0000-0000-0000-000000000009"), "full_name": "Emma Katko",
             "lead_type": "Knee", "status": "in_progress", "cadence_state": "active",
             "call_opt_out": False, "sms_opt_out": True}

    class Connection:
        def __init__(self):
            self.queries = []

        def execute(self, query, params=None):
            normalized = " ".join(query.split())
            self.queries.append(normalized)
            if normalized.startswith("insert into leads"):
                return _Rows(one={"id": UUID("00000000-0000-0000-0000-000000000002")})
            if "phone_e164=%s and id<>%s" in normalized:
                return _Rows(many=[older])
            return _Rows()

    conn = Connection()
    monkeypatch.setattr(lead_actions, "materialize_cadence", lambda *args: 8)
    result = lead_actions._start_cadence(
        conn,
        request_id=UUID("00000000-0000-0000-0000-000000000001"),
        practice={"id": 1, "timezone": "America/Los_Angeles"},
        lead_data={"phone": "+15555550100", "full_name": "Emma Katko", "email": None,
                   "date_of_birth": None, "location": "Dana Point", "lead_type": "Lower back"},
    )

    assert result.status_code == 201
    assert result.body["warning"] == "This number is also on file as Emma Katko (Knee)."
    assert any("cadence_state='terminated'" in q for q in conn.queries), conn.queries
    assert any(q.startswith("update outreach_events set status='skipped'") for q in conn.queries)
    # She opted out of texts on the knee referral; that follows her number.
    assert any("sms_opt_out=sms_opt_out or" in q for q in conn.queries)
    # A replaced lead has nothing left to act on, so it must leave Needs Attention.
    assert any("needs_review=false" in q and "cadence_state='terminated'" in q for q in conn.queries)


def test_same_number_warning_mentions_an_earlier_wrong_number():
    from datetime import datetime as dt

    from rpt_agent.services.review import hand_over_number

    wrong = {"id": UUID("00000000-0000-0000-0000-000000000009"), "full_name": "Cris Test",
             "lead_type": None, "status": "invalid_phone", "cadence_state": "paused",
             "call_opt_out": False, "sms_opt_out": False,
             "status_changed_at": dt(2026, 9, 25, 15, 0, tzinfo=UTC)}

    class Connection:
        def execute(self, query, params=None):
            return _Rows(many=[wrong]) if "id<>%s" in query else _Rows()

    warning = hand_over_number(Connection(), practice_id=1, phone="+15555550100", lead_id="new")
    assert warning == (
        "This number is also on file as Cris Test. "
        "It was marked as a wrong number on Cris Test on Sep 25."
    )


def test_sheet_team_can_mark_booked_without_an_appointment():
    lead_id = UUID("00000000-0000-0000-0000-000000000002")

    class Connection:
        def __init__(self):
            self.queries = []

        def execute(self, query, params=None):
            normalized = " ".join(query.split())
            self.queries.append((normalized, params))
            if normalized.startswith("select id,practice_id,status"):
                return _Rows(one={
                    "id": lead_id,
                    "practice_id": 1,
                    "status": "in_progress",
                    "cadence_state": "active",
                    "call_opt_out": False,
                    "sms_opt_out": False,
                    "phone_e164": "+15555550100",
                })
            return _Rows()

    conn = Connection()
    result = lead_actions._mark_booked(
        conn,
        request_id=UUID("00000000-0000-0000-0000-000000000001"),
        practice={"id": 1},
        lead_id=lead_id,
        phone="+15555550100",
    )

    assert result.body["result"] == "booked_applied"
    statements = [query for query, _ in conn.queries]
    assert any("status='booked',cadence_state='completed'" in query for query in statements)
    assert any("status='skipped'" in query for query in statements)
    assert not any("from appointments" in query for query in statements)


class _RestartConnection:
    def __init__(self, cadence_state: str):
        self.cadence_state = cadence_state
        self.queries: list[tuple[str, object]] = []

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.queries.append((normalized, params))
        if normalized.startswith("select id,practice_id,status,cadence_state"):
            return _Rows(one={
                "id": UUID("00000000-0000-0000-0000-000000000002"),
                "practice_id": 1,
                "status": "needs_attention" if self.cadence_state == "paused" else "closed_no_response",
                "cadence_state": self.cadence_state,
                "call_opt_out": False,
                "sms_opt_out": False,
                "phone_e164": "+15555550100",
            })
        if normalized.startswith("select exists"):
            return _Rows(one={"unresolved": False})
        return _Rows()


@pytest.mark.parametrize("previous_state", ["paused", "completed"])
def test_restart_always_starts_again_from_day_zero(monkeypatch, previous_state):
    conn = _RestartConnection(previous_state)
    materialized = []
    monkeypatch.setattr(
        lead_actions,
        "materialize_cadence",
        lambda *args, **kwargs: materialized.append((args, kwargs)) or 8,
    )

    result = lead_actions._restart_cadence(
        conn,
        request_id=UUID("00000000-0000-0000-0000-000000000001"),
        practice={"id": 1},
        lead_id=UUID("00000000-0000-0000-0000-000000000002"),
        phone="+15555550100",
    )

    statements = [query for query, _ in conn.queries]
    assert result.body["result"] == "cadence_restarted"
    assert result.body["cadence_event_count"] == 8
    assert materialized
    assert any(query.startswith("delete from outreach_events") for query in statements)


def test_booked_lead_can_be_restarted_and_says_so(monkeypatch):
    """A mis-clicked Booked needs an undo; Booked again undoes a mis-clicked
    restart. The response flags it so the Sheet can show "(was Booked)"."""
    conn = _RestartConnection("completed")
    original_execute = conn.execute

    def execute(query, params=None):
        result = original_execute(query, params)
        if "select id,practice_id,status,cadence_state" in " ".join(query.split()):
            result.one["status"] = "booked"
        return result

    conn.execute = execute
    monkeypatch.setattr(lead_actions, "materialize_cadence", lambda *args, **kwargs: 8)
    result = lead_actions._restart_cadence(
        conn,
        request_id=UUID("00000000-0000-0000-0000-000000000001"),
        practice={"id": 1},
        lead_id=UUID("00000000-0000-0000-0000-000000000002"),
        phone="+15555550100",
    )
    assert result.body["result"] == "cadence_restarted"
    assert result.body["was_booked"] is True


@pytest.mark.parametrize("status", ["do_not_contact", "invalid_phone"])
def test_restart_refuses_terminal_or_unsafe_leads(status):
    conn = _RestartConnection("paused")
    original_execute = conn.execute

    def execute(query, params=None):
        result = original_execute(query, params)
        if "select id,practice_id,status,cadence_state" in " ".join(query.split()):
            result.one["status"] = status
        return result

    conn.execute = execute
    with pytest.raises(lead_actions.LeadActionError) as exc_info:
        lead_actions._restart_cadence(
            conn,
            request_id=UUID("00000000-0000-0000-0000-000000000001"),
            practice={"id": 1},
            lead_id=UUID("00000000-0000-0000-0000-000000000002"),
            phone="+15555550100",
        )

    assert exc_info.value.code == "restart_not_allowed"
    # Name the real reason, not both (user request 2026-10-16).
    expected = {"do_not_contact": "A Do Not Contact lead cannot be restarted",
                "invalid_phone": "An invalid phone lead cannot be restarted"}[status]
    assert exc_info.value.detail == expected


def test_restart_rejects_a_repeat_sheet_restart_within_cooldown(monkeypatch):
    """A Sheet workflow that re-fires Restart after our own writeback sends a new
    request ID each time; without this every repeat is a fresh Day 0 call."""
    conn = _RestartConnection("active")
    original_execute = conn.execute

    def execute(query, params=None):
        if "from lead_status_history" in query:
            conn.queries.append((" ".join(query.split()), params))
            return _Rows(one={"changed_at": datetime.now(UTC)})
        return original_execute(query, params)

    conn.execute = execute
    monkeypatch.setattr(lead_actions, "materialize_cadence", lambda *args, **kwargs: 8)
    with pytest.raises(lead_actions.LeadActionError) as exc_info:
        lead_actions._restart_cadence(
            conn,
            request_id=UUID("00000000-0000-0000-0000-000000000001"),
            practice={"id": 1},
            lead_id=UUID("00000000-0000-0000-0000-000000000002"),
            phone="+15555550100",
        )

    assert exc_info.value.code == "restart_too_soon"
    statements = [query for query, _ in conn.queries]
    assert not any(query.startswith("delete from outreach_events") for query in statements)


def test_sheet_lead_input_accepts_the_free_text_lead_type_alias():
    from rpt_agent.services.sheet_models import LeadActionRequest

    request = LeadActionRequest.model_validate({
        "action": "start_cadence",
        "lead_id": None,
        "lead": {
            "full_name": "Synthetic Patient",
            "phone": "+15555550100",
            "date_of_birth": "15-03-1990",
            "location": "Dana Point",
            "lead_type": "Sports Rehab",
        },
    })
    assert (request.lead.lead_type, request.lead.title) == ("Sports Rehab", "Sports Rehab")


def test_sheet_lead_input_rejects_conflicting_title_aliases():
    from pydantic import ValidationError

    from rpt_agent.services.sheet_models import LeadActionRequest

    with pytest.raises(ValidationError):
        LeadActionRequest.model_validate({
            "action": "start_cadence",
            "lead_id": None,
            "lead": {
                "full_name": "Synthetic",
                "phone": "+15555550100",
                "date_of_birth": "15/03/1990",
                "location": "Dana Point",
                "title": "Sports Rehab",
                "lead_type": "Wellness",
            },
        })


def test_migration_and_worker_routing_contracts():
    sql = Path("supabase/migrations/023_google_sheets_n8n_integration.sql").read_text(
        encoding="utf-8"
    )
    assert "lead_action_requests" in sql
    assert "call_transcripts" in sql and "transcript_link" in sql
    assert "destination in ('keap', 'n8n')" in sql
    assert "idx_leads_practice_phone" in sql
    free_text_sql = Path("supabase/migrations/024_free_text_lead_type.sql").read_text(
        encoding="utf-8"
    )
    assert "drop constraint if exists leads_lead_type_check" in free_text_sql
    assert "create index" not in free_text_sql.lower()
    review_sql = Path("supabase/migrations/029_sheet_booked_and_review_pause.sql").read_text(
        encoding="utf-8"
    )
    assert "'do_not_contact', 'booked'" in review_sql
    assert "new.status in ('failed', 'unknown')" in review_sql
    assert "cadence_state = 'paused'" in review_sql
    assert "status = 'skipped'" in review_sql
    assert "paused_for_review" in review_sql

    from rpt_agent import sheet_sync_worker
    from rpt_agent.services.sheet_sync import SHEET_DESTINATION

    # The stored label must stay inside the CHECK constraint above.
    assert SHEET_DESTINATION == "n8n"
    sheet_source = inspect.getsource(sheet_sync_worker._claim_sheet_work)
    assert "destination=%s" in sheet_source and "SHEET_DESTINATION" in sheet_source

    from rpt_agent.services import delivery

    assert "dashboard_call_link" in inspect.getsource(delivery.process_vapi_end_report)


def test_sheet_worker_is_disabled_by_default():
    assert Settings.model_fields["sheet_sync_enabled"].default is False


def test_every_snapshot_carries_lead_status_as_the_board_column():
    # Client, 2026-10-15: Lead Status mirrors the dashboard, so Needs Review never sticks.
    review = build_sheet_snapshot(_SnapshotConnection(), "00000000-0000-0000-0000-000000000002")
    assert review["sheet"]["lead_status"] == "Needs Review"
    booked = build_sheet_snapshot(_BookedSnapshotConnection(), "00000000-0000-0000-0000-000000000002")
    assert booked["sheet"]["lead_status"] == "Booked"

    class Paused(_SnapshotConnection):
        def execute(self, query, params=None):
            rows = super().execute(query, params)
            if query.startswith("select l.id,l.status"):
                rows.one = {**rows.one, "status": "in_progress", "cadence_state": "paused",
                            "needs_review": False, "cadence_total": 4, "next_event_id": None}
            return rows

    paused = build_sheet_snapshot(Paused(), "00000000-0000-0000-0000-000000000002")
    assert paused["sheet"]["lead_status"] == "Paused"
