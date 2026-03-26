"""OpenAI-compatible chat completion client."""

from __future__ import annotations

import httpx

from backend.models import RuntimeAIProvider

DEFAULT_SYSTEM_PROMPT = (
    "You are DevBrain, a codebase Q&A assistant. "
    "Answer using only provided context and cite concrete files when possible."
)


class LLMClientError(Exception):
    """Raised when an upstream LLM request fails or returns malformed data."""


def chat_completion(
    prompt: str,
    config: RuntimeAIProvider,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> str:
    """Send a non-streaming chat completion request and return answer text."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return chat_completion_from_messages(messages=messages, config=config)


def chat_completion_from_messages(
    messages: list[dict[str, str]],
    config: RuntimeAIProvider,
) -> str:
    """Send a non-streaming chat completion request using raw messages."""

    endpoint = f"{config.base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": 0.1,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}

    try:
        with httpx.Client(timeout=config.timeout_seconds) as client:
            response = client.post(endpoint, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise LLMClientError("AI 请求超时") from exc
    except httpx.RequestError as exc:
        raise LLMClientError("AI 请求失败") from exc

    if response.status_code >= 400:
        message = response.text.strip()
        short_message = message[:300] if message else "empty response body"
        raise LLMClientError(f"AI 服务返回 HTTP {response.status_code}: {short_message}")

    try:
        body = response.json()
    except ValueError as exc:
        raise LLMClientError("AI 服务返回了无效 JSON") from exc

    try:
        answer = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMClientError("AI 服务返回缺少 choices[0].message.content") from exc

    if not isinstance(answer, str) or not answer.strip():
        raise LLMClientError("AI 服务返回了空回答")
    return answer.strip()
