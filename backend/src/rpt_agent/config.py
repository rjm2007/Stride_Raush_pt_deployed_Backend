from functools import cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    log_dir: Path = Path("logs")
    supabase_db_url: str = ""
    provider_mode: str = "mock"
    vapi_mode: str | None = None
    twilio_mode: str | None = None
    mock_base_url: str = "http://localhost:9000"
    api_base_url: str = "http://localhost:8000"
    public_base_url: str = ""
    dashboard_api_token: str = ""
    assistant_enabled: bool = False
    assistant_requests_per_minute: int = Field(default=10, ge=1, le=60)
    langsmith_tracing: bool = False
    langchain_tracing_v2: bool = False
    # Any OpenAI-compatible chat API; the base URL and model are settings so a provider
    # change needs no code change.
    openai_api_key: str = ""
    assistant_base_url: str = "https://api.openai.com/v1"
    assistant_model: str = "gpt-5.6-luna"
    assistant_phi_approved: bool = False
    assistant_phi_approval_reference: str = ""
    dashboard_public_url: str = ""
    # The practice the Google Sheet belongs to (practices.slug).
    practice_slug: str = "rausch-pt"
    # The Google Sheet is the only way leads come in. The sheet-worker reads it with a Google
    # service account (commands, profile edits) and writes results straight into it.
    # False keeps the sheet-worker idle (nothing read or written).
    sheet_sync_enabled: bool = False
    sheet_sync_poll_seconds: int = Field(default=30, ge=1, le=3600)
    sheet_sync_batch_size: int = Field(default=20, ge=1, le=100)
    google_sheet_credentials_file: str = "/run/secrets/google-sheet-sa.json"
    google_sheet_id: str = ""
    google_sheet_tab: str = "Sheet1"
    google_sheet_header_row: int = Field(default=2, ge=1, le=20)
    # A row left "Processing"/"Retrying" this long (worker stopped mid-command) is retried
    # with the same Action Request ID, which replays the stored result.
    sheet_stuck_seconds: int = Field(default=120, ge=30, le=3600)
    # Most polls read only five narrow columns; the profile-edit check needs every column and
    # runs on a full read this often.
    sheet_full_read_seconds: int = Field(default=300, ge=30, le=86400)
    # A command row runs only once its cells stayed unchanged this long (staff still typing).
    sheet_settle_seconds: int = Field(default=60, ge=0, le=3600)
    # Commands started per poll; the rest of a big pasted block waits for the next polls.
    sheet_max_commands_per_poll: int = Field(default=50, ge=1, le=1000)
    # Tries for one Sheet update (e.g. its row was deleted) before it is given up as dead:
    # the first try plus two retries, about 1 and 2 minutes apart.
    sheet_max_attempts: int = Field(default=3, ge=1, le=20)
    # Nightly archive: rows of finished leads (booked, do not contact, declined, closed, wrong
    # number, or cadence over) untouched for SHEET_ARCHIVE_DAYS move to the archive tab at
    # SHEET_ARCHIVE_HOUR (Pacific). Off until the clinic agrees.
    sheet_archive_enabled: bool = False
    sheet_archive_days: int = Field(default=30, ge=1, le=3650)
    sheet_archive_hour: int = Field(default=3, ge=0, le=23)
    google_sheet_archive_tab: str = "Archive"
    vapi_base_url: str = "https://api.vapi.ai"
    vapi_api_key: str = ""
    vapi_assistant_id: str = ""
    vapi_phone_number_id: str = ""
    vapi_webhook_secret: str = "local-vapi-secret"
    vapi_hmac_secret: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = "+15550000001"
    twilio_base_url: str = "https://api.twilio.com"
    # HMAC key that turns phone numbers into stable, non-reversible labels in the test usage
    # report (scripts/generate_test_usage_report.py), so the report never shows a full number.
    phone_fingerprint_secret: str = Field(default="local-fingerprint-secret", min_length=8)
    worker_poll_seconds: int = 30
    # Master stop for anything that reaches a patient. Defaults on so a missing
    # variable can never silence outreach by accident; set false to suspend all
    # calls and SMS while leaving the dashboard readable.
    outbound_enabled: bool = True
    # TESTING_MODE=true: every lead the Sheet creates while it is on is a test lead: each cadence
    # day lasts TESTING_DAY_MINUTES (one minute) and calling hours and daily limits are ignored, so
    # the whole 14-day flow runs in about 15 minutes. false = normal production. Leads keep the mode
    # they were created in; delete the test leads before real patients come in.
    testing_mode: bool = False
    testing_day_minutes: int = Field(default=1, ge=1, le=1440)
    # Test phone numbers, used for every call and text while TESTING_MODE is on (when set). With
    # TESTING_MODE off the live TWILIO_* / VAPI_PHONE_NUMBER_ID (and the database's practice
    # settings) are used as always.
    test_twilio_account_sid: str = ""
    test_twilio_auth_token: str = ""
    test_twilio_from_number: str = ""
    test_vapi_phone_number_id: str = ""
    mock_scenario: str = "success"
    request_timeout_seconds: float = 10.0
    db_pool_timeout_seconds: float = 5.0
    # Supabase's session pooler allows only 15 clients in total, shared by every
    # container and local script, so each process keeps a small pool.
    db_pool_max_size: int = Field(default=3, ge=1, le=20)
    db_pool_max_idle_seconds: float = 60.0
    http_retry_attempts: int = Field(default=3, ge=1, le=5)
    http_retry_base_seconds: float = Field(default=0.5, ge=0.1, le=5.0)
    retry_max_attempts: int = Field(default=5, ge=1, le=20)
    retry_base_seconds: int = Field(default=60, ge=1, le=3600)
    retry_max_seconds: int = Field(default=3600, ge=1, le=86400)

    def _testing_twilio(self) -> bool:
        return self.testing_mode and bool(self.test_twilio_account_sid)

    def twilio_account(self) -> tuple[str, str, str]:
        """(account sid, auth token, from number) for sending: the test account in testing mode."""
        if self._testing_twilio():
            return self.test_twilio_account_sid, self.test_twilio_auth_token, self.test_twilio_from_number
        return self.twilio_account_sid, self.twilio_auth_token, self.twilio_from_number

    def twilio_auth_tokens(self) -> list[str]:
        """Tokens a Twilio webhook may be signed with: both accounts, so callbacks for texts sent
        before a mode switch still verify."""
        return [t for t in (self.twilio_auth_token, self.test_twilio_auth_token) if t]

    def testing_vapi_phone_number_id(self) -> str | None:
        """In testing mode the test Vapi number wins over .env and the database setting."""
        return (self.test_vapi_phone_number_id or None) if self.testing_mode else None

    def mode(self, provider: str) -> str:
        override = getattr(self, f"{provider}_mode", None)
        return override or self.provider_mode

    def provider_url(self, provider: str) -> str:
        if self.mode(provider) == "mock":
            return f"{self.mock_base_url.rstrip('/')}/mock/{provider}"
        return {
            "vapi": self.vapi_base_url,
            "twilio": self.twilio_base_url,
        }[provider].rstrip("/")

    def runtime_errors(self, service: str) -> list[str]:
        errors: list[str] = []
        deployment_env = self.app_env.lower() in {"preproduction", "preprod", "staging", "production", "prod"}
        if service in {"api", "worker", "sheet-worker", "cli"} and not self.supabase_db_url:
            errors.append("SUPABASE_DB_URL is required")
        elif (
            service in {"api", "worker", "sheet-worker", "cli"}
            and "db.example.supabase.co" in self.supabase_db_url
        ):
            errors.append("SUPABASE_DB_URL still contains the example hostname")
        if self.provider_mode not in {"mock", "real"}:
            errors.append("PROVIDER_MODE must be mock or real")
        for provider in ("vapi", "twilio"):
            if self.mode(provider) not in {"mock", "real"}:
                errors.append(f"{provider.upper()}_MODE must be mock or real")
        if service in {"api", "worker"}:
            required: dict[str, str] = {}
            if self.mode("vapi") == "real":
                required.update(
                    VAPI_API_KEY=self.vapi_api_key,
                    VAPI_ASSISTANT_ID=self.vapi_assistant_id,
                    VAPI_PHONE_NUMBER_ID=self.vapi_phone_number_id,
                    VAPI_WEBHOOK_SECRET=self.vapi_webhook_secret,
                    PUBLIC_BASE_URL=self.public_base_url,
                )
            if self.mode("twilio") == "real":
                required.update(
                    TWILIO_ACCOUNT_SID=self.twilio_account_sid,
                    TWILIO_AUTH_TOKEN=self.twilio_auth_token,
                    TWILIO_FROM_NUMBER=self.twilio_from_number,
                    PUBLIC_BASE_URL=self.public_base_url,
                )
            errors.extend(
                f"{name} is required when its provider is real"
                for name, value in required.items() if not value
            )
        if service == "api" and self.assistant_enabled:
            if self.langsmith_tracing or self.langchain_tracing_v2:
                errors.append("LangChain/LangSmith tracing must be disabled for the assistant")
            if not self.openai_api_key:
                errors.append("OPENAI_API_KEY is required when the assistant is enabled")
            if not self.assistant_model.strip():
                errors.append("ASSISTANT_MODEL is required when the assistant is enabled")
            if deployment_env and not self.assistant_phi_approved:
                errors.append("ASSISTANT_PHI_APPROVED must be true for the production assistant")
            if (deployment_env or self.assistant_phi_approved) and not (
                self.assistant_phi_approval_reference.strip()
            ):
                errors.append(
                    "ASSISTANT_PHI_APPROVAL_REFERENCE is required for real-patient assistant use"
                )
        if deployment_env:
            database_url = self.supabase_db_url.lower()
            if not any(
                value in database_url for value in ("sslmode=require", "sslmode=verify-full")
            ):
                errors.append("SUPABASE_DB_URL must set sslmode=require or verify-full")
            if self.public_base_url and not self.public_base_url.startswith("https://"):
                errors.append("PUBLIC_BASE_URL must use HTTPS")
            if service == "api" and len(self.dashboard_api_token) < 32:
                errors.append("DASHBOARD_API_TOKEN must contain at least 32 characters")
            if self.log_level.upper() == "DEBUG":
                errors.append("LOG_LEVEL must not be DEBUG in a deployed environment")
            if "your-ngrok-domain" in self.public_base_url:
                errors.append("PUBLIC_BASE_URL still contains the example hostname")
            if self.mode("vapi") == "real" and self.vapi_webhook_secret == "local-vapi-secret":
                errors.append("VAPI_WEBHOOK_SECRET must be replaced outside local development")
            if self.mode("twilio") == "real" and self.twilio_account_sid == "AC" + "0" * 32:
                errors.append("TWILIO_ACCOUNT_SID still contains the example value")
            if self.mode("twilio") == "real" and self.twilio_from_number == "+15550000001":
                errors.append("TWILIO_FROM_NUMBER still contains the example value")
            if self.phone_fingerprint_secret in {
                "local-fingerprint-secret",
                "replace-this-for-non-local-use",
            }:
                errors.append("PHONE_FINGERPRINT_SECRET must be replaced outside local development")
        if service in {"api", "sheet-worker"} and self.sheet_sync_enabled:
            if not self.dashboard_public_url.startswith("https://"):
                errors.append("DASHBOARD_PUBLIC_URL must use HTTPS")
            elif "example.com" in self.dashboard_public_url:
                errors.append("DASHBOARD_PUBLIC_URL still contains the example hostname")
        if service == "sheet-worker" and self.sheet_sync_enabled:
            if not self.google_sheet_id:
                errors.append("GOOGLE_SHEET_ID is required when Sheet sync is enabled")
            if not Path(self.google_sheet_credentials_file).is_file():
                errors.append("GOOGLE_SHEET_CREDENTIALS_FILE does not point to a readable key file")
            if not self.practice_slug.strip():
                errors.append("PRACTICE_SLUG is required when Sheet sync is enabled")
        test_twilio = [self.test_twilio_account_sid, self.test_twilio_auth_token,
                       self.test_twilio_from_number]
        if any(test_twilio) and not all(test_twilio):
            errors.append("TEST_TWILIO_ACCOUNT_SID, TEST_TWILIO_AUTH_TOKEN and TEST_TWILIO_FROM_NUMBER "
                          "must be set together")
        if self.retry_max_seconds < self.retry_base_seconds:
            errors.append("RETRY_MAX_SECONDS must be greater than or equal to RETRY_BASE_SECONDS")
        return errors


@cache
def get_settings() -> Settings:
    return Settings()
