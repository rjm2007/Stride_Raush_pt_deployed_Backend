"""Sheet Call Outcome / Message Outcome on a real Postgres schema.

Needs TEST_DATABASE_URL (a disposable database with the migrations applied, never production).
Builds its own practice, cadence and a synthetic 555 lead, and removes them afterwards.
"""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from rpt_agent.services.sheet_sync import build_sheet_snapshot

pytestmark = pytest.mark.integration

# The production shape around a text-only day: Day 0 call + text, Day 1 text only, Day 3 call.
STEPS = [(0, "call"), (0, "sms"), (1, "sms"), (3, "call")]


@pytest.fixture
def db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    conn = psycopg.connect(url, row_factory=dict_row, autocommit=True)
    practice = conn.execute(
        "insert into practices(name,slug) values('Synthetic Practice',%s) returning id",
        (f"test-{uuid4().hex}",),
    ).fetchone()["id"]
    version = conn.execute(
        "insert into cadence_versions(practice_id,version_number,name,status,activated_at) "
        "values(%s,1,'Synthetic v1','active',now()) returning id",
        (practice,),
    ).fetchone()["id"]
    for order, (day, channel) in enumerate(STEPS):
        conn.execute(
            "insert into cadence_steps(practice_id,cadence_version_id,step_order,day_offset,channel,"
            "key,description,is_active) values(%s,%s,%s,%s,%s,%s,%s,true)",
            (practice, version, order, day, channel, f"s{order}-{uuid4().hex[:6]}", f"Day {day}"),
        )
    lead = str(conn.execute(
        "insert into leads(practice_id,full_name,first_name,last_name,phone_e164,status,"
        "cadence_state,source_system,status_changed_at) values(%s,'Synthetic Patient','Synthetic',"
        "'Patient',%s,'in_progress','active','google_sheets',now()) returning id",
        (practice, f"+1555{uuid4().int % 10_000_000:07d}"),
    ).fetchone()["id"])
    start = datetime.now(UTC) - timedelta(days=2)
    events = {}
    for step in conn.execute(
        "select id,day_offset,channel from cadence_steps where cadence_version_id=%s "
        "order by step_order", (version,),
    ).fetchall():
        events[(step["day_offset"], step["channel"])] = conn.execute(
            "insert into outreach_events(lead_id,cadence_step_id,cadence_version_id,channel,"
            "day_offset,scheduled_for,status) values(%s,%s,%s,%s,%s,%s,'planned') returning id",
            (lead, step["id"], version, step["channel"], step["day_offset"],
             start + timedelta(days=step["day_offset"])),
        ).fetchone()["id"]
    yield {"conn": conn, "lead": lead, "events": events, "start": start}
    conn.execute("delete from integration_outbox where aggregate_id=%s", (lead,))
    conn.execute("delete from leads where practice_id=%s", (practice,))
    conn.execute("delete from practices where id=%s", (practice,))
    conn.close()


def _call(db, day, outcome):
    at = db["start"] + timedelta(days=day, minutes=5)
    db["conn"].execute(
        "update outreach_events set status='delivered',outcome=%s,executed_at=%s,settled_at=%s "
        "where id=%s", (outcome, at, at, db["events"][(day, "call")]))


def _text(db, day):
    at = db["start"] + timedelta(days=day, minutes=10)
    event = db["events"][(day, "sms")]
    db["conn"].execute(
        "update outreach_events set status='delivered',executed_at=%s,settled_at=%s where id=%s",
        (at, at, event))
    db["conn"].execute(
        "insert into sms_messages(lead_id,outreach_event_id,direction,body,occurred_at,"
        "delivery_status,delivered_at,provider_message_id) "
        "values(%s,%s,'outbound','Hi',%s,'delivered',%s,%s)",
        (db["lead"], event, at, at, f"SM{uuid4().hex}"))


def test_text_only_day_keeps_the_last_call_outcome(db):
    """Production 2026-11-06: after the Day 1 text, Call Outcome went blank on called leads."""
    _call(db, 0, "voicemail")
    _text(db, 0)
    _text(db, 1)
    sheet = build_sheet_snapshot(db["conn"], db["lead"])["sheet"]
    assert sheet["cadence_day"] == "Day 1"
    assert sheet["call_outcome"] == "Voicemail left"
    assert sheet["message_outcome"] == "Delivered"


def test_newest_call_wins_and_the_last_text_stays(db):
    _call(db, 0, "voicemail")
    _text(db, 0)
    _text(db, 1)
    _call(db, 3, "no_answer")
    sheet = build_sheet_snapshot(db["conn"], db["lead"])["sheet"]
    assert sheet["cadence_day"] == "Day 3"
    assert sheet["call_outcome"] == "No answer"
    assert sheet["message_outcome"] == "Delivered"


def test_no_call_yet_leaves_call_outcome_empty(db):
    _text(db, 0)
    sheet = build_sheet_snapshot(db["conn"], db["lead"])["sheet"]
    assert sheet["call_outcome"] is None
    assert sheet["message_outcome"] == "Delivered"
