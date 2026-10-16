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
| `Lead Status` | backend | | the dashboard column: New / In cadence / Paused / Needs Review / Booked / Do not outreach / Closed |
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

`Already booked` (no call): the same phone + name + birthday + case was marked Booked in the last 30 days.
A different case (booked for Ortho, referred again for Pelvic) starts a new lead.

## When a row is missing

If the backend has an update for a lead whose row is gone (deleted, or Lead ID cleared), it tries 3 times
(about 1 and 2 minutes apart, `SHEET_MAX_ATTEMPTS`) and then gives that update up. The lead itself is not
affected; the dashboard stays correct.

## Edits to an existing row

Name, Phone Number, Email, Date Of Birth, Location and Case edits on a linked row are synced every 5
minutes. A changed **name or phone number** is not applied silently: the lead is flagged for review
(`Phone number changed; needs review`, `Name changed; needs review`, …) and staff decide on the dashboard.

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
