"""Staff reviews: why a lead was flagged, in plain words, and what staff chose to do about it.

Incident 2026-10-21: one lead was flagged because its Name cell was edited in the Sheet, another
because its Day 0 text failed (Twilio 30006, a landline). Staff saw "needs review", pressed Resume,
and the cadence looked live while the worker sent nothing (needs_review stayed set). Nobody could see
what had changed, and no record said who decided what.

Every flag now has a review row (`lead_reviews`, migration 048) with a reason code. The code puts it
in a group, and each group offers a short list of choices. A choice either fully resumes the lead
(review cleared, status in_progress, cadence active, the paused steps back on the schedule) or closes
it. Resume and the board's "In cadence" refuse a flagged lead, so a choice is the only way through.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from .lead_status import _practice_clock, clamp_to_business_hours, record_status
from .review import PAUSE_SKIP_REASON, restore_pause_skipped, skip_remaining_planned
from .sheet_sync import enqueue_sheet_update

# --- codes, groups, choices -----------------------------------------------------------------

GROUP_OF = {
    "name_changed": "name",
    "phone_changed": "phone",
    "sms_failed": "text",
    "booking_link_failed": "text",
    "wrong_person": "call",
    "call_no_outcome": "call",
    "call_outcome_not_applied": "call",
    "unrecognized_status": "call",
    "call_failed": "technical",
    "dispatch_failed": "technical",
    "dispatch_unconfirmed": "technical",
    "call_result_missing": "technical",
    "sms_unconfirmed": "technical",
    "booking_link_unconfirmed": "technical",
    "manual_sms_unconfirmed": "technical",
    "number_blocked": "blocked",
    "moved_by_staff": "other",
    "other": "other",
}

GROUP_LABELS = {
    "name": "Name changed",
    "phone": "Phone changed",
    "text": "Text failed",
    "call": "Call problem",
    "technical": "Not confirmed",
    "blocked": "Number blocked",
    "other": "Other",
}

TITLES = {
    "name_changed": "Name changed in the Sheet",
    "phone_changed": "Phone number changed in the Sheet",
    "sms_failed": "Text not delivered",
    "booking_link_failed": "Booking-link text not delivered",
    "wrong_person": "Wrong person or wrong number",
    "call_no_outcome": "Call answered, no outcome",
    "call_outcome_not_applied": "Call outcome could not be applied",
    "unrecognized_status": "Unknown call result",
    "call_failed": "Call could not be placed",
    "dispatch_failed": "Call or text could not be sent",
    "dispatch_unconfirmed": "Call or text not confirmed",
    "call_result_missing": "Call result never arrived",
    "sms_unconfirmed": "Text delivery not confirmed",
    "booking_link_unconfirmed": "Booking-link text not confirmed",
    "manual_sms_unconfirmed": "Dashboard text not confirmed",
    "number_blocked": "Number blocked",
    "moved_by_staff": "Moved to review by staff",
    "other": "Needs review",
}

CHOICE_LABELS = {
    "use_new_name": "Same person, use new name & continue",
    "keep_old_name": "Same person, keep old name & continue",
    "different_person": "Different person, close this lead",
    "calls_only": "Continue with calls only",
    "retry_texts": "Try texting again",
    "number_ok": "Number is right, continue",
    "wrong_number": "Wrong number, close lead",
    "continue": "Continue",
    "close_phone_changed": "Close this lead (new number goes in a new row)",
    "front_desk": "Front desk will handle",
}

GROUP_CHOICES = {
    "name": ["use_new_name", "keep_old_name", "different_person", "front_desk"],
    # Only for leads flagged before 2026-10-22; a phone change now closes the lead at once.
    "phone": ["close_phone_changed", "front_desk"],
    "text": ["calls_only", "retry_texts", "front_desk"],
    "call": ["number_ok", "wrong_number", "front_desk"],
    "technical": ["continue", "front_desk"],
    # Unblocking stays where it was (lead page / Administration, admins only).
    "blocked": ["front_desk"],
    "other": ["continue", "front_desk"],
}

RESUME_CHOICES = {"use_new_name", "keep_old_name", "calls_only", "retry_texts", "number_ok", "continue"}
# Closed for good: the number (or the person) on this lead is wrong. Staff add a new Sheet row.
WRONG_LEAD_CHOICES = {"different_person", "wrong_number", "close_phone_changed"}

FRONT_DESK_REASON = "Handled by front desk"
TEXTS_OFF_SKIP_REASON = "texts off (calls only)"

# Outcome Status in the Sheet (no new columns: only the words in the existing cell change).
SHEET_RESOLVED = {
    "use_new_name": "Resolved: new name used",
    "keep_old_name": "Resolved: old name kept",
    "different_person": "Closed: different person, add a new row",
    "calls_only": "Resolved: calls only",
    "retry_texts": "Resolved: texting again",
    "number_ok": "Resolved: number confirmed",
    "wrong_number": "Closed: wrong number",
    "continue": "Resolved: continued",
    "close_phone_changed": "Phone changed: add a new row",
    "front_desk": "Closed: handled by front desk",
}
SHEET_TEXTS_OFF = "Calls only (texts off)"


def sheet_open_status(code: str | None, details: dict | None) -> str:
    """Outcome Status while a review is open. Each contains "needs review", which the Sheet
    worker reads as "no command to run on this row" (sheet_direct.needs_processing)."""
    group = group_of(code)
    if code == "number_blocked":
        return "Number blocked; needs review"  # the words the Start command already writes
    if code == "name_changed":
        return "Needs review: name changed"
    if group == "phone":
        return "Needs review: phone changed"
    if group == "text":
        landline = sms_failure((details or {}).get("error_code"))["landline"]
        return "Needs review: text failed (landline)" if landline else "Needs review: text failed"
    if code == "wrong_person":
        return "Needs review: wrong number"
    if group == "call":
        return "Needs review: call result unclear"
    if group == "technical":
        return "Needs review: not confirmed"
    return "Needs review"

SOURCE_LABELS = {
    "sheet": "Google Sheet",
    "text": "Text message",
    "call": "Call",
    "worker": "Outreach worker",
    "dashboard": "Dashboard",
    "db": "System",
    "legacy": "System",
    "system": "System",
}

# Twilio's error codes, in staff words. Landline: the number cannot take texts at all, so trying
# again is pointless (the option is hidden). Permanent: the same, for other reasons.
TWILIO_REASONS = {
    "30006": "this number can't receive texts (likely a landline)",
    "21614": "this number can't receive texts (likely a landline)",
    "30005": "this number doesn't exist or is no longer in service",
    "21211": "this phone number is not valid",
    "21610": "the patient has replied STOP to our number before",
    "30003": "the phone was unreachable (switched off or out of signal)",
    "30004": "the message was blocked by the patient or their carrier",
    "30007": "the carrier filtered the message as spam",
    "30008": "the carrier reported an unknown error",
    "30034": "our texting number is not yet registered with US carriers",
    "30032": "our toll-free texting number is not verified yet",
}
LANDLINE_CODES = {"30006", "21614"}
PERMANENT_CODES = LANDLINE_CODES | {"30005", "21211", "21610"}


class ReviewError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def group_of(code: str | None) -> str:
    return GROUP_OF.get(code or "other", "other")


def sms_failure(error_code: Any) -> dict[str, Any]:
    """Plain reason for a failed text, and whether trying again could ever work."""
    code = str(error_code or "").strip()
    if code in TWILIO_REASONS:
        reason = TWILIO_REASONS[code]
    elif code:
        reason = f"the carrier did not deliver it (Twilio error {code})"
    else:
        reason = "the carrier did not deliver it (no reason given)"
    return {
        "reason": reason,
        "error_code": code or None,
        "landline": code in LANDLINE_CODES,
        "permanent": code in PERMANENT_CODES,
    }


def step_name(channel: Any, day_offset: Any) -> str:
    kind = "call" if channel == "call" else "text"
    return f"Day {int(day_offset)} {kind}" if day_offset is not None else f"Callback {kind}"


def mask_phone(phone: Any) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    return f"…{digits[-4:]}" if digits else "…"


def _clinic_time(value: datetime, tz) -> str:
    local = value.astimezone(tz)
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"{local:%a} {local:%b} {local.day}, {hour}:{local:%M} {local:%p} PT"


def _clinic_date(value: datetime, tz) -> str:
    local = value.astimezone(tz)
    return f"{local:%b} {local.day}, {local.year}"


# --- reading reviews --------------------------------------------------------------------------

REVIEW_COLUMNS = (
    "id,lead_id,code,message,details,source,outreach_event_id,flagged_at,resolved_at,"
    "resolved_by,resolved_by_name,resolution,note"
)


def open_reviews(conn, lead_id: str) -> list[dict]:
    """Open review rows for a lead, oldest first: staff settle them one at a time, in order.

    QA 2026-10-22: one choice used to settle every open review, so a lead with a landline text
    failure AND a name change could be resumed by "use new name" with texts on, to a landline.
    """
    return conn.execute(
        f"select {REVIEW_COLUMNS} from lead_reviews where lead_id=%s and resolved_at is null "
        "order by flagged_at,id",
        (lead_id,),
    ).fetchall()


def _legacy_row(lead: dict) -> dict:
    """A flagged lead with no review row (written before migration 048 reached it)."""
    return {
        "id": None, "lead_id": lead.get("id"), "code": "other",
        "message": lead.get("review_reason") or "Needs review", "details": {},
        "source": "legacy", "outreach_event_id": None,
        "flagged_at": lead.get("review_flagged_at"), "resolved_at": None,
        "resolved_by": None, "resolved_by_name": None, "resolution": None, "note": None,
    }


def _plain_reason(row: dict, lead: dict) -> str:
    code = row["code"]
    details = row.get("details") or {}
    if code == "name_changed":
        old = details.get("old_name") or lead.get("full_name") or "?"
        if not details.get("new_name"):
            # Flagged before 2026-10-22: only "Name changed; needs review" was stored (the D. S. lead).
            return (f"The Name in the Google Sheet was changed; the new name was not recorded (flagged "
                    f"before Oct 22). The name on file is “{old}”. Check the Sheet row: keep the name on "
                    "file, or close the lead if it is a different person.")
        return (f"The Name in the Google Sheet changed from “{old}” "
                f"to “{details['new_name']}”. Is it the same person?")
    if code in {"sms_failed", "booking_link_failed"}:
        what = "booking-link text" if code == "booking_link_failed" else (
            step_name("sms", details["day_offset"]) if details.get("day_offset") is not None
            else "text")
        failure = sms_failure(details.get("error_code"))
        if not details.get("error_code") and details.get("refused"):
            failure["reason"] = "Twilio refused to send it"
        return f"The {what} was not delivered: {failure['reason']}."
    if code == "wrong_person":
        # Rows from before 048 keep the agent's note only as the stored reason text.
        message = str(row.get("message") or "").strip()
        note = str(details.get("note") or "").strip() or (
            message if message.lower() not in {"", "wrong phone number", "needs review"} else "")
        base = "On the call, the person said this is the wrong number or not the patient."
        return f"{base} Agent's note: {note}" if note else base
    if code == "call_no_outcome":
        return "The call was answered, but the agent reported no outcome. Read the transcript."
    if code == "call_outcome_not_applied":
        return "The call summary gave an outcome the system could not apply. Read the transcript."
    if code == "unrecognized_status":
        return "The agent reported a call result the system does not know. Read the transcript."
    if code == "call_failed":
        return "The cadence call could not be placed (the phone provider refused it)."
    if code == "dispatch_failed":
        return "A cadence call or text could not be sent."
    if code == "dispatch_unconfirmed":
        return ("A call or text was handed to the provider but its result never came back. It was "
                "not retried, so the patient is not contacted twice.")
    if code == "call_result_missing":
        return "A call was placed but its result never arrived. It was not retried."
    if code == "sms_unconfirmed":
        return "A text was sent but its delivery report never arrived. It was not retried."
    if code == "booking_link_unconfirmed":
        return "The booking-link text may or may not have gone out. It was not retried."
    if code == "manual_sms_unconfirmed":
        return "A text sent from the dashboard may or may not have gone out. It was not retried."
    if code == "number_blocked":
        return ("This number is on the blocked list (the patient once asked not to be contacted). "
                "Nothing goes out until an admin unblocks it on this lead's page.")
    if code == "moved_by_staff":
        who = details.get("by")
        return f"{who} moved this lead to Needs Review on the board." if who else \
            "Staff moved this lead to Needs Review on the board."
    if code == "phone_changed":
        if not details.get("new_phone"):  # flagged before Oct 22: the numbers were not recorded
            return ("The phone number changed in the Google Sheet (flagged before Oct 22, so the numbers "
                    "were not recorded). Close this lead and add the new number as a new row.")
        return row.get("message") or "The phone number changed in the Google Sheet."
    return row.get("message") or lead.get("review_reason") or "This lead needs staff review."


def _proof(row: dict, lead_name: str | None = None) -> list[dict[str, str]]:
    code = row["code"]
    details = row.get("details") or {}
    proof: list[dict[str, str]] = []
    if code == "name_changed":
        proof += [{"label": "Old name", "value": str(details.get("old_name") or lead_name or "—")},
                  {"label": "New name", "value": str(details.get("new_name") or "Not recorded (see Sheet)")}]
    if code == "phone_changed":
        if details.get("old_phone"):
            proof.append({"label": "Old number", "value": str(details["old_phone"])})
        if details.get("new_phone"):
            proof.append({"label": "New number", "value": str(details["new_phone"])})
    if code in {"sms_failed", "booking_link_failed"}:
        if details.get("day_offset") is not None:
            proof.append({"label": "Step", "value": step_name("sms", details["day_offset"])})
        if details.get("error_code"):
            proof.append({"label": "Error code", "value": f"Twilio {details['error_code']}"})
    if code in {"call_failed", "dispatch_failed", "dispatch_unconfirmed", "sms_unconfirmed",
                "call_result_missing"} and details.get("channel"):
        proof.append({"label": "Step", "value": step_name(details["channel"], details.get("day_offset"))})
    return proof


def describe(row: dict, lead: dict, *, has_calls: bool = False) -> dict[str, Any]:
    """One review as the dashboard shows it: what happened, the proof, and the choices."""
    code = row["code"] if row["code"] in GROUP_OF else "other"
    details = row.get("details") or {}
    group = group_of(code)
    failure = sms_failure(details.get("error_code")) if group == "text" else None
    choices = [
        choice for choice in GROUP_CHOICES[group]
        if not (choice == "retry_texts" and failure and failure["permanent"])
        # A pre-048 name review never recorded the new name, so there is nothing to "use".
        and not (choice == "use_new_name" and not details.get("new_name"))
    ]
    lead_id = str(lead.get("id") or row.get("lead_id"))
    return {
        "id": row.get("id"),
        "code": code,
        "group": group,
        "group_label": GROUP_LABELS[group],
        "title": TITLES[code],
        "reason": _plain_reason({**row, "code": code}, lead),
        "proof": _proof({**row, "code": code}, lead.get("full_name")),
        "flagged_at": row.get("flagged_at"),
        "source": row.get("source"),
        "source_label": SOURCE_LABELS.get(str(row.get("source")), "System"),
        "landline": bool(failure and failure["landline"]),
        "transcript_url": f"/leads/{lead_id}/conversations/calls"
        if group == "call" and has_calls else None,
        "options": [{"choice": choice, "label": CHOICE_LABELS[choice]} for choice in choices],
    }


def lead_review_summary(conn, lead: dict) -> dict[str, Any] | None:
    """The open review a flagged lead shows (the oldest open one), with the others listed."""
    if not lead.get("needs_review"):
        return None
    rows = open_reviews(conn, str(lead["id"]))
    primary = rows[0] if rows else _legacy_row(lead)
    has_calls = bool(conn.execute(
        "select 1 from call_logs where lead_id=%s limit 1", (lead["id"],)
    ).fetchone())
    summary = describe(primary, lead, has_calls=has_calls)
    summary["also"] = [
        {"title": TITLES.get(row["code"], TITLES["other"]), "flagged_at": row["flagged_at"]}
        for row in rows[1:]
    ]
    return summary


# --- what a choice will do ----------------------------------------------------------------------


def _first_flag_time(rows: list[dict], lead: dict) -> datetime:
    times = [row["flagged_at"] for row in rows if row.get("flagged_at")]
    if lead.get("review_flagged_at"):
        times.append(lead["review_flagged_at"])
    return min(times) if times else datetime.now(UTC)


def _resume_shift(conn, lead_id: str, flagged_at: datetime, now: datetime) -> tuple[timedelta, list]:
    """How far the paused steps move on resume, and those steps.

    Pause means postpone: every remaining step moves by the time the lead sat in review, so the
    cadence keeps its spacing (day 5 still lands two days after day 3). A step that was already
    overdue when the lead was flagged (held back by calling hours) would still be overdue, and with
    it everything behind it, so the shift is at least enough to bring the earliest step to now:
    one step goes out promptly, the rest keep their gaps. The worker still applies calling hours,
    holidays and daily limits.
    """
    steps = conn.execute(
        "select oe.id,oe.channel,oe.day_offset,oe.scheduled_for,oe.status,cs.description "
        "from outreach_events oe left join cadence_steps cs on cs.id=oe.cadence_step_id "
        "where oe.lead_id=%s and (oe.status='planned' or (oe.status='skipped' and oe.failure_reason=%s)) "
        "order by oe.scheduled_for nulls last,oe.id",
        (lead_id, PAUSE_SKIP_REASON),
    ).fetchall()
    times = [step["scheduled_for"] for step in steps if step["scheduled_for"]]
    shift = max(now - flagged_at, now - min(times) if times else timedelta(0), timedelta(0))
    return shift, steps


def _failed_text_event(conn, lead_id: str, rows: list[dict]) -> dict | None:
    """The failed cadence text a "Try texting again" sends again (the review's own step)."""
    for row in rows:
        if row.get("outreach_event_id") and group_of(row["code"]) == "text":
            event = conn.execute(
                "select id,cadence_step_id,cadence_version_id,channel,day_offset,status "
                "from outreach_events where id=%s and lead_id=%s and channel='sms' "
                "and status in ('failed','unknown')",
                (row["outreach_event_id"], lead_id),
            ).fetchone()
            if event:
                return event
    return None


def _next_step_text(conn, lead: dict, rows: list[dict], choice: str, now: datetime) -> str:
    lead_id = str(lead["id"])
    shift, steps = _resume_shift(conn, lead_id, _first_flag_time(rows, lead), now)
    upcoming = [
        (step["scheduled_for"] + shift, step_name(step["channel"], step["day_offset"]))
        for step in steps
        if step["scheduled_for"] and not (choice == "calls_only" and step["channel"] == "sms")
        and not (step["channel"] == "sms" and lead.get("sms_disabled") and choice != "retry_texts")
    ]
    if choice == "retry_texts" and (failed := _failed_text_event(conn, lead_id, rows)):
        upcoming.append((now, f"{step_name('sms', failed['day_offset'])} again"))
    if not upcoming:
        return "none left, so the lead moves to Closed"
    when, name = min(upcoming, key=lambda item: item[0])
    tz, hours, holidays = _practice_clock(conn, lead_id)
    if not lead.get("is_test"):
        when = clamp_to_business_hours(max(when, now), tz, hours, holidays)
    if when <= now + timedelta(minutes=2):
        return f"{name}, right away (within calling hours)"
    return f"{name}, {_clinic_time(when, tz)}"


def _effect(choice: str, details: dict, lead: dict, group: str = "other", code: str = "") -> str:
    if choice == "use_new_name":
        return f"Name becomes {details.get('new_name') or 'the Sheet name'}"
    if choice == "keep_old_name":
        if not details.get("new_name"):
            return (f"Name stays {lead.get('full_name')}; the name the Sheet worker last read from the row "
                    "is accepted")
        return f"Name stays {lead.get('full_name')}"
    if choice == "calls_only":
        return "Texts off"
    if choice == "retry_texts":
        if code == "booking_link_failed":
            # QA 2026-10-22: this promised a resend that never happened. The link was asked for on
            # one call; it is not sent again by itself (the agent offers it on the next call).
            return ("Texts stay on. The booking link is not resent automatically; the next cadence "
                    "text goes out as planned")
        return "Texts stay on and the failed text goes out again"
    if choice == "number_ok":
        return "Number kept"
    if choice == "continue":
        if group == "technical":
            return "The unconfirmed step is not repeated"
        return "Outreach picks up where it paused"
    if choice == "front_desk":
        return "Outreach stops and the lead moves to Closed (Handled by front desk)"
    return "Outreach stops and the lead moves to Closed for good"


def options_preview(conn, lead: dict, now: datetime | None = None) -> dict[str, Any]:
    """The review card plus, per choice, what will happen and the next step (confirm pop-up)."""
    now = now or datetime.now(UTC)
    summary = lead_review_summary(conn, lead)
    if not summary:
        return {"review": None, "options": []}
    rows = open_reviews(conn, str(lead["id"])) or [_legacy_row(lead)]
    details = rows[0].get("details") or {}
    options = []
    for option in summary["options"]:
        choice = option["choice"]
        effect = _effect(choice, details, lead, summary["group"], summary["code"])
        if choice in RESUME_CHOICES and len(rows) > 1:
            next_step = (f"Next step: the next open review ({TITLES.get(rows[1]['code'], TITLES['other'])}); "
                         "the lead stays paused until every review is resolved.")
        elif choice in RESUME_CHOICES:
            next_step = f"Next step: {_next_step_text(conn, lead, rows, choice, now)}."
        elif choice == "front_desk":
            next_step = "Next step: the front desk contacts the patient."
        else:
            next_step = "Next step: add the patient as a new row in the Google Sheet."
        options.append({
            **option,
            "effect": effect,
            "next_step": next_step,
            "confirm": f"{option['label']} for {lead.get('full_name')}. {effect}. {next_step}",
        })
    return {"review": summary, "options": options}


# --- resolving ---------------------------------------------------------------------------------


def close_open_reviews(
    conn, lead_id: str, resolution: str, *, by: str | None, by_name: str | None,
    note: str | None = None,
) -> int:
    """Mark every open review of a lead resolved (before needs_review is cleared, so migration
    048's clear trigger finds nothing left and the record names the person and the choice)."""
    rows = conn.execute(
        "update lead_reviews set resolved_at=now(),resolved_by=%s,resolved_by_name=%s,"
        "resolution=%s,note=%s,updated_at=now() where lead_id=%s and resolved_at is null returning id",
        (by or "system", (by_name or by or "System")[:120], resolution, note, lead_id),
    ).fetchall()
    return len(rows)


def _legacy_sheet_name(conn, lead: dict, row: dict) -> dict:
    """"Keep old name" on a name review flagged before 2026-10-22, which never stored the new name.

    QA 2026-10-22: accepting "whatever the Sheet holds next" let a different person's name typed
    over the row pass silently. Accepted instead: only the Name the Sheet worker last read from the
    row (sheet_row_state.sheet_name), which is recorded on the review too. Unknown -> refused.
    """
    found = conn.execute(
        "select sheet_name from sheet_row_state where lead_id=%s", (lead["id"],)
    ).fetchone()
    name = " ".join(str((found or {}).get("sheet_name") or "").split())
    if not name:
        raise ReviewError(409, "The name in the Sheet row is not recorded yet (the next Sheet read, "
                               "within about 5 minutes, records it). Try again then, or choose "
                               "Different person or Front desk will handle.")
    details = {"old_name": lead.get("full_name"), "new_name": name}
    if row.get("id"):
        conn.execute("update lead_reviews set details=details||%s where id=%s",
                     (Jsonb(details), row["id"]))
    # The Sheet already matches the name on file: nothing to accept.
    same = " ".join(name.lower().split()) == " ".join(str(lead.get("full_name") or "").lower().split())
    return {**details, "new_name": None} if same else details


def _split_name(full_name: str) -> tuple[str, str | None]:
    parts = full_name.split()
    return parts[0], " ".join(parts[1:]) or None


def _resume_guards(conn, lead: dict, choice: str) -> None:
    if lead.get("call_opt_out") and (lead.get("sms_opt_out") or choice == "calls_only"
                                       or lead.get("sms_disabled")):
        raise ReviewError(409, "This lead has opted out of calls and cannot be texted, so outreach "
                               "cannot continue. Choose Front desk will handle.")
    if lead.get("phone_e164") and conn.execute(
        "select 1 from suppressed_numbers where phone_e164=%s", (lead["phone_e164"],)
    ).fetchone():
        raise ReviewError(409, "This number is blocked. An admin can unblock it on this lead's page.")


def _apply_choice(conn, lead: dict, rows: list[dict], choice: str, details: dict) -> None:
    """What the choice itself changes on the lead (name, texts), before or without resuming."""
    lead_id = str(lead["id"])
    if choice == "use_new_name":
        new_name = " ".join(str(details.get("new_name") or "").split())
        if not new_name:
            raise ReviewError(409, "The new name is not recorded on this review.")
        first, last = _split_name(new_name)
        conn.execute(
            "update leads set full_name=%s,first_name=%s,last_name=%s,sheet_name_accepted=null "
            "where id=%s",
            (new_name, first, last, lead_id),
        )
    elif choice == "keep_old_name":
        conn.execute(
            "update leads set sheet_name_accepted=%s where id=%s",
            (" ".join(str(details.get("new_name") or "").split()) or None, lead_id),
        )
    elif choice == "calls_only":
        conn.execute(
            "update leads set sms_disabled=true,sms_disabled_at=now(),sms_disabled_reason=%s where id=%s",
            (_plain_reason(rows[0], lead)[:500], lead_id),
        )
    elif choice == "retry_texts":
        conn.execute(
            "update leads set sms_disabled=false,sms_disabled_at=null,sms_disabled_reason=null "
            "where id=%s",
            (lead_id,),
        )


def _resume(conn, lead: dict, rows: list[dict], choice: str, now: datetime) -> dict:
    lead_id = str(lead["id"])
    lead = {**lead, **conn.execute(
        "select sms_disabled from leads where id=%s", (lead_id,)).fetchone()}
    shift, _ = _resume_shift(conn, lead_id, _first_flag_time(rows, lead), now)
    restored = restore_pause_skipped(conn, lead_id)
    shifted = len(conn.execute(
        "update outreach_events set scheduled_for=scheduled_for+%s,updated_at=now() "
        "where lead_id=%s and status='planned' returning id",
        (shift, lead_id),
    ).fetchall())
    texts_off = choice == "calls_only" or (lead.get("sms_disabled") and choice != "retry_texts")
    if texts_off:
        conn.execute(
            "update outreach_events set status='skipped',failure_reason=%s,updated_at=now() "
            "where lead_id=%s and channel='sms' and status='planned'",
            (TEXTS_OFF_SKIP_REASON, lead_id),
        )
    pending = conn.execute(
        f"select {REVIEW_COLUMNS} from lead_reviews where lead_id=%s and resolution='retry_texts' "
        "and details->>'retry_pending'='true'",
        (lead_id,),
    ).fetchall()
    retry_rows = (rows if choice == "retry_texts" else []) + list(pending)
    if retry_rows and not lead.get("sms_disabled") and choice != "calls_only" and (
            failed := _failed_text_event(conn, lead_id, retry_rows)):
        # sms_messages links one row per event, so the retry is a new event for the same step.
        conn.execute(
            "insert into outreach_events(lead_id,cadence_step_id,cadence_version_id,channel,"
            "day_offset,scheduled_for,status,attempt_no) values(%s,%s,%s,'sms',%s,now(),'planned',1)",
            (lead_id, failed["cadence_step_id"], failed["cadence_version_id"], failed["day_offset"]),
        )
    if pending:
        conn.execute(
            "update lead_reviews set details=details-'retry_pending' where id=any(%s)",
            ([row["id"] for row in pending],),
        )
    conn.execute(
        "update leads set needs_review=false,review_reason=null,review_resolved_at=now(),"
        "status='in_progress',cadence_state='active',status_reason=%s,status_changed_at=now() "
        "where id=%s",
        (f"review resolved: {CHOICE_LABELS[choice]}"[:500], lead_id),
    )
    return {"restored_steps": restored, "shifted_steps": shifted}


def _close(conn, lead: dict, choice: str) -> None:
    lead_id = str(lead["id"])
    if choice == "front_desk":
        status, reason = "closed_no_response", FRONT_DESK_REASON
    elif choice == "different_person":
        status, reason = "invalid_phone", "Different person: add the new patient as a new row in the Sheet"
    elif choice == "wrong_number":
        status, reason = "invalid_phone", "Wrong number confirmed by staff: add the right number as a new row"
    else:
        status, reason = "invalid_phone", "Phone number changed in the Sheet: add the new number as a new row"
    skip_remaining_planned(conn, lead_id, reason)
    # Steps the review paused stay stopped: nothing may bring them back on this lead.
    conn.execute(
        "update outreach_events set failure_reason=%s,updated_at=now() "
        "where lead_id=%s and status='skipped' and failure_reason=%s",
        (reason[:500], lead_id, PAUSE_SKIP_REASON),
    )
    conn.execute(
        "update leads set needs_review=false,review_reason=null,review_resolved_at=now(),"
        "status=%s,cadence_state='terminated',status_reason=%s,status_changed_at=now() where id=%s",
        (status, reason, lead_id),
    )


LEAD_COLUMNS = (
    "id,practice_id,full_name,phone_e164,status,status_reason,cadence_state,needs_review,"
    "review_reason,review_flagged_at,call_opt_out,sms_opt_out,sms_disabled,is_test"
)


def resolve_review(
    conn, lead_id: str, choice: str, *, note: str | None, actor_id: str, actor_name: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Apply one staff choice to a flagged lead. Any staff member or admin may do this."""
    now = now or datetime.now(UTC)
    lead = conn.execute(f"select {LEAD_COLUMNS} from leads where id=%s for update", (lead_id,)).fetchone()
    if not lead:
        raise ReviewError(404, "lead not found")
    rows = open_reviews(conn, lead_id)
    if not lead["needs_review"]:
        raise ReviewError(409, "This lead has no open review.")
    rows = rows or [_legacy_row(lead)]
    primary = describe(rows[0], lead)
    allowed = {option["choice"] for option in primary["options"]}
    if choice not in CHOICE_LABELS:
        raise ReviewError(422, "Unknown choice.")
    if choice not in allowed:
        raise ReviewError(409, f"“{CHOICE_LABELS[choice]}” is not an option for this review.")
    details = rows[0].get("details") or {}
    if choice == "keep_old_name" and not details.get("new_name"):
        details = _legacy_sheet_name(conn, lead, rows[0])
    note = (note or "").strip()[:500] or None
    result: dict[str, Any] = {}
    remaining = len(rows) - 1 if rows[0].get("id") is not None else 0
    if choice in RESUME_CHOICES and remaining:
        # Only this review is settled; its effect (new name, texts off) applies now, and the lead
        # stays paused for the next one, so no choice can undo another open problem.
        _apply_choice(conn, lead, rows, choice, details)
        # "Try texting again" is kept on the review and honoured when the lead finally resumes
        # (QA round 2: it was lost when another review was still open).
        conn.execute(
            "update lead_reviews set resolved_at=now(),resolved_by=%s,resolved_by_name=%s,"
            "resolution=%s,note=%s,details=details||%s,updated_at=now() where id=%s",
            (actor_id, actor_name[:120], choice, note,
             Jsonb({"retry_pending": True} if choice == "retry_texts" else {}), rows[0]["id"]),
        )
        conn.execute(
            "update leads set review_reason=%s where id=%s",
            (str(rows[1].get("message") or "Needs review")[:500], lead_id),
        )
        result = {"remaining_reviews": remaining}
    elif choice in RESUME_CHOICES:
        _resume_guards(conn, lead, choice)
        close_open_reviews(conn, lead_id, choice, by=actor_id, by_name=actor_name, note=note)
        _apply_choice(conn, lead, rows, choice, details)
        result = _resume(conn, lead, rows, choice, now)
    else:
        close_open_reviews(conn, lead_id, choice, by=actor_id, by_name=actor_name, note=note)
        _close(conn, lead, choice)
    new = conn.execute("select status,cadence_state from leads where id=%s", (lead_id,)).fetchone()
    record_status(
        conn, lead_id, lead["status"], new["status"], "dashboard",
        (f"Review resolved by {actor_name}: {CHOICE_LABELS[choice]}"
         + (f". Note: {note}" if note else ""))[:500],
    )
    enqueue_sheet_update(
        conn, lead_id=lead_id,
        # With reviews left, the Sheet shows the next one ("Needs review: …").
        event_type="review_flagged" if result.get("remaining_reviews") else "review_resolved",
        source_key=f"{lead_id}:{rows[0].get('id')}:{choice}:{now.isoformat()}",
    )
    return {
        "status": "resolved",
        "choice": choice,
        "label": CHOICE_LABELS[choice],
        "lead_status": new["status"],
        "cadence_state": new["cadence_state"],
        **result,
    }


# --- a phone number changed in the Sheet ---------------------------------------------------------


def close_for_phone_change(
    conn, lead: dict, *, new_phone: str, new_name: str | None, now: datetime | None = None,
) -> bool:
    """The Sheet row now holds another number: this lead is over (owner, 2026-10-22).

    Not a review: the old lead closes at once and can never be resumed or restarted (the number it
    calls is no longer the patient's), and staff add the new number as a new row. A booked,
    declined or Do Not Contact lead keeps its outcome; the change is still recorded.
    Returns False when it was already recorded for this number (a later profile sync).
    """
    now = now or datetime.now(UTC)
    lead_id = str(lead["id"])
    old_mask, new_mask = mask_phone(lead["phone_e164"]), mask_phone(new_phone)
    seen = conn.execute(
        "select 1 from lead_reviews where lead_id=%s and code='phone_changed' "
        "and details->>'new_phone'=%s limit 1",
        (lead_id, new_mask),
    ).fetchone()
    if seen:
        return False
    tz, _, _ = _practice_clock(conn, lead_id)
    message = (f"Phone number changed in the Sheet from {old_mask} to {new_mask} on "
               f"{_clinic_date(now, tz)}. Add the new number as a new row.")
    details: dict[str, Any] = {"old_phone": old_mask, "new_phone": new_mask}
    if new_name and new_name.strip() != str(lead.get("full_name") or "").strip():
        details.update(old_name=lead.get("full_name"), new_name=new_name.strip())
    finished = lead["status"] in {"booked", "declined", "do_not_contact"}
    conn.execute(
        "insert into lead_reviews(lead_id,code,message,details,source,resolved_at,resolved_by,"
        "resolved_by_name,resolution) values(%s,'phone_changed',%s,%s,'sheet',now(),'sheet',"
        "'Google Sheet','close_phone_changed')",
        (lead_id, message[:500], Jsonb(details)),
    )
    if finished:
        record_status(conn, lead_id, lead["status"], lead["status"], "n8n_sheet", message)
        return True
    # Any open review is settled by this: nothing is left to decide on this lead.
    close_open_reviews(conn, lead_id, "close_phone_changed", by="sheet", by_name="Google Sheet")
    skip_remaining_planned(conn, lead_id, "phone number changed in the Sheet")
    conn.execute(
        "update outreach_events set failure_reason='phone number changed in the Sheet',updated_at=now() "
        "where lead_id=%s and status='skipped' and failure_reason=%s",
        (lead_id, PAUSE_SKIP_REASON),
    )
    conn.execute(
        "update leads set status='invalid_phone',cadence_state='terminated',needs_review=false,"
        "review_reason=null,review_resolved_at=case when needs_review then now() else review_resolved_at end,"
        "status_reason=%s,status_changed_at=now() where id=%s",
        (message[:500], lead_id),
    )
    record_status(conn, lead_id, lead["status"], "invalid_phone", "n8n_sheet", message)
    return True


PHONE_CHANGED_DETAIL = (
    "The phone number changed in the Google Sheet, so this lead cannot be restarted or resumed on "
    "the old number. Add the new number as a new row in the Sheet."
)


def closed_for_good(conn, lead: dict) -> str | None:
    """Why a lead may never be resumed or restarted, or None.

    Closed because its number (or person) is wrong, or its phone changed in the Sheet. QA
    2026-10-22: a Booked lead whose phone changed kept its status (it is still Booked for staff),
    and the board's New restarted it on the OLD number. The phone change record now blocks that,
    whatever the status.
    """
    # Any phone-change record, however it was settled: an old (pre-048) one closed with Front desk
    # or a board move blocked nothing (QA round 2).
    phone_changed = conn.execute(
        "select 1 from lead_reviews where lead_id=%s and code='phone_changed' limit 1",
        (lead["id"],),
    ).fetchone()
    if phone_changed:
        return PHONE_CHANGED_DETAIL
    if lead.get("status") == "invalid_phone" and lead.get("cadence_state") == "terminated":
        return CLOSED_FOR_GOOD_DETAIL
    return None


CLOSED_FOR_GOOD_DETAIL = (
    "This lead is closed for good (wrong number, different person or phone changed). "
    "Add the patient as a new row in the Google Sheet."
)
OPEN_REVIEW_DETAIL = (
    "This lead has an open review. Choose what happens next with Resolve review."
)
