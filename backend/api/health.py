from fastapi import APIRouter

from backend.settings import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str | bool]:
    """Simple health endpoint for service readiness checks."""

    return {
        "status": "ok",
        "service": "devbrain-backend",
        "deepseek_configured": bool(settings.deepseek_api_key),
    }
