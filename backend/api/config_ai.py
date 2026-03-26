"""AI provider configuration endpoints."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.ai_provider_service import (
    AIProviderError,
    activate_provider,
    delete_provider,
    get_ai_config_snapshot,
    save_provider,
)

router = APIRouter(prefix="/config/ai", tags=["config"])


class ProviderTemplateItem(BaseModel):
    type: str
    label: str
    description: str
    base_url: str
    model: str


class ProviderItem(BaseModel):
    id: str
    type: str
    name: str
    base_url: str
    model: str
    enabled: bool
    configured: bool
    is_active: bool


class AIConfigResponse(BaseModel):
    llm_configured: bool
    active_provider_id: str | None
    active_provider_name: str | None
    active_provider: ProviderItem | None
    providers: list[ProviderItem]
    templates: list[ProviderTemplateItem]


class SaveProviderRequest(BaseModel):
    provider_id: str | None = None
    type: str
    name: str
    base_url: str
    model: str
    api_key: str = Field(default="")


class ActivateProviderRequest(BaseModel):
    provider_id: str


@router.get("", response_model=AIConfigResponse)
def get_ai_config() -> AIConfigResponse:
    return _snapshot_response()


@router.post("/providers", response_model=AIConfigResponse)
def upsert_provider(payload: SaveProviderRequest) -> AIConfigResponse:
    try:
        snapshot = save_provider(
            provider_id=payload.provider_id,
            provider_type=payload.type,
            name=payload.name,
            base_url=payload.base_url,
            model=payload.model,
            api_key=payload.api_key,
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _to_response(snapshot)


@router.post("/activate", response_model=AIConfigResponse)
def activate_provider_route(payload: ActivateProviderRequest) -> AIConfigResponse:
    try:
        snapshot = activate_provider(payload.provider_id)
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _to_response(snapshot)


@router.delete("/providers/{provider_id}", response_model=AIConfigResponse)
def delete_provider_route(provider_id: str) -> AIConfigResponse:
    try:
        snapshot = delete_provider(provider_id)
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _to_response(snapshot)


def _snapshot_response() -> AIConfigResponse:
    try:
        snapshot = get_ai_config_snapshot()
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _to_response(snapshot)


def _to_response(snapshot) -> AIConfigResponse:
    active_provider = ProviderItem(**asdict(snapshot.active_provider)) if snapshot.active_provider else None
    return AIConfigResponse(
        llm_configured=snapshot.llm_configured,
        active_provider_id=snapshot.active_provider_id,
        active_provider_name=snapshot.active_provider_name,
        active_provider=active_provider,
        providers=[ProviderItem(**asdict(item)) for item in snapshot.providers],
        templates=[ProviderTemplateItem(**asdict(item)) for item in snapshot.templates],
    )
