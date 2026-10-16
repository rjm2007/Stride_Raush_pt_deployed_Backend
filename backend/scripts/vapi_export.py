"""Back up the live outreach voice agent into config/ (read-only against Vapi).

Saves the assistant's prompt and settings to config/vapi_assistant.json + config/vapi_assistant_prompt.md
and its tools to config/vapi_tools.json. Secret values (tool header values, server secrets) are replaced
with placeholders, so the files are safe to commit.

    uv run --frozen python scripts/vapi_export.py            # VAPI_ASSISTANT_ID from .env
    uv run --frozen python scripts/vapi_export.py <assistant-id>

Nothing is changed in Vapi. Edit the agent in the Vapi dashboard, then re-run this to update the backup.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx

from rpt_agent.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
SECRET = "<secret: set in Vapi, same value as VAPI_WEBHOOK_SECRET>"
# Fields that describe the agent; ids, org and timestamps are left out on purpose.
ASSISTANT_FIELDS = (
    "name", "firstMessage", "firstMessageMode", "voicemailMessage", "endCallMessage", "model",
    "voice", "transcriber", "server", "serverMessages", "analysisPlan", "artifactPlan",
    "startSpeakingPlan", "stopSpeakingPlan", "silenceTimeoutSeconds", "maxDurationSeconds",
    "backgroundSound", "voicemailDetection", "endCallPhrases", "toolIds",
)


def _mask(value: Any) -> Any:
    """Replace every header value / secret in a nested Vapi object."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in {"headers"} and isinstance(item, dict):
                out[key] = {name: SECRET for name in item}
            elif key in {"secret", "token", "apiKey", "password"}:
                out[key] = SECRET
            else:
                out[key] = _mask(item)
        return out
    if isinstance(value, list):
        return [_mask(item) for item in value]
    return value


def main() -> None:
    settings = get_settings()
    assistant_id = sys.argv[1] if len(sys.argv) > 1 else settings.vapi_assistant_id
    if not settings.vapi_api_key or not assistant_id:
        raise SystemExit("VAPI_API_KEY and an assistant id (VAPI_ASSISTANT_ID or argument) are required")
    headers = {"Authorization": f"Bearer {settings.vapi_api_key}"}
    with httpx.Client(base_url=settings.vapi_base_url, headers=headers, timeout=60) as client:
        response = client.get(f"/assistant/{assistant_id}")
        response.raise_for_status()
        assistant = response.json()
        tools = []
        for tool_id in assistant.get("model", {}).get("toolIds") or assistant.get("toolIds") or []:
            tool = client.get(f"/tool/{tool_id}")
            tool.raise_for_status()
            data = tool.json()
            tools.append(_mask({key: data[key] for key in data
                                if key not in {"orgId", "createdAt", "updatedAt"}}))
    kept = {key: assistant[key] for key in ASSISTANT_FIELDS if key in assistant}
    kept = _mask(kept)
    prompt = "\n\n".join(
        message.get("content", "")
        for message in (kept.get("model") or {}).get("messages", [])
        if message.get("role") == "system"
    )
    config = ROOT / "config"
    (config / "vapi_assistant.json").write_text(
        json.dumps({"id": assistant_id, **kept}, indent=2) + "\n", encoding="utf-8")
    (config / "vapi_assistant_prompt.md").write_text(prompt.rstrip() + "\n", encoding="utf-8")
    (config / "vapi_tools.json").write_text(json.dumps(tools, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"assistant": assistant_id, "tools": [t.get("name") or t.get("function", {}).get("name")
                                                           for t in tools]}))


if __name__ == "__main__":
    main()
