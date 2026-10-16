"""Small compatibility facade over the provider-specific service files."""

from __future__ import annotations

from typing import Any

import httpx

from .config import Settings, get_settings
from .observability import WorkflowTrace
from .services.provider_http import ProviderError
from .services.twilio_service import TwilioService
from .services.vapi_service import VapiService


class ProviderClients:
    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None):
        self.settings = settings or get_settings()
        shared_client = client or httpx.Client(timeout=self.settings.request_timeout_seconds)
        options = {"audit_enabled": client is None}
        self.vapi = VapiService(self.settings, shared_client, **options)
        self.twilio = TwilioService(self.settings, shared_client, **options)

    def create_vapi_call(self, trace: WorkflowTrace, payload: dict[str, Any]) -> str:
        return self.vapi.create_call(trace, payload)

    def send_sms(self, trace: WorkflowTrace, to: str, body: str) -> str:
        return self.twilio.send_sms(trace, to, body)


__all__ = ["ProviderClients", "ProviderError"]
