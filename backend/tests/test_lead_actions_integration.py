"""Sheet command rules on a real Postgres schema: "Already booked" and Do Not Contact.

Needs TEST_DATABASE_URL (a disposable database with the migrations applied, never production).
Each test builds its own practice and 555 leads, and removes them afterwards.
"""

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from rpt_agent.config import get_settings
from rpt_agent.db import get_pool

pytestmark = pytest.mark.integration


@pytest.fixture
def env(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    slug = f"test-actions-{uuid4().hex[:10]}"
    conn = psycopg.connect(url, row_factory=dict_row, autocommit=True)
    practice = conn.execute(
        "insert into practices(name,slug,timezone) values('Synthetic Practice',%s,'America/Los_Angeles') "
        "returning id",
        (slug,),
    ).fetchone()["id"]
    conn.execute("insert into practice_settings(practice_id) values(%s)", (practice,))
    monkeypatch.setenv("SUPABASE_DB_URL", url)
    monkeypatch.setenv("PRACTICE_SLUG", slug)
    monkeypatch.setenv("SHEET_SYNC_ENABLED", "false")
    get_settings.cache_clear()
    get_pool.cache_clear()

    class Env:
        db = conn
        practice_id = practice

        def one(self, sql, *args):
            return conn.execute(sql, args).fetchone()

        def lead(self, name, dob="1990-01-01", phone="+15552010000", status="in_progress"):
            lead_id = conn.execute(
                "insert into leads(practice_id,source_system,full_name,first_name,last_name,phone_e164,"
                "date_of_birth,status,cadence_state,is_test) values(%s,'google_sheets',%s,%s,%s,%s,%s,%s,"
                "'active',true) returning id",
                (practice, name, name.split()[0], name.split()[-1], phone, dob, status),
            ).fetchone()["id"]
            for attempt in (1, 2):
                conn.execute(
                    "insert into outreach_events(lead_id,attempt_no,channel,status,scheduled_for) "
                    "values(%s,%s,'call','planned',now()+interval '1 day')",
                    (lead_id, attempt),
                )
            return lead_id

    yield Env()

    lead_ids = [r["id"] for r in conn.execute("select id from leads where practice_id=%s", (practice,))]
    conn.execute("delete from integration_outbox where aggregate_id=any(%s)", ([str(i) for i in lead_ids],))
    conn.execute("delete from lead_status_history where lead_id=any(%s)", (lead_ids,))
    conn.execute("delete from outreach_events where lead_id=any(%s)", (lead_ids,))
    conn.execute("delete from suppressed_numbers where phone_e164='+15552010000'")
    conn.execute("delete from leads where practice_id=%s", (practice,))
    conn.execute("delete from practice_settings where practice_id=%s", (practice,))
    conn.execute("delete from practices where id=%s", (practice,))
    conn.close()
    get_pool.cache_clear()
    get_settings.cache_clear()


def test_repeat_patient_with_another_birthday_is_a_new_referral(env):
    from rpt_agent.services.lead_actions import _same_person_already_booked

    env.lead("Family Member", status="booked")
    lead_data = {"full_name": "Family Member", "date_of_birth": "1955-05-05"}
    assert _same_person_already_booked(env.db, env.practice_id, "+15552010000", lead_data) is None


def test_patient_booked_long_ago_can_be_referred_again(env):
    from rpt_agent.services.lead_actions import _same_person_already_booked

    lead = env.lead("Old Patient", status="booked")
    env.db.execute("update leads set status_changed_at=now()-interval '90 days',"
                   "updated_at=now()-interval '90 days' where id=%s", (lead,))
    lead_data = {"full_name": "Old Patient", "date_of_birth": "1990-01-01"}
    assert _same_person_already_booked(env.db, env.practice_id, "+15552010000", lead_data) is None


def test_person_booked_from_the_sheet_recently_counts_as_booked(env):
    from rpt_agent.services.lead_actions import _same_person_already_booked

    lead = env.lead("Sheet Booked", status="booked")
    lead_data = {"full_name": "Sheet Booked", "date_of_birth": None}
    assert _same_person_already_booked(env.db, env.practice_id, "+15552010000", lead_data)["id"] == lead


def test_person_still_in_cadence_is_left_to_the_repeat_patient_rule(env):
    from rpt_agent.services.lead_actions import _same_person_already_booked

    env.lead("Still Calling")
    lead_data = {"full_name": "Still Calling", "date_of_birth": "1990-01-01"}
    assert _same_person_already_booked(env.db, env.practice_id, "+15552010000", lead_data) is None


def test_do_not_contact_from_the_sheet_settles_an_old_review_note(env):
    # A lead flagged "call could not be placed", then marked Do Not Contact, used to stay in
    # Needs attention with the stale note. Do Not Contact now resolves it (Closed column).
    from rpt_agent.services.lead_actions import _do_not_contact

    lead = env.lead("Settled Note")
    env.db.execute("update leads set status='needs_attention',needs_review=true,"
                   "review_reason='dispatch failed: vapi returned HTTP 400' where id=%s", (lead,))
    _do_not_contact(env.db, request_id=uuid4(), practice={"id": env.practice_id}, lead_id=lead,
                    phone="+15552010000")
    row = env.one("select status,needs_review,review_reason,review_resolved_at from leads where id=%s", lead)
    assert (row["status"], row["needs_review"], row["review_reason"]) == ("do_not_contact", False, None)
    assert row["review_resolved_at"] is not None
