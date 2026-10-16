from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from dataclasses import dataclass
from urllib.parse import unquote

from fastapi import HTTPException, Request
from fastapi.security import APIKeyHeader

from .config import get_settings

# Documentation only: makes Swagger's Authorize button send the header that
# require_vapi_auth() checks. auto_error=False so it never enforces on its own.
vapi_secret_scheme = APIKeyHeader(
    name="x-vapi-secret",
    auto_error=False,
    description="Paste VAPI_WEBHOOK_SECRET to use Try it out.",
)

@dataclass(frozen=True)
class DashboardActor:
    user_id: str
    email: str
    employee_id: str = ""
    display_name: str = ""
    role: str = "super_admin"
    practice_id: int = 1


def _fresh_timestamp(timestamp: str, *, max_age_seconds: int = 300) -> bool:
    try:
        return abs(int(time.time()) - int(timestamp)) <= max_age_seconds
    except (TypeError, ValueError):
        return False


def require_dashboard_auth(request: Request) -> DashboardActor:
    settings = get_settings()
    expected = settings.dashboard_api_token
    supplied = request.headers.get("x-dashboard-token", "")
    if not expected:
        raise HTTPException(status_code=503, detail="dashboard API is not configured")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid dashboard credentials")
    user_id = request.headers.get("x-dashboard-user-id", "").strip().lower()
    display_name = unquote(request.headers.get("x-dashboard-user-name", "")).strip()
    role = request.headers.get("x-dashboard-user-role", "").strip()
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,31}", user_id)
        or not display_name
        or len(display_name) > 120
        or role not in {"super_admin", "employee"}
    ):
        raise HTTPException(status_code=401, detail="authenticated dashboard user is required")
    return DashboardActor(
        user_id=user_id,
        email=user_id,
        employee_id=user_id,
        display_name=display_name,
        role=role,
    )


async def require_vapi_auth(request: Request) -> None:
    settings = get_settings()
    expected = settings.vapi_webhook_secret
    supplied = request.headers.get("authorization", "")
    token = supplied[7:] if supplied.lower().startswith("bearer ") else ""
    legacy_secret = request.headers.get("x-vapi-secret", "")
    if expected and (
        hmac.compare_digest(token, expected) or hmac.compare_digest(legacy_secret, expected)
    ):
        return
    timestamp = request.headers.get("x-vapi-timestamp", "")
    signature = request.headers.get("x-vapi-signature", "")
    try:
        fresh = _fresh_timestamp(timestamp)
    except ValueError:
        fresh = False
    if settings.vapi_hmac_secret and signature and fresh:
        body = await request.body()
        expected_signature = hmac.new(
            settings.vapi_hmac_secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        if hmac.compare_digest(signature.removeprefix("sha256="), expected_signature):
            return
    if expected:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - malformed JSON remains unauthenticated
            body = {}
        candidates = [body.get("vapi_secret")] if isinstance(body, dict) else []
        message = body.get("message") if isinstance(body, dict) else None
        message = message if isinstance(message, dict) else {}
        for key in ("toolCallList", "toolCalls"):
            for item in message.get(key) or []:
                if not isinstance(item, dict):
                    continue
                function = item.get("function") if isinstance(item.get("function"), dict) else {}
                arguments = item.get("arguments") or item.get("parameters") or function.get("arguments")
                if isinstance(arguments, str):
                    try:
                        import json

                        arguments = json.loads(arguments)
                    except (TypeError, ValueError):
                        arguments = {}
                if isinstance(arguments, dict):
                    candidates.append(arguments.get("vapi_secret"))
        if any(
            isinstance(candidate, str) and hmac.compare_digest(candidate, expected)
            for candidate in candidates
        ):
            return
    raise HTTPException(status_code=401, detail="invalid Vapi credentials")


async def require_twilio_auth(request: Request, form: dict[str, str]) -> None:
    """Validate Twilio's HMAC-SHA1 request signature."""
    settings = get_settings()
    tokens = settings.twilio_auth_tokens()  # live and test account
    signature = request.headers.get("x-twilio-signature", "")
    if settings.mode("twilio") == "mock" and signature == "mock-valid":
        return
    if not tokens or not signature:
        raise HTTPException(status_code=401, detail="missing Twilio signature")
    if settings.public_base_url:
        public_url = f"{settings.public_base_url.rstrip('/')}{request.url.path}"
        if request.url.query:
            public_url = f"{public_url}?{request.url.query}"
    else:
        public_url = str(request.url)
    data = public_url + "".join(f"{key}{form[key]}" for key in sorted(form))
    for token in tokens:
        digest = base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()
        if hmac.compare_digest(digest, signature):
            return
    raise HTTPException(status_code=401, detail="invalid Twilio signature")
