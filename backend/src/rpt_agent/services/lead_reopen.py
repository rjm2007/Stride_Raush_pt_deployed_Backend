"""Bring a closed lead back into outreach from where it stopped (owner, 2026-11-03).

A lead closes when a call ends "not interested", staff close it on the board or hand it to the
front desk, or its last step runs. Closing skips the steps still planned but keeps them, so they
can come back. Before this, dragging a closed card to In cadence only flipped its status: nothing
was planned, so the worker's spent-cadence sweep closed it again within a minute (production
2026-11-02: a patient who said "not a good time" was moved back four times and stayed Closed).

Continue restores those steps, the first one now and the rest at the gaps they always had, the same
way an unblock continues. Restart from Day 0 is the board's New column and is unchanged.
"""

from __future__ import annotations

from uuid import uuid4

from .lead_review import closed_for_good
from .review import REPLACED_REASON
from .sheet_sync import enqueue_sheet_update

CONTINUE_REASON = "continued by staff from where it stopped"
NOTHING_LEFT = (
    "Nothing is left on this lead's schedule to continue. "
    "Use Restart cadence (or move it to New) to start again from Day 0."
)


class ReopenError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def remaining_steps(conn, lead: dict) -> list[dict]:
    """The steps closing the lead stopped, in order, and only those it may still be sent.

    Skipped and never sent, after the last step that did run. Not a callback (its time has passed),
    not a step a newer referral on the number took over, and not a channel the patient opted out of
    or staff turned off (calls only).
    """
    rows = conn.execute(
        "select oe.id,oe.channel,oe.scheduled_for from outreach_events oe where oe.lead_id=%s "
        "and oe.status='skipped' and oe.executed_at is null and oe.day_offset is not null "
        "and coalesce(oe.failure_reason,'')<>%s "
        "and oe.scheduled_for>coalesce((select max(r.scheduled_for) from outreach_events r "
        "where r.lead_id=oe.lead_id and r.executed_at is not null),'-infinity'::timestamptz) "
        "order by oe.scheduled_for,oe.id",
        (lead["id"], REPLACED_REASON),
    ).fetchall()
    texts_off = lead.get("sms_opt_out") or lead.get("sms_disabled")
    return [
        row for row in rows
        if not (row["channel"] == "call" and lead.get("call_opt_out"))
        and not (row["channel"] == "sms" and texts_off)
    ]


def continue_refusal(conn, lead: dict) -> str | None:
    """Why this closed lead cannot continue where it stopped, or None."""
    if lead["status"] == "do_not_contact":
        return "A Do Not Contact lead cannot be returned to outreach."
    if lead["status"] == "booked":
        return "A booked lead stays booked."
    if closed := closed_for_good(conn, lead):
        return closed
    if lead.get("status_reason") == REPLACED_REASON:
        return ("A newer Sheet row with this phone number took over. "
                "Move this lead to New only if it should take the number back.")
    if lead.get("phone_e164") and conn.execute(
        "select 1 from suppressed_numbers where phone_e164=%s", (lead["phone_e164"],)
    ).fetchone():
        return "This number is blocked. An admin can unblock it on this lead's page."
    if lead.get("phone_e164") and conn.execute(
        "select 1 from leads where practice_id=%s and phone_e164=%s and id<>%s "
        "and cadence_state in ('pending','active','paused') limit 1",
        (lead["practice_id"], lead["phone_e164"], lead["id"]),
    ).fetchone():
        return "Another lead with this phone number is in outreach, so this one cannot continue."
    if conn.execute(
        "select 1 from outreach_events where lead_id=%s and status in ('in_flight','attempted') "
        "limit 1",
        (lead["id"],),
    ).fetchone():
        return "Wait for the current call or text result first."
    if not remaining_steps(conn, lead):
        return NOTHING_LEFT
    return None


def continue_closed_lead(conn, lead: dict) -> int:
    """Put a closed lead back in cadence from the step where it stopped. Returns the steps restored.

    `lead` needs id, practice_id, status, status_reason, phone_e164 and the opt-out columns.
    """
    if refusal := continue_refusal(conn, lead):
        raise ReopenError(409, refusal)
    steps = remaining_steps(conn, lead)
    # Keep the cadence's own spacing, counted from now: the first stopped step runs next (the
    # worker still applies calling hours and daily limits) and the rest follow at their old gaps.
    conn.execute(
        "update outreach_events set status='planned',failure_reason=null,"
        "scheduled_for=now()+(scheduled_for-%s),updated_at=now() where id=any(%s)",
        (steps[0]["scheduled_for"], [row["id"] for row in steps]),
    )
    conn.execute(
        "update leads set status='in_progress',cadence_state='active',status_reason=%s,"
        "callback_requested_at=null,callback_notes=null,status_changed_at=now() where id=%s",
        (CONTINUE_REASON, lead["id"]),
    )
    enqueue_sheet_update(
        conn, lead_id=str(lead["id"]), event_type="cadence_continued",
        source_key=f"{lead['id']}:{uuid4().hex}",
    )
    return len(steps)
