"""DeepSeek OpenAI-compatible client helpers."""

from __future__ import annotations

from dataclasses import dataclass

import httpx


DEFAULT_SYSTEM_PROMPT = (
    "You are DevBrain, a codebase Q&A assistant. "
    "Answer using only provided context and cite concrete files when possible."
)


class DeepSeekAPIError(Exception):
    """Raised when DeepSeek request or response parsing fails."""


@dataclass(frozen=True)
class DeepSeekConfig:
    """Runtime configuration for DeepSeek chat completions."""

    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 30.0


def chat_completion(
    prompt: str,
    config: DeepSeekConfig,
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
    config: DeepSeekConfig,
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
        raise DeepSeekAPIError("DeepSeek request timed out") from exc
    except httpx.RequestError as exc:
        raise DeepSeekAPIError("DeepSeek request failed") from exc

    if response.status_code >= 400:
        message = response.text.strip()
        short_message = message[:300] if message else "empty response body"
        raise DeepSeekAPIError(f"DeepSeek returned HTTP {response.status_code}: {short_message}")

    try:
        body = response.json()
    except ValueError as exc:
        raise DeepSeekAPIError("DeepSeek response is not valid JSON") from exc

    try:
        answer = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekAPIError("DeepSeek response missing choices[0].message.content") from exc

    if not isinstance(answer, str) or not answer.strip():
        raise DeepSeekAPIError("DeepSeek returned an empty answer")
    return answer.strip()
