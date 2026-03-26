"""Provider metadata persistence and runtime resolution."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import uuid

from backend.models import (
    AIConfigSnapshot,
    ProviderTemplate,
    PublicAIProvider,
    RuntimeAIProvider,
    StoredAIProvider,
    StoredAIProviderState,
)
from backend.services.secret_store import SecretStoreError, get_secret_store

CONFIG_ROOT = Path("data/config")
PROVIDERS_FILE = CONFIG_ROOT / "ai_providers.json"
SECRET_REF_PREFIX = "provider:"
SUPPORTED_PROVIDER_TYPES = {"deepseek", "kimi", "bailian", "minimax", "custom"}
PROVIDER_TEMPLATES = [
    ProviderTemplate(
        type="deepseek",
        label="DeepSeek",
        description="DeepSeek 官方 OpenAI 兼容接口",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
    ),
    ProviderTemplate(
        type="kimi",
        label="Kimi",
        description="Moonshot Kimi OpenAI 兼容接口",
        base_url="https://api.moonshot.cn/v1",
        model="moonshot-v1-8k",
    ),
    ProviderTemplate(
        type="bailian",
        label="百炼",
        description="阿里云百炼 OpenAI 兼容接口",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3-coder-plus",
    ),
    ProviderTemplate(
        type="minimax",
        label="MiniMax",
        description="MiniMax OpenAI 兼容接口",
        base_url="https://api.minimaxi.com/v1",
        model="MiniMax-M2.5",
    ),
    ProviderTemplate(
        type="custom",
        label="自定义",
        description="自定义 OpenAI 兼容接口",
        base_url="https://api.example.com/v1",
        model="custom-model",
    ),
]


class AIProviderError(Exception):
    """Service-level error with HTTP-friendly status codes."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def get_ai_config_snapshot() -> AIConfigSnapshot:
    """Return the full UI-facing provider configuration state."""

    state = _load_state()
    public_providers = [_to_public_provider(provider, state.active_provider_id) for provider in state.providers]
    active_provider = next((item for item in public_providers if item.is_active), None)
    llm_configured = bool(active_provider and active_provider.configured)
    return AIConfigSnapshot(
        llm_configured=llm_configured,
        active_provider_id=state.active_provider_id,
        active_provider_name=active_provider.name if active_provider else None,
        active_provider=active_provider,
        providers=public_providers,
        templates=PROVIDER_TEMPLATES,
    )


def save_provider(
    *,
    provider_id: str | None,
    provider_type: str,
    name: str,
    base_url: str,
    model: str,
    api_key: str,
) -> AIConfigSnapshot:
    """Create or update provider metadata and persist its secret."""

    normalized_type = provider_type.strip().lower()
    if normalized_type not in SUPPORTED_PROVIDER_TYPES:
        raise AIProviderError("不支持的 Provider 类型。")

    normalized_name = name.strip()
    normalized_base_url = base_url.strip().rstrip("/")
    normalized_model = model.strip()
    normalized_key = api_key.strip()
    if not normalized_name:
        raise AIProviderError("名称不能为空。")
    if not normalized_base_url.startswith("http://") and not normalized_base_url.startswith("https://"):
        raise AIProviderError("Base URL 必须以 http:// 或 https:// 开头。")
    if not normalized_model:
        raise AIProviderError("模型名称不能为空。")

    state = _load_state()
    providers_by_id = {item.id: item for item in state.providers}
    existing = providers_by_id.get(provider_id or "")

    if existing is None and not normalized_key:
        raise AIProviderError("首次创建 Provider 时必须填写 API Key。")

    if existing is not None:
        secret_ref = existing.secret_ref
    else:
        created_id = provider_id or uuid.uuid4().hex
        secret_ref = f"{SECRET_REF_PREFIX}{created_id}"
        provider_id = created_id

    if normalized_key:
        _store_secret(secret_ref, normalized_key)
    elif existing is None:
        raise AIProviderError("缺少 API Key。")

    stored_provider = StoredAIProvider(
        id=provider_id or "",
        type=normalized_type,
        name=normalized_name,
        base_url=normalized_base_url,
        model=normalized_model,
        secret_ref=secret_ref,
        enabled=True,
    )
    updated_providers = [item for item in state.providers if item.id != stored_provider.id]
    updated_providers.append(stored_provider)
    updated_state = StoredAIProviderState(
        active_provider_id=stored_provider.id,
        providers=sorted(updated_providers, key=lambda item: item.name.lower()),
    )
    _save_state(updated_state)
    return get_ai_config_snapshot()


def activate_provider(provider_id: str) -> AIConfigSnapshot:
    """Set the active provider used for ask/analyze requests."""

    state = _load_state()
    if not any(item.id == provider_id for item in state.providers):
        raise AIProviderError("要激活的 Provider 不存在。", status_code=404)
    updated_state = StoredAIProviderState(active_provider_id=provider_id, providers=state.providers)
    _save_state(updated_state)
    return get_ai_config_snapshot()


def delete_provider(provider_id: str) -> AIConfigSnapshot:
    """Delete provider metadata and its secret."""

    state = _load_state()
    remaining = [item for item in state.providers if item.id != provider_id]
    if len(remaining) == len(state.providers):
        raise AIProviderError("要删除的 Provider 不存在。", status_code=404)

    removed = next(item for item in state.providers if item.id == provider_id)
    _delete_secret(removed.secret_ref)
    next_active = state.active_provider_id
    if state.active_provider_id == provider_id:
        next_active = remaining[0].id if remaining else None
    updated_state = StoredAIProviderState(active_provider_id=next_active, providers=remaining)
    _save_state(updated_state)
    return get_ai_config_snapshot()


def get_active_runtime_provider() -> RuntimeAIProvider:
    """Resolve the active provider and load its API key from the OS secret store."""

    state = _load_state()
    if not state.active_provider_id:
        raise AIProviderError("尚未配置可用的 AI Provider。", status_code=500)

    provider = next((item for item in state.providers if item.id == state.active_provider_id), None)
    if provider is None:
        raise AIProviderError("当前激活的 AI Provider 不存在。", status_code=500)

    api_key = _load_secret(provider.secret_ref)
    if not api_key:
        raise AIProviderError("当前激活的 AI Provider 缺少可用 API Key。", status_code=500)

    return RuntimeAIProvider(
        id=provider.id,
        type=provider.type,
        name=provider.name,
        base_url=provider.base_url,
        model=provider.model,
        api_key=api_key,
    )


def _to_public_provider(provider: StoredAIProvider, active_provider_id: str | None) -> PublicAIProvider:
    configured = bool(_maybe_load_secret(provider.secret_ref))
    return PublicAIProvider(
        id=provider.id,
        type=provider.type,
        name=provider.name,
        base_url=provider.base_url,
        model=provider.model,
        enabled=provider.enabled,
        configured=configured,
        is_active=provider.id == active_provider_id,
    )


def _load_state() -> StoredAIProviderState:
    if not PROVIDERS_FILE.exists():
        return StoredAIProviderState()
    payload = json.loads(PROVIDERS_FILE.read_text(encoding="utf-8"))
    providers = [StoredAIProvider(**item) for item in payload.get("providers", []) if isinstance(item, dict)]
    active_provider_id = payload.get("active_provider_id")
    if active_provider_id and not any(item.id == active_provider_id for item in providers):
        active_provider_id = None
    return StoredAIProviderState(active_provider_id=active_provider_id, providers=providers)


def _save_state(state: StoredAIProviderState) -> None:
    CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "active_provider_id": state.active_provider_id,
        "providers": [asdict(item) for item in state.providers],
    }
    PROVIDERS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _store_secret(secret_ref: str, api_key: str) -> None:
    try:
        get_secret_store().set_secret(secret_ref, api_key)
    except SecretStoreError as exc:
        raise AIProviderError(str(exc), status_code=500) from exc


def _load_secret(secret_ref: str) -> str:
    try:
        secret = get_secret_store().get_secret(secret_ref)
    except SecretStoreError as exc:
        raise AIProviderError(str(exc), status_code=500) from exc
    if not secret:
        raise AIProviderError("系统凭据库中未找到对应的 API Key。", status_code=500)
    return secret


def _maybe_load_secret(secret_ref: str) -> str | None:
    try:
        return get_secret_store().get_secret(secret_ref)
    except SecretStoreError:
        return None


def _delete_secret(secret_ref: str) -> None:
    try:
        get_secret_store().delete_secret(secret_ref)
    except SecretStoreError as exc:
        raise AIProviderError(str(exc), status_code=500) from exc
