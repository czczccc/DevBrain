from fastapi import APIRouter

from backend.services.ai_provider_service import get_ai_config_snapshot

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str | bool]:
    """Simple health endpoint for service readiness checks."""

    snapshot = get_ai_config_snapshot()
    deepseek_configured = bool(
        snapshot.llm_configured
        and snapshot.active_provider
        and snapshot.active_provider.type == "deepseek"
    )
    return {
        "status": "ok",
        "service": "devbrain-backend",
        "llm_configured": snapshot.llm_configured,
        "active_provider_name": snapshot.active_provider_name or "",
        "deepseek_configured": deepseek_configured,
    }
