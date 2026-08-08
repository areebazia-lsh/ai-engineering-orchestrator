"""
Settings endpoints for dynamic LLM provider configuration.

POST /api/v1/settings/llm-provider
  - Accepts {provider, api_key} (api_key is optional)
  - Validates the key with one lightweight real test call
  - Updates the active provider in-memory for subsequent requests

Response format:
{
  "success": true,
  "provider": "openai",
  "model": "gpt-4o",
  "api_key_masked": "sk-...xxxx"
}

Error responses:
  400: Invalid provider name or API key validation failed
  500: Unexpected error
"""

from __future__ import annotations

import logging

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.models.llm_providers import OpenAIProvider, ClaudeProvider, GroqProvider

logger = logging.getLogger(__name__)
router = APIRouter()


class LLMProviderRequest(BaseModel):
    """Request body for updating LLM provider."""
    provider: str
    api_key: str | None = None


class LLMProviderResponse(BaseModel):
    """Response body for LLM provider status."""
    success: bool
    provider: str
    model: str
    api_key_masked: str


def mask_api_key(key: str | None) -> str:
    """Mask API key showing only last 4 characters."""
    if not key:
        return "***"
    if len(key) <= 4:
        return "*" * len(key)
    return key[:6] + "..." + key[-4:]


async def _test_provider_api_key(provider: str, api_key: str) -> tuple[bool, str]:
    """
    Test if an API key is valid by making a minimal request.
    
    Returns (success, error_message).
    Uses minimal tokens to keep cost low.
    """
    if not api_key:
        return False, "API key is required"

    try:
        if provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key, timeout=5.0)
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=3,
            )
            return True, ""

        elif provider == "claude":
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=api_key, timeout=5.0)
            response = await client.messages.create(
                model="claude-3-haiku-20240307",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=3,
            )
            return True, ""

        elif provider == "groq":
            from groq import AsyncGroq
            client = AsyncGroq(api_key=api_key, timeout=5.0)
            response = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=3,
            )
            return True, ""

        else:
            return False, f"Unknown provider: {provider}"

    except Exception as exc:
        return False, str(exc)


@router.post(
    "/settings/llm-provider",
    response_model=LLMProviderResponse,
)
async def set_llm_provider(request: LLMProviderRequest) -> dict[str, Any]:
    """
    Set the active LLM provider and optionally update the API key.
    - Validates the API key with a lightweight test call
    - Updates the provider in-memory for the current session
    - Never logs or stores the raw API key
    """
    provider = request.provider.lower()

    valid_providers = ["openai", "claude", "groq"]
    if provider not in valid_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider. Must be one of: {', '.join(valid_providers)}",
        )

    api_key = request.api_key
    if not api_key:
        if provider == "openai":
            api_key = settings.OPENAI_API_KEY
        elif provider == "claude":
            api_key = settings.ANTHROPIC_API_KEY
        elif provider == "groq":
            api_key = settings.GROQ_API_KEY

    success, error = await _test_provider_api_key(provider, api_key)
    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"API key validation failed: {error}",
        )

    if provider == "openai":
        settings.LLM_PROVIDER = "openai"
        settings.OPENAI_API_KEY = api_key
    elif provider == "claude":
        settings.LLM_PROVIDER = "claude"
        settings.ANTHROPIC_API_KEY = api_key
    elif provider == "groq":
        settings.LLM_PROVIDER = "groq"
        settings.GROQ_API_KEY = api_key

    logger.info(
        f"LLM provider updated | provider={provider} "
        f"model={settings.active_llm_model}"
    )

    return {
        "success": True,
        "provider": provider,
        "model": settings.active_llm_model,
        "api_key_masked": mask_api_key(api_key),
    }


@router.get(
    "/settings/llm-provider",
    response_model=LLMProviderResponse,
)
async def get_llm_provider() -> dict[str, Any]:
    """Get the current LLM provider configuration."""
    return {
        "success": True,
        "provider": settings.LLM_PROVIDER,
        "model": settings.active_llm_model,
        "api_key_masked": mask_api_key(settings.active_llm_api_key),
    }
