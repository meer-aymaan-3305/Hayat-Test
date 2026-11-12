"""Backup language model over any OpenAI-compatible chat endpoint.

Used when the primary provider (Groq) is rate limited or down, so a quota on one account
does not stop the chat. Examples of base URLs:
  Google Gemini  https://generativelanguage.googleapis.com/v1beta/openai
  OpenRouter     https://openrouter.ai/api/v1
  OpenAI         https://api.openai.com/v1
"""

from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger("hayat.llm_compat")


class CompatError(RuntimeError):
    """The backup provider could not answer."""


class OpenAICompatClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
        extra: dict | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._model = model
        self._timeout = timeout
        self._transport = transport
        # Provider options such as turning thinking off; dropped if the provider rejects them.
        self._extra = extra or {}
        self._blocked_until = 0.0  # after a 429 the provider is skipped for a short while

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> tuple[str, str | None]:
        """Return (text, finish_reason)."""
        if self._blocked_until > time.monotonic():
            raise CompatError("Backup model is rate limited; skipping it for now.")
        body: dict = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **self._extra,
        }
        plain = {k: v for k, v in body.items() if k not in self._extra}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                headers = {"Authorization": f"Bearer {self._key}"}
                if json_mode:
                    response = await client.post(
                        self._url, headers=headers,
                        json={**body, "response_format": {"type": "json_object"}},
                    )
                    if response.status_code == 400:  # provider without JSON mode or options
                        response = await client.post(self._url, headers=headers, json=plain)
                else:
                    response = await client.post(self._url, headers=headers, json=body)
                    if response.status_code == 400 and self._extra:
                        response = await client.post(self._url, headers=headers, json=plain)
        except httpx.HTTPError as exc:
            raise CompatError("Backup model request failed.") from exc
        if response.status_code == 429:
            self._blocked_until = time.monotonic() + 30
        if response.status_code >= 400:
            raise CompatError(f"Backup model returned {response.status_code}.")
        try:
            choice = response.json()["choices"][0]
            text = (choice["message"].get("content") or "").strip()
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise CompatError("Backup model returned an unreadable answer.") from exc
        if not text:
            raise CompatError("Backup model returned an empty answer.")
        return text, choice.get("finish_reason")
