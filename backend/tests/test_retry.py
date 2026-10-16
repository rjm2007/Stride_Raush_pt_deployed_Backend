from pathlib import Path

from rpt_agent.config import Settings
from rpt_agent.retry import retry_delay_seconds


def test_exponential_retry_delay_respects_provider_and_cap(monkeypatch):
    monkeypatch.setattr("rpt_agent.retry.random.uniform", lambda _start, _end: 1.0)
    settings = Settings(retry_base_seconds=60, retry_max_seconds=3600)
    assert retry_delay_seconds(1, settings=settings) == 60
    assert retry_delay_seconds(3, settings=settings) == 240
    assert retry_delay_seconds(1, retry_after_seconds=600, settings=settings) == 600
    assert retry_delay_seconds(1, retry_after_seconds=7200, settings=settings) == 7200
    assert retry_delay_seconds(20, settings=settings) == 3600


def test_retry_migration_repairs_call_log_contract_and_notification_queue():
    sql = Path("supabase/migrations/013_retry_and_reconciliation.sql").read_text(
        encoding="utf-8"
    )
    assert "call_logs" in sql and "outreach_event_id" in sql
    assert "notification_log" in sql and "next_attempt_at" in sql and "attempts" in sql
    assert "provider_events" in sql and "dead_lettered_at" in sql


def test_preproduction_booking_migration_adds_safe_integration_audit():
    sql = Path("supabase/migrations/014_preproduction_booking_api.sql").read_text(
        encoding="utf-8"
    )
    assert "integration_events" in sql
    assert "outcome_source" in sql
    assert "payload" not in sql


def test_assistant_audit_rate_limit_index_is_migrated():
    sql = Path("supabase/migrations/023_assistant_audit_rate_limit.sql").read_text(
        encoding="utf-8"
    )
    assert "dashboard_audit_log(actor_id,action,created_at desc)" in sql


def test_production_may_run_in_testing_mode():
    """TESTING_MODE is how the live server is checked end to end before go-live."""
    settings = Settings(_env_file=None, app_env="production", testing_mode=True)
    assert settings.testing_day_minutes == 1
    assert not any("TEST" in error for error in settings.runtime_errors("api"))
    assert Settings.model_fields["testing_mode"].default is False


def test_preproduction_rejects_disabled_database_tls():
    settings = Settings(
        app_env="preproduction",
        supabase_db_url="postgresql://db.invalid/postgres?sslmode=disable",
    )
    assert "SUPABASE_DB_URL must set sslmode=require or verify-full" in settings.runtime_errors(
        "api"
    )


def test_preproduction_rejects_incomplete_real_provider_configuration():
    settings = Settings(
        _env_file=None,
        app_env="preproduction",
        provider_mode="real",
        supabase_db_url="postgresql://db.invalid/postgres?sslmode=require",
        public_base_url="https://preprod.invalid",
        vapi_api_key="configured",
        vapi_webhook_secret="configured",
        twilio_account_sid="AC" + "1" * 32,
        twilio_auth_token="configured",
    )
    errors = settings.runtime_errors("api")
    assert "VAPI_ASSISTANT_ID is required when its provider is real" in errors
    assert "VAPI_PHONE_NUMBER_ID is required when its provider is real" in errors
    assert "TWILIO_FROM_NUMBER still contains the example value" in errors
    assert "PHONE_FINGERPRINT_SECRET must be replaced outside local development" in errors


def test_production_api_needs_no_stride_keap_or_n8n_secret():
    # This build has no Stride, Keap or n8n: a complete production .env without any of their
    # variables must start cleanly (the old checks demanded N8N_INTAKE_* and STRIDE_API_TOKEN).
    settings = Settings(
        _env_file=None,
        app_env="production",
        provider_mode="real",
        supabase_db_url="postgresql://db.invalid/postgres?sslmode=require",
        public_base_url="https://prod.invalid",
        dashboard_api_token="x" * 32,
        vapi_api_key="configured",
        vapi_assistant_id="assistant",
        vapi_phone_number_id="phone",
        vapi_webhook_secret="configured-webhook-secret",
        twilio_account_sid="AC" + "1" * 32,
        twilio_auth_token="configured",
        twilio_from_number="+15551234567",
        phone_fingerprint_secret="configured-fingerprint",
    )
    assert settings.runtime_errors("api") == []
    assert settings.runtime_errors("worker") == []


def test_sheet_worker_needs_the_google_sheet_when_enabled(tmp_path):
    base = {
        "_env_file": None,
        "app_env": "production",
        "supabase_db_url": "postgresql://db.invalid/postgres?sslmode=require",
        "dashboard_public_url": "https://dash.invalid",
        "phone_fingerprint_secret": "configured-fingerprint",
        "sheet_sync_enabled": True,
    }
    errors = Settings(**base, google_sheet_credentials_file=str(tmp_path / "missing.json")).runtime_errors(
        "sheet-worker"
    )
    assert "GOOGLE_SHEET_ID is required when Sheet sync is enabled" in errors
    assert "GOOGLE_SHEET_CREDENTIALS_FILE does not point to a readable key file" in errors
    key = tmp_path / "sa.json"
    key.write_text("{}")
    ok = Settings(**base, google_sheet_id="sheet", google_sheet_credentials_file=str(key))
    assert ok.runtime_errors("sheet-worker") == []


def test_production_assistant_requires_phi_approval_evidence():
    settings = Settings(
        _env_file=None,
        app_env="production",
        assistant_enabled=True,
        openai_api_key="configured",
        supabase_db_url="postgresql://db.invalid/postgres?sslmode=require",
        dashboard_api_token="x" * 32,
        phone_fingerprint_secret="configured-fingerprint",
    )
    errors = settings.runtime_errors("api")
    assert "ASSISTANT_PHI_APPROVED must be true for the production assistant" in errors
    assert "ASSISTANT_PHI_APPROVAL_REFERENCE is required for real-patient assistant use" in errors

    approved = settings.model_copy(
        update={"assistant_phi_approved": True, "assistant_phi_approval_reference": "security-review-123"}
    )
    assert not any("ASSISTANT_" in error or "OPENAI_" in error for error in approved.runtime_errors("api"))
    traced = approved.model_copy(update={"langsmith_tracing": True})
    assert "LangChain/LangSmith tracing must be disabled for the assistant" in (
        traced.runtime_errors("api")
    )
