"""Data models for configurable LLM providers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderTemplate:
    """Preset values for a supported provider."""

    type: str
    label: str
    description: str
    base_url: str
    model: str


@dataclass(frozen=True)
class StoredAIProvider:
    """Provider metadata persisted on disk."""

    id: str
    type: str
    name: str
    base_url: str
    model: str
    secret_ref: str
    enabled: bool = True


@dataclass(frozen=True)
class StoredAIProviderState:
    """Persistent metadata file payload."""

    active_provider_id: str | None = None
    providers: list[StoredAIProvider] = field(default_factory=list)


@dataclass(frozen=True)
class PublicAIProvider:
    """Provider metadata safe to send to the frontend."""

    id: str
    type: str
    name: str
    base_url: str
    model: str
    enabled: bool
    configured: bool
    is_active: bool


@dataclass(frozen=True)
class RuntimeAIProvider:
    """Resolved provider configuration with API key loaded from secret storage."""

    id: str
    type: str
    name: str
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class AIConfigSnapshot:
    """Combined UI-facing state for provider management."""

    llm_configured: bool
    active_provider_id: str | None
    active_provider_name: str | None
    active_provider: PublicAIProvider | None
    providers: list[PublicAIProvider]
    templates: list[ProviderTemplate]
