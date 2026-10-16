from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..config import get_settings
from ..db import transaction

router = APIRouter(tags=["system"])


@router.get("/health", summary="Liveness check")
def health():
    return {"status": "ok", "service": "rpt-agent-api"}


@router.get("/ready", include_in_schema=False)
def ready():
    errors = get_settings().runtime_errors("api")
    if not errors:
        try:
            with transaction() as conn:
                conn.execute("select 1").fetchone()
        except Exception as exc:  # noqa: BLE001 - readiness reports dependency failure
            errors.append(f"database unavailable: {type(exc).__name__}")
    if errors:
        return JSONResponse(status_code=503, content={"status": "not_ready", "errors": errors})
    return {"status": "ready", "service": "rpt-agent-api", "testing_mode": get_settings().testing_mode}
