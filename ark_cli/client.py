"""Volcengine Ark OpenAI-compatible chat client."""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from .config import (
    DEFAULT_ARK_MAX_TOKENS,
    MAX_ARK_MAX_TOKENS,
    MIN_ARK_MAX_TOKENS,
    Config,
)

logger = logging.getLogger(__name__)

_CLIENT: Optional["ArkChatClient"] = None


class ArkChatClient:
    """Minimal client for Ark's OpenAI-compatible chat completions API."""

    def __init__(self, api_key: str, base_url: str, timeout: float):
        if not api_key:
            raise ValueError("ARK_API_KEY is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0,
        max_tokens: int = DEFAULT_ARK_MAX_TOKENS,
    ) -> str:
        if not model:
            raise ValueError("ARK_MODEL is required")
        if not MIN_ARK_MAX_TOKENS <= max_tokens <= MAX_ARK_MAX_TOKENS:
            raise ValueError(
                f"max_tokens must be between {MIN_ARK_MAX_TOKENS} and {MAX_ARK_MAX_TOKENS}"
            )
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        response = self._post(body)
        if response.status_code == 400 and "response_format" in response.text.lower():
            body.pop("response_format", None)
            response = self._post(body)
        if response.status_code == 400:
            logger.error(
                "Ark chat request rejected (HTTP 400), including max_tokens=%s: %s",
                max_tokens,
                response.text[:1000],
            )
        response.raise_for_status()
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Ark response did not contain choices[0].message.content") from exc
        if not isinstance(content, str):
            raise ValueError("Ark response content was not text")
        return content

    def _post(self, body: dict) -> httpx.Response:
        return httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=dict(body),
            timeout=self.timeout,
        )


def get_client(config: Optional[Config] = None) -> ArkChatClient:
    """Return a lazily constructed process-wide Ark client."""
    global _CLIENT
    if _CLIENT is None:
        cfg = config or Config.load()
        _CLIENT = ArkChatClient(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            timeout=cfg.timeout_seconds,
        )
    return _CLIENT


def reset_client() -> None:
    global _CLIENT
    _CLIENT = None
