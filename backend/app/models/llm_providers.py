"""
LLM Provider Abstraction Layer.

Design decisions:
- Single LLMProvider interface that all agents call — never import OpenAI/Anthropic/Groq directly.
- Provider is selected once at startup via LLM_PROVIDER env var, injected everywhere.
- All providers expose the same two methods:
    chat()       → single structured response
    stream()     → async generator for streaming (Phase 2 frontend)
- Structured output is handled uniformly: we ask the LLM to respond in JSON
  and parse it here, so agents always receive typed Python dicts.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Message type ──────────────────────────────────────────────────────────────

class LLMMessage:
    """Lightweight message container — avoids coupling to any SDK's types."""

    __slots__ = ("role", "content")

    def __init__(self, role: str, content: str) -> None:
        self.role = role      # "system" | "user" | "assistant"
        self.content = content

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}

    def __repr__(self) -> str:
        preview = self.content[:80].replace("\n", " ")
        return f"LLMMessage(role={self.role!r}, content={preview!r})"


# ── Response type ─────────────────────────────────────────────────────────────

class LLMResponse:
    """Normalised response from any provider."""

    __slots__ = ("content", "model", "input_tokens", "output_tokens", "raw")

    def __init__(
        self,
        content: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        raw: Any = None,
    ) -> None:
        self.content = content
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.raw = raw  # original SDK response, useful for debugging

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_json(self) -> dict[str, Any]:
        """
        Parse content as JSON. Strips markdown code fences if present.
        Agents that expect structured output call this instead of content.
        """
        text = self.content.strip()
        # Strip ```json ... ``` or ``` ... ``` fences that LLMs sometimes add
        if text.startswith("```"):
            lines = text.splitlines()
            # Remove first and last fence lines
            inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            text = "\n".join(inner).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning(f"LLM response is not valid JSON: {exc}\nContent: {text[:200]}")
            raise ValueError(f"LLM did not return valid JSON: {exc}") from exc

    def __repr__(self) -> str:
        return (
            f"LLMResponse(model={self.model!r}, "
            f"tokens={self.total_tokens}, "
            f"content={self.content[:60]!r})"
        )


# ── Abstract base ─────────────────────────────────────────────────────────────

class BaseLLMProvider(ABC):
    """
    Abstract interface every provider must implement.
    Agents depend only on this interface — never on concrete SDKs.
    """

    def __init__(self, model: str, temperature: float, max_tokens: int) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @abstractmethod
    async def chat(self, messages: list[LLMMessage]) -> LLMResponse:
        """Send messages and return a single complete response."""
        ...

    @abstractmethod
    async def stream(self, messages: list[LLMMessage]) -> AsyncGenerator[str, None]:
        """Stream response tokens. Yields string chunks."""
        ...

    def _log_call(self, messages: list[LLMMessage]) -> None:
        logger.debug(
            f"{self.__class__.__name__} call | model={self.model} "
            f"messages={len(messages)} last_role={messages[-1].role}"
        )


# ── OpenAI Provider ───────────────────────────────────────────────────────────

class OpenAIProvider(BaseLLMProvider):
    """OpenAI provider using the official openai-python async client."""

    def __init__(self) -> None:
        super().__init__(
            model=settings.OPENAI_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
        )

    def _get_client(self) -> "AsyncOpenAI":
        """Create a new client with the current API key from settings."""
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError("openai package is required: pip install openai") from exc
        return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def chat(self, messages: list[LLMMessage]) -> LLMResponse:
        self._log_call(messages)
        client = self._get_client()
        response = await client.chat.completions.create(
            model=self.model,
            messages=[m.to_dict() for m in messages],  # type: ignore[arg-type]
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            raw=response,
        )

    async def stream(self, messages: list[LLMMessage]) -> AsyncGenerator[str, None]:
        self._log_call(messages)
        client = self._get_client()
        async with await client.chat.completions.create(
            model=self.model,
            messages=[m.to_dict() for m in messages],  # type: ignore[arg-type]
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=True,
        ) as stream:
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta


# ── Claude (Anthropic) Provider ───────────────────────────────────────────────

class ClaudeProvider(BaseLLMProvider):
    """Anthropic Claude provider using the official anthropic-python async client."""

    def __init__(self) -> None:
        super().__init__(
            model=settings.CLAUDE_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
        )

    def _get_client(self) -> "AsyncAnthropic":
        """Create a new client with the current API key from settings."""
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise ImportError("anthropic package is required: pip install anthropic") from exc
        return AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    def _split_system(
        self, messages: list[LLMMessage]
    ) -> tuple[str, list[dict[str, str]]]:
        """
        Anthropic API separates system prompt from messages.
        Extract the first system message (if any) from the list.
        """
        system = ""
        conversation: list[dict[str, str]] = []
        for msg in messages:
            if msg.role == "system" and not system:
                system = msg.content
            else:
                conversation.append(msg.to_dict())
        return system, conversation

    async def chat(self, messages: list[LLMMessage]) -> LLMResponse:
        self._log_call(messages)
        client = self._get_client()
        system, conversation = self._split_system(messages)
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=conversation,
            max_tokens=self.max_tokens,
        )
        if system:
            kwargs["system"] = system

        response = await client.messages.create(**kwargs)
        content = response.content[0].text if response.content else ""
        return LLMResponse(
            content=content,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            raw=response,
        )

    async def stream(self, messages: list[LLMMessage]) -> AsyncGenerator[str, None]:
        self._log_call(messages)
        client = self._get_client()
        system, conversation = self._split_system(messages)
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=conversation,
            max_tokens=self.max_tokens,
        )
        if system:
            kwargs["system"] = system

        async with client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text


# ── Groq Provider ─────────────────────────────────────────────────────────────

class GroqProvider(BaseLLMProvider):
    """
    Groq provider — uses OpenAI-compatible API.
    Groq's SDK mirrors the openai-python interface exactly.
    """

    def __init__(self) -> None:
        super().__init__(
            model=settings.GROQ_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
        )

    def _get_client(self) -> "AsyncGroq":
        """Create a new client with the current API key from settings."""
        try:
            from groq import AsyncGroq
        except ImportError as exc:
            raise ImportError("groq package is required: pip install groq") from exc
        return AsyncGroq(api_key=settings.GROQ_API_KEY)

    async def chat(self, messages: list[LLMMessage]) -> LLMResponse:
        self._log_call(messages)
        client = self._get_client()
        response = await client.chat.completions.create(
            model=self.model,
            messages=[m.to_dict() for m in messages],  # type: ignore[arg-type]
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            raw=response,
        )

    async def stream(self, messages: list[LLMMessage]) -> AsyncGenerator[str, None]:
        self._log_call(messages)
        client = self._get_client()
        stream = await client.chat.completions.create(
            model=self.model,
            messages=[m.to_dict() for m in messages],  # type: ignore[arg-type]
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


# ── Factory ───────────────────────────────────────────────────────────────────

def create_llm_provider() -> BaseLLMProvider:
    """
    Factory function — reads LLM_PROVIDER from settings and returns
    the correct provider instance. Call once at startup and inject
    the result everywhere (avoids re-reading config on every request).
    """
    provider_map: dict[str, type[BaseLLMProvider]] = {
        "openai": OpenAIProvider,
        "claude": ClaudeProvider,
        "groq": GroqProvider,
    }
    provider_class = provider_map.get(settings.LLM_PROVIDER)
    if provider_class is None:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {settings.LLM_PROVIDER!r}. "
            f"Choose from: {list(provider_map.keys())}"
        )
    logger.info(
        f"LLM provider initialised | provider={settings.LLM_PROVIDER} "
        f"model={settings.active_llm_model}"
    )
    return provider_class()
