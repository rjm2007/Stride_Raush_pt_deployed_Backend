"""Test the live outreach voice agent case by case, by text chat. No phone call is placed.

Each case plays a scripted patient against the agent through the Vapi Chat API (the same assistant,
prompt and tools as a real call), then checks what the agent said and which outcome it reported.

    python scripts/test_agent_chat.py              # list the cases
    python scripts/test_agent_chat.py 3            # run case 3
    python scripts/test_agent_chat.py 3 7 9        # run several
    python scripts/test_agent_chat.py all          # run every case

Needs VAPI_API_KEY in the environment or in an env file (`--env ../.env`, default: `.env`, then `../.env`).
VAPI_ASSISTANT_ID defaults to the outreach agent. Standard library only.

The agent's lead-status tool really reaches the backend, with a dummy lead id (all zeros): the backend
finds no lead, so nothing changes. Callback cases depend on the current California time and are
checked against it. Prints no secret.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

CLINIC = ZoneInfo("America/Los_Angeles")
DEFAULT_ASSISTANT = "540ddb07-711e-4060-8753-f82d848b9a25"
DUMMY_LEAD = "00000000-0000-0000-0000-000000000000"
# Must match practice_settings (clinic, 2026-10-19).
HOLIDAYS = {"2026-11-26", "2026-12-24", "2026-12-25", "2026-12-31", "2027-01-01", "2027-05-31",
            "2027-07-04", "2027-09-06", "2027-11-25", "2027-12-24", "2027-12-25", "2027-12-31"}
START = ["Yes, this is him.", "Sure, go ahead."]


def open_now(now: datetime) -> bool:
    """Callback hours: Mon-Fri 8 AM-7 PM, Sat 8 AM-1:30 PM, no Sunday or holiday."""
    if now.date().isoformat() in HOLIDAYS or now.weekday() == 6:
        return False
    close = 13.5 if now.weekday() == 5 else 19
    return 8 <= now.hour + now.minute / 60 < close


@dataclass
class Case:
    title: str
    patient: list[str]
    status: str | None = None          # the outcome the agent must report (None = must report nothing)
    says: list[str] = field(default_factory=list)       # regexes the agent must say (any turn)
    never_says: list[str] = field(default_factory=list)
    last_says: str | None = None       # regex the agent's final words must match
    note: str = ""


def cases(now: datetime) -> list[Case]:
    in_ten = now + timedelta(minutes=10)
    ten_ok = open_now(now) and open_now(in_ten)
    goodbye = r"Goodbye!?\s*$"
    return [
        Case("Booking link, then 'anything else?' → no", START + ["Text me the link.", "Yes.", "No, that's all."],
             status="booking_link", says=[r"anything else I can help you with"], last_says=goodbye),
        Case("Link, then a clinic question, then 'connect me' (keeps the link)",
             START + ["Text me the link.", "Yes.", "Actually, do you take my insurance?", "Yes please."],
             status="booking_link_and_transfer", says=[r"anything else", r"front desk"]),
        Case("Link and a person in one go", START + ["Send me the link and also connect me to someone now."],
             status="booking_link_and_transfer"),
        Case("Clinic question: no, no, then yes",
             START + ["Do you take Blue Shield insurance?", "No, just tell me.", "No. Just answer my question.",
                      "Okay fine, connect me."],
             status="transferred_human", says=[r"not able to answer", r"booking link"]),
        Case("Clinic question: no to everything",
             START + ["How much does the evaluation cost?", "No.", "No.", "No thanks."],
             status="declined", says=[r"not able to answer"], last_says=goodbye),
        Case("Callback this Saturday at 10 AM (Saturday is open)",
             START + ["Can you call me back this Saturday at ten in the morning?", "Yes.", "No, that's all."],
             status="callback_scheduled", says=[r"Saturday", r"anything else"], last_says=goodbye),
        Case("Callback Saturday at 3 PM (Saturday closes 1:30)",
             START + ["Call me back this Saturday at three in the afternoon."],
             status=None, says=[r"one thirty"]),
        Case("Callback on Sunday", START + ["Call me back on Sunday at noon."],
             status=None, says=[r"Sunday", r"Monday", r"eight in the morning"]),
        Case("Callback on Thanksgiving (Nov 26)",
             START + ["Call me back on November twenty-sixth at ten in the morning."],
             status=None, says=[r"Thanksgiving|closed"], never_says=[r"we shall reach out to you on Thursday"]),
        Case("Only free in the evening", START + ["I'm only free in the evenings, call me then."],
             status=None, says=[r"seven in the evening", r"six thirty"]),
        Case("Callback today at 7:30 PM (after closing)",
             START + ["Can you call me today at seven thirty in the evening?"], status=None,
             says=[r"seven in the evening|one thirty|Sunday|closed|eight in the morning"],
             note="7:30 PM is always outside hours"),
        Case("Callback in ten minutes", START + ["Can you call me back in ten minutes?", "Yes.", "No thanks."],
             status="callback_scheduled",
             says=[r"in ten minutes"] if ten_ok else [r"eight in the morning|earliest"],
             note=("inside hours now: must accept ten minutes" if ten_ok
                   else "outside hours now: must offer the next opening instead")),
        Case("Not interested", START[:1] + ["Not interested."], status="declined", last_says=goodbye),
        Case("Wrong person", ["No, you have the wrong number."], status="wrong_person", last_says=goodbye),
        Case("Clinic hours question after the link",
             START + ["Text me the link.", "Yes.", "What are your hours on Saturday?", "No, that's it."],
             status="booking_link", says=[r"one thirty", r"anything else"], last_says=goodbye),
    ]


def load_env(path: str | None) -> None:
    for candidate in [path] if path else [".env", "../.env"]:
        if candidate and Path(candidate).is_file():
            for line in Path(candidate).read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    name, value = line.split("=", 1)
                    os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))
            return


def chat(key: str, assistant: str, text: str, previous: str | None) -> dict:
    body = {"assistantId": assistant, "input": text, "assistantOverrides": {"variableValues": {
        "Patient_name": "Alex Tester", "lead_id": DUMMY_LEAD, "call_attempt": "1"}}}
    if previous:
        body["previousChatId"] = previous
    for attempt in range(5):
        try:
            request = urllib.request.Request(
                "https://api.vapi.ai/chat", method="POST", data=json.dumps(body).encode(),
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                         "User-Agent": "rpt-agent-test/1"})
            return json.load(urllib.request.urlopen(request, timeout=120))
        except Exception as exc:  # Vapi has brief 5xx/timeouts; retry
            if attempt == 4:
                raise SystemExit(f"Vapi chat failed: {exc}") from exc
            time.sleep(3 + attempt * 2)
    return {}


def run(case: Case, number: int, key: str, assistant: str) -> bool:
    print(f"\n=== Case {number}: {case.title}" + (f"  ({case.note})" if case.note else ""))
    previous, said, statuses = None, [], []
    for line in case.patient:
        reply = chat(key, assistant, line, previous)
        previous = reply.get("id")
        print(f"  Patient: {line}")
        for message in reply.get("output", []):
            for call in message.get("tool_calls") or []:
                name = call["function"]["name"]
                try:
                    status = json.loads(call["function"].get("arguments") or "{}").get("status")
                except ValueError:
                    status = None
                if status:
                    statuses.append(status)
                print(f"    [tool {name}{' → ' + status if status else ''}]")
            if message.get("role") == "assistant" and message.get("content"):
                said.append(message["content"])
                print(f"  Agent:   {message['content']}")
    text = "\n".join(said)
    problems = []
    if case.status and case.status not in statuses:
        problems.append(f"expected outcome {case.status}, got {statuses or 'none'}")
    if case.status is None and statuses:
        problems.append(f"expected no outcome yet, got {statuses}")
    problems += [f"never said /{p}/" for p in case.says if not re.search(p, text, re.IGNORECASE)]
    problems += [f"should not say /{p}/" for p in case.never_says if re.search(p, text, re.IGNORECASE)]
    if case.last_says and not (said and re.search(case.last_says, said[-1].strip(), re.IGNORECASE)):
        problems.append(f"last words should match /{case.last_says}/")
    print("  RESULT: " + ("PASS" if not problems else "FAIL — " + "; ".join(problems)))
    return not problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("which", nargs="*", help="case numbers, or 'all'")
    parser.add_argument("--env", help="env file with VAPI_API_KEY")
    args = parser.parse_args()
    now = datetime.now(CLINIC)
    all_cases = cases(now)
    if not args.which:
        print(f"California time now: {now:%A %I:%M %p}. Cases:")
        for number, case in enumerate(all_cases, 1):
            print(f"  {number:>2}. {case.title}")
        print("\nRun: python scripts/test_agent_chat.py <number> [...] | all")
        return
    load_env(args.env)
    key = os.environ.get("VAPI_API_KEY")
    if not key:
        raise SystemExit("VAPI_API_KEY is not set (use --env path/to/.env)")
    assistant = os.environ.get("VAPI_ASSISTANT_ID") or DEFAULT_ASSISTANT
    numbers = range(1, len(all_cases) + 1) if args.which == ["all"] else [int(n) for n in args.which]
    print(f"California time now: {now:%A %I:%M %p}  ·  assistant …{assistant[-6:]}")
    results = {n: run(all_cases[n - 1], n, key, assistant) for n in numbers}
    passed = sum(results.values())
    print(f"\n{passed}/{len(results)} passed" + ("" if passed == len(results) else
          "  · failed: " + ", ".join(str(n) for n, ok in results.items() if not ok)))
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
