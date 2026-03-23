"""LLM provider abstraction with production-grade resilience.

Features:
- Retry with exponential backoff (tenacity)
- Circuit breaker for cascading failure prevention
- Rate limiting to stay under API quotas
- Response validation
- Prometheus metrics
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from tektonit.observability import (
    ERRORS,
    LLM_CALL_DURATION,
    LLM_TOKENS,
)
from tektonit.resilience import (
    llm_breaker,
    llm_rate_limiter,
    llm_retry,
)

log = logging.getLogger("tektonit")


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict | None = None


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> LLMResponse: ...

    @abstractmethod
    def name(self) -> str: ...

    def _validate_response(self, content: str | None) -> str:
        """Validate LLM response is non-empty."""
        if not content or not content.strip():
            raise ValueError("LLM returned empty response")
        return content

    def _record_metrics(self, provider_name: str, usage: dict | None, duration: float, success: bool):
        LLM_CALL_DURATION.labels(provider=provider_name, operation="generate").observe(duration)
        if usage:
            LLM_TOKENS.labels(provider=provider_name, direction="input").inc(usage.get("input_tokens", 0))
            LLM_TOKENS.labels(provider=provider_name, direction="output").inc(usage.get("output_tokens", 0))


class GeminiProvider(LLMProvider):
    """Gemini via google-genai SDK (API key auth)."""

    def __init__(self, model: str = "gemini-3.1-pro-preview", api_key: str | None = None):
        from google import genai

        self._model = model
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ValueError("Gemini API key required. Set GEMINI_API_KEY or pass api_key.")
        self._client = genai.Client(api_key=key)

    def name(self) -> str:
        return f"gemini ({self._model})"

    @llm_retry(max_attempts=3)
    def generate(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        if llm_breaker.is_open:
            raise RuntimeError("Circuit breaker open: LLM API unavailable")

        llm_rate_limiter.acquire(timeout=60)

        from google.genai import types

        start = time.time()
        usage = None
        try:
            model_info = self._client.models.get(model=self._model)
            max_tokens = getattr(model_info, "output_token_limit", 65536)

            response = self._client.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=max_tokens,
                    temperature=0.2,
                ),
            )

            if response.usage_metadata:
                usage = {
                    "input_tokens": response.usage_metadata.prompt_token_count,
                    "output_tokens": response.usage_metadata.candidates_token_count,
                }

            content = self._validate_response(response.text)
            llm_breaker.record_success()
            self._record_metrics("gemini", usage, time.time() - start, True)

            return LLMResponse(content=content, model=self._model, usage=usage)

        except Exception as e:
            llm_breaker.record_failure()
            self._record_metrics("gemini", usage, time.time() - start, False)
            ERRORS.labels(component="llm", error_type=type(e).__name__).inc()
            raise


class ClaudeProvider(LLMProvider):
    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: str | None = None):
        try:
            import anthropic
        except ImportError:
            raise ImportError("Claude provider requires anthropic. Install with: pip install 'tektonit[anthropic]'")
        self._model = model
        self._client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def name(self) -> str:
        return f"claude ({self._model})"

    @llm_retry(max_attempts=3)
    def generate(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        if llm_breaker.is_open:
            raise RuntimeError("Circuit breaker open: LLM API unavailable")

        llm_rate_limiter.acquire(timeout=60)

        start = time.time()
        usage = None
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=128000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            if not response.content:
                raise ValueError("Claude returned empty content list")

            content = self._validate_response(response.content[0].text)
            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }

            llm_breaker.record_success()
            self._record_metrics("claude", usage, time.time() - start, True)

            return LLMResponse(content=content, model=self._model, usage=usage)

        except Exception as e:
            llm_breaker.record_failure()
            self._record_metrics("claude", usage, time.time() - start, False)
            ERRORS.labels(component="llm", error_type=type(e).__name__).inc()
            raise


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        try:
            import openai
        except ImportError:
            raise ImportError("OpenAI provider requires openai. Install with: pip install 'tektonit[openai]'")
        self._model = model
        self._client = openai.OpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            base_url=base_url or os.environ.get("OPENAI_BASE_URL"),
        )

    def name(self) -> str:
        return f"openai-compatible ({self._model})"

    @llm_retry(max_attempts=3)
    def generate(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        if llm_breaker.is_open:
            raise RuntimeError("Circuit breaker open: LLM API unavailable")

        llm_rate_limiter.acquire(timeout=60)

        start = time.time()
        usage = None
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=128000,
                temperature=0.2,
            )

            choice = response.choices[0]
            content = self._validate_response(choice.message.content)

            if response.usage:
                usage = {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens,
                }

            llm_breaker.record_success()
            self._record_metrics("openai", usage, time.time() - start, True)

            return LLMResponse(content=content, model=self._model, usage=usage)

        except Exception as e:
            llm_breaker.record_failure()
            self._record_metrics("openai", usage, time.time() - start, False)
            ERRORS.labels(component="llm", error_type=type(e).__name__).inc()
            raise


PROVIDERS = {"gemini", "claude", "openai"}


def create_provider(
    provider: str = "gemini",
    model: str | None = None,
    **kwargs,
) -> LLMProvider:
    """Factory to create an LLM provider."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider!r}. Use one of: {PROVIDERS}")

    if provider == "gemini":
        return GeminiProvider(model=model or "gemini-3.1-pro-preview", api_key=kwargs.get("api_key"))
    elif provider == "claude":
        return ClaudeProvider(model=model or "claude-sonnet-4-20250514", api_key=kwargs.get("api_key"))
    elif provider == "openai":
        return OpenAICompatibleProvider(
            model=model or "gpt-4o",
            api_key=kwargs.get("api_key"),
            base_url=kwargs.get("base_url"),
        )
