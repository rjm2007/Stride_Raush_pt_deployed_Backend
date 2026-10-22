# The Google Sheet (production)

The Sheet is the only way leads come in. The `sheet-worker` reads it every 30 s with a Google service
account and writes results back into it. Code: `src/rpt_agent/services/google_sheet.py` (access, column map)
and `src/rpt_agent/services/sheet_direct.py` (rules and labels).

## Layout

- Tab name: `Sheet1` (`GOOGLE_SHEET_TAB`). Row 1 is free (title). **Row 2 holds the column names**
  (`GOOGLE_SHEET_HEADER_ROW=2`). Data starts on row 3.
- Columns are found by their name in row 2, so their order does not matter, but the names must match
  exactly (case and spaces included). A missing required column stops the sync and the heartbeat says
  which one.
- Share the Sheet with the service account's email as **Editor**.

| Column (row 2) | Who fills it | Required | Notes |
| --- | --- | --- | --- |
| `Name` | staff | yes | first and last name |
| `Phone Number` | staff | yes | 10 digits = US (+1); 12 digits starting 91 = India (+91, team tests) |
| `Email` | staff | no | |
| `Date Of Birth` | staff | for Start | DD/MM/YYYY, a date cell, or "Mar 5, 1990"; day first when ambiguous |
| `Location` | staff | for Start | clinic name, e.g. Laguna Niguel |
| `Case` | staff | for Start | free text, e.g. Ortho, Pelvic ("Ortho" = "Physical Therapy" by case aliases) |
| `Action` | staff | yes | dropdown: `Start cadence`, `Restart cadence`, `Do Not Contact`, `Booked` |
| `Lead Status` | backend | | the dashboard column: New / In cadence / Paused / Needs Review / Booked / Do not outreach / Closed. If the cell has a dropdown, it must list all seven, or Google marks the value as invalid. Closed = 14 days done with no booking, patient not interested, or wrong number |
| `Cadence Day` | backend | | |
| `Outcome Status` | backend | yes | result of the last command (see below). Clear it to run a command again |
| `Call Outcome` | backend | | |
| `Message Outcome` | backend | | |
| `Email Outcome` | backend | | |
| `Transcript Link` | backend | | link to the lead's calls in the dashboard |
| `Action Request ID` | backend | yes | do not edit |
| `Action Started At` | backend | yes | do not edit |
| `Lead ID` | backend | yes | do not edit; links the row to the lead |

Required for the sync to run at all: Name, Phone Number, Action, Outcome Status, Action Request ID,
Action Started At, Lead ID. Optional columns that are missing are simply not written.

## Commands (Action column)

A row runs when its Action is one of the four commands and its Outcome Status says it still needs doing
(empty, or not a final result). The row must stay unchanged for 60 s first (`SHEET_SETTLE_SECONDS`), so a
half-typed row never starts early. At most 50 commands run per poll; a pasted block is worked through over
several polls.

| Action | What happens | Outcome Status written |
| --- | --- | --- |
| `Start cadence` | creates the lead and plans the 14-day cadence (Day 0 call + text first) | `Cadence started` (or `Already in Cadence`, `Already booked`, `Error: …`) |
| `Restart cadence` | starts the lead again from Day 0 (refused within 10 min of the last restart) | `Cadence restarted` |
| `Do Not Contact` | stops all calls and texts; the phone number is blocked | `Do Not Contact applied` |
| `Booked` | the clinic booked the patient: outreach stops, the dashboard shows Booked | `Booked` |

While a command runs the cell shows `Processing: <command>`, then `Retrying n/3: …` if the database is
slow. A row stuck in Processing for 2 minutes is retried with the same request id, so it never runs twice.

**Booked is only set by staff** (this Sheet, or moving the card to Booked on the dashboard). There is no
Stride link, so no appointment date, clinician or "who booked" is recorded. The voice agent never marks a
lead booked: it sends the booking link, transfers to the front desk, or books a callback, and the cadence
keeps running after each of those until staff mark Booked (or Do Not Contact, or the patient declines).
After the last cadence step with no booking the lead moves to Closed.

`Number blocked; needs review` (no call): the phone number is on the blocked list (the patient once asked
not to be contacted). The lead is created in Needs Attention; an admin unblocks it on the lead's page
(continue or start over). A number whose lead was deleted is unblocked from Administration → Blocked numbers.

`Already booked` (no call): the same phone + name + birthday + case was marked Booked in the last 30 days.
A different case (booked for Ortho, referred again for Pelvic) starts a new lead.

## When a row is missing

If the backend has an update for a lead whose row is gone (deleted, or Lead ID cleared), it tries 3 times
(about 1 and 2 minutes apart, `SHEET_MAX_ATTEMPTS`) and then gives that update up. The lead itself is not
affected; the dashboard stays correct.

## Edits to an existing row

Name, Phone Number, Email, Date Of Birth, Location and Case edits on a linked row are synced every 5
minutes. Email, Date Of Birth, Location and Case are applied. Name and phone are not applied silently:

- **Phone Number changed** (alone or with the name): the old lead is **closed at once** and can never be
  resumed or restarted (Lead Status `Closed`, Outcome Status `Phone changed: add a new row`, Action set to
  `Start cadence`). Add the new number as a **new row**. The dashboard keeps the reason ("Phone number
  changed in the Sheet from …8847 to …1234 on Oct 21, 2026").
- **Name changed**: the lead pauses for review (`Needs review: name changed`). On the dashboard staff
  choose: use the new name, keep the old name (that exact Sheet name is then remembered and never
  flagged again), or different person (lead closed; add a new row).

## Review texts (Outcome Status)

When a lead needs review the Outcome Status says why; when staff resolve it on the dashboard it says what
was chosen. No new columns: only the words in the existing cells. Lead Status keeps its seven values.

| Outcome Status | When |
| --- | --- |
| `Needs review: name changed` | Name edited in the Sheet |
| `Needs review: text failed (landline)` / `Needs review: text failed` | a cadence text was not delivered (Twilio 30006/21614 = landline) |
| `Needs review: wrong number` | the person on the call said it is the wrong number or not the patient |
| `Needs review: call result unclear` | call answered with no usable outcome |
| `Needs review: not confirmed` | a call or text whose result never came back (never retried automatically) |
| `Number blocked; needs review` | the number is on the blocked list |
| `Resolved: new name used` / `Resolved: old name kept` | name review resolved, cadence continues |
| `Resolved: calls only` | texts off for this lead, calls continue; Message Outcome shows `Calls only (texts off)` |
| `Resolved: texting again` / `Resolved: number confirmed` / `Resolved: continued` | cadence continues |
| `Closed: handled by front desk` | outreach stopped, the front desk takes over |
| `Closed: wrong number` / `Closed: different person, add a new row` | lead closed for good |
| `Phone changed: add a new row` | phone edited in the Sheet (see above) |

A row in review (Outcome Status `Needs review: …` or `Number blocked; needs review`, 2026-10-23):

- `Booked` and `Do Not Contact` typed in Action run as on any row. The lead is booked / its number
  blocked, and the review closes ("booked" / "do_not_contact", by Google Sheet).
- `Restart cadence` waits for the review. The row says `<review text>; resolve it on the dashboard
  first, then the restart runs` and Action keeps the typed text. Once the review is resolved the Restart
  runs (10-minute cooldown and the usual refusals still apply). If the dashboard ends the lead instead
  (front desk, wrong number close, board Booked, Do not contact, phone change), the Restart is dropped:
  Outcome Status reads `<result>; the Restart in Action was not run` (a final `Booked` / `Do Not
  Contact applied` stays as is) and Action is reset. Clearing Action removes the waiting words on the
  next poll.
- `Start cadence` never runs on a linked row (it is the value the system writes after a resolution).
- The backend never leaves `Restart cadence` next to a review text it writes (on a flag, or a Restart
  that ends in `Number blocked; needs review`, Action becomes `Start cadence`), so a Restart next to a
  review text was typed by staff.
- Older texts that do not start this way (e.g. `Phone number changed; needs review`) still block every
  command.

With a `Resolved: …` / `Closed: …` text the backend also sets Action to `Start cadence`, so a stale
`Restart cadence` or `Booked` never runs again by itself; picking a command in Action afterwards runs it
once. These texts are written once, when the review is flagged or resolved, and Action is never written
over a command typed in the row that has not run yet (nor over a waiting Restart); later updates leave
the cell alone. A lead whose phone changed can never be restarted on the old number,
even if it was Booked or the old number is typed back.

## To run a command again

Clear the Outcome Status cell (leave Lead ID alone). For a Start that failed before a Lead ID was written,
clearing Outcome Status is enough: if the lead was in fact created, its Lead ID is recovered instead of
starting a second lead.

## Nightly archive (off)

`SHEET_ARCHIVE_ENABLED=true` moves rows of finished leads (booked, do not contact, declined, closed, wrong
number) untouched for 30 days to an `Archive` tab at 3 AM Pacific. Off until the clinic agrees.
`docker compose run --rm sheet-worker rpt sheet-archive` shows what would move.

## Checks

- `docker compose run --rm sheet-worker rpt sheet-check` — reads the Sheet and shows what the next poll
  would do. Changes nothing.
- The sheet-worker writes a heartbeat to `service_heartbeats` (service `sheet-worker`) every poll, with
  `ok=false` and the reason when the layout is wrong.
