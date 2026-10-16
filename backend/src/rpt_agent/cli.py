from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from .agent.terminal import run_terminal
from .config import get_settings
from .db import transaction
from .observability import WorkflowTrace, configure_logging
from .worker import format_phone, materialize_cadence, run_tick

ROOT = Path(__file__).resolve().parents[2]
TEST_LEAD_RESET_SQL = ROOT / "supabase" / "dev" / "reset_test_lead_by_name.sql"


def migrate() -> None:
    trace = WorkflowTrace("database_migration", "cli")
    with transaction() as conn:
        conn.execute(
            "create table if not exists public.schema_migrations(version text primary key,applied_at timestamptz not null default now())"
        )
        applied = {row["version"] for row in conn.execute("select version from public.schema_migrations")}
        for path in sorted((ROOT / "supabase" / "migrations").glob("*.sql")):
            if path.name in applied:
                trace.log("migration_skipped", migration=path.name)
                continue
            trace.log("migration_started", migration=path.name)
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("insert into public.schema_migrations(version) values(%s)", (path.name,))
            trace.log("migration_completed", migration=path.name)
    trace.complete()


def verify() -> None:
    with transaction() as conn:
        rows = conn.execute("select version,applied_at from public.schema_migrations order by version").fetchall()
    print(json.dumps(rows, indent=2, default=str))


def seed() -> None:
    trace = WorkflowTrace("database_seed", "cli")
    with transaction() as conn:
        conn.execute((ROOT / "supabase" / "seed.sql").read_text(encoding="utf-8"))
    trace.complete()


def create_test_lead(args: argparse.Namespace) -> None:
    settings = get_settings()
    if not settings.testing_mode:
        raise RuntimeError("set TESTING_MODE=true before creating an accelerated synthetic lead")
    phone = format_phone(args.phone)
    if not phone:
        raise ValueError("phone must be a valid E.164 or 10-digit North American number")
    if not args.consent_reference.strip():
        raise ValueError("--consent-reference is required before any test call")
    dob = date.fromisoformat(args.dob)
    test_run_id = uuid4()
    first_name = args.first_name.strip()
    last_name = args.last_name.strip()
    if not first_name or not last_name:
        raise ValueError("first and last name are required")
    with transaction() as conn:
        practice = conn.execute("select id from practices where slug='rausch-pt'").fetchone()
        if not practice:
            raise RuntimeError("run `rpt seed` first")
        active = conn.execute(
            "select oe.id from outreach_events oe join leads l on l.id=oe.lead_id "
            "where l.practice_id=%s and l.is_test is true and l.source_system='synthetic_test' "
            "and lower(btrim(coalesce(l.first_name,'')))=lower(btrim(%s)) "
            "and lower(btrim(coalesce(l.last_name,'')))=lower(btrim(%s)) "
            "and oe.status in ('in_flight','attempted') for update of oe",
            (practice["id"], first_name, last_name),
        ).fetchall()
        if active:
            raise RuntimeError(
                "cannot replace this synthetic lead while a call is in flight or awaiting settlement"
            )
        reset = conn.execute(
            TEST_LEAD_RESET_SQL.read_text(encoding="utf-8"),
            {
                "practice_slug": "rausch-pt",
                "first_name": first_name,
                "last_name": last_name,
            },
        ).fetchone()
        lead = conn.execute(
            "insert into leads(practice_id,source_system,external_referral_id,is_test,test_run_id,"
            "first_name,last_name,full_name,phone_e164,phone_original,date_of_birth,timezone,line_type,"
            "consent_captured_at,consent_source,consent_reference,consent_text_version,status,cadence_state) "
            "values(%s,'synthetic_test',%s,true,%s,%s,%s,%s,%s,%s,%s,'America/Los_Angeles','mobile',"
            "now(),'verbal_recorded',%s,'synthetic-test-v1','new','pending') returning id",
            (
                practice["id"], f"test-{test_run_id}", test_run_id, first_name,
                last_name, f"{first_name} {last_name}",
                phone, args.phone, dob, args.consent_reference.strip(),
            ),
        ).fetchone()
        event_count = materialize_cadence(
            conn, str(lead["id"]), practice["id"], datetime.now(UTC).date()
        )
        schedule = conn.execute(
            "select day_offset,channel,scheduled_for from outreach_events where lead_id=%s "
            "order by scheduled_for",
            (lead["id"],),
        ).fetchall()
    print(json.dumps({
        "lead_id": str(lead["id"]),
        "test_run_id": str(test_run_id),
        "replaced_test_leads": int(reset["deleted_leads"]),
        "event_count": event_count,
        "test_day_minutes": settings.testing_day_minutes,
        "schedule": schedule,
    }, indent=2, default=str))


def sheet_check() -> None:
    """Read the Google Sheet and show what the next poll would do. Changes nothing."""
    from .services.google_sheet import GoogleSheetBackend, parse_grid
    from .services.sheet_direct import preview

    settings = get_settings()
    backend = GoogleSheetBackend(settings)
    grid = parse_grid(backend.read_values(), settings.google_sheet_header_row)
    print(json.dumps({"tab": settings.google_sheet_tab, **preview(grid, settings.sheet_stuck_seconds)},
                     indent=2))


def sheet_archive(args) -> None:
    """Show (or with --apply, move) the rows the nightly archive would move now."""
    from .services import sheet_direct
    from .services.google_sheet import GoogleSheetBackend, parse_grid

    settings = get_settings()
    backend = GoogleSheetBackend(settings)
    grid = parse_grid(backend.read_values(), settings.google_sheet_header_row)
    days = settings.sheet_archive_days if args.days is None else args.days
    rows = sheet_direct.archive_candidates(grid, days)
    out: dict[str, object] = {"days": days, "rows": [r.number for r in rows]}
    if args.apply:
        out["archived"] = sheet_direct.archive(
            backend, grid, days, settings.google_sheet_archive_tab,
            WorkflowTrace("sheet_archive", "cli"))
    print(json.dumps(out, indent=2))


def main() -> None:
    configure_logging("cli")
    parser = argparse.ArgumentParser(prog="rpt")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("migrate", "verify", "seed", "tick", "sheet-check"):
        subparsers.add_parser(command)
    archive = subparsers.add_parser("sheet-archive",
                                    help="list (or --apply: move) finished Sheet rows to the archive")
    archive.add_argument("--apply", action="store_true")
    archive.add_argument("--days", type=int, default=None)
    test_lead = subparsers.add_parser("test-lead", help="create a consented synthetic lead")
    test_lead.add_argument("--phone", required=True)
    test_lead.add_argument("--first-name", default="Synthetic")
    test_lead.add_argument("--last-name", default="Patient")
    test_lead.add_argument("--dob", default="1990-01-01")
    test_lead.add_argument("--consent-reference", required=True)
    agent = subparsers.add_parser("agent", help="open the lead-scoped terminal assistant")
    agent.add_argument("--api-url")
    agent.add_argument("--lead", action="append", default=[])
    agent.add_argument("--user-id", default="terminal-agent")
    agent.add_argument("--name", default="Terminal Agent")
    args = parser.parse_args()
    commands = {
        "migrate": migrate,
        "verify": verify,
        "seed": seed,
        "tick": lambda: print(json.dumps(run_tick(), indent=2)),
        "test-lead": lambda: create_test_lead(args),
        "sheet-check": sheet_check,
        "sheet-archive": lambda: sheet_archive(args),
        "agent": lambda: run_terminal(
            api_url=args.api_url,
            initial_leads=args.lead,
            user_id=args.user_id,
            display_name=args.name,
        ),
    }
    commands[args.command]()


if __name__ == "__main__":
    main()
