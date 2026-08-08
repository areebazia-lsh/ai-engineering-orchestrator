"""
Core configuration management using pydantic-settings.
All environment variables are loaded from .env file.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ────────────────────────────────────────────────────────
    APP_NAME: str = "AI Engineering Orchestrator"
    APP_VERSION: str = "0.1.0"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True

    # ── API ────────────────────────────────────────────────────────────────
    API_V1_PREFIX: str = "/api/v1"
    ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = [f"http://localhost:{p}" for p in range(3000, 3011)] + ["http://localhost:8000"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v):
        """
        Accepts either a JSON array string (e.g. '["a","b"]') or a plain
        comma-separated string (e.g. 'a,b,c') from the environment.
        Prevents crashes when the env var is edited by hand on a dashboard
        and the JSON syntax gets broken (trailing commas, missing brackets,
        missing separators, etc).
        """
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("["):
                try:
                    import json
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(o).strip().rstrip("/") for o in parsed if str(o).strip()]
                except Exception:
                    pass
            # Fallback: treat as comma-separated
            return [o.strip().rstrip("/") for o in v.split(",") if o.strip()]
        return v

    # ── LLM Provider ───────────────────────────────────────────────────────
    # Set to "openai", "claude", or "groq"
    LLM_PROVIDER: Literal["openai", "claude", "groq"] = "openai"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"

    # Anthropic / Claude
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-3-5-sonnet-20241022"

    # Groq
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Shared LLM params
    LLM_TEMPERATURE: float = 0.1       # Low temp → more deterministic agent reasoning
    LLM_MAX_TOKENS: int = 4096

    # ── Supabase ───────────────────────────────────────────────────────────
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""  # Use service role for backend operations

    # ── LangGraph ──────────────────────────────────────────────────────────
    MAX_AGENT_RETRIES: int = 3           # Max validation retries before giving up
    GRAPH_RECURSION_LIMIT: int = 25      # LangGraph recursion safety limit

    # ── Logging ────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "text"] = "text"

    @field_validator("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip() if v else ""

    @property
    def active_llm_api_key(self) -> str:
        """Returns the API key for the currently configured LLM provider."""
        return {
            "openai": self.OPENAI_API_KEY,
            "claude": self.ANTHROPIC_API_KEY,
            "groq": self.GROQ_API_KEY,
        }[self.LLM_PROVIDER]

    @property
    def active_llm_model(self) -> str:
        """Returns the model name for the currently configured LLM provider."""
        return {
            "openai": self.OPENAI_MODEL,
            "claude": self.CLAUDE_MODEL,
            "groq": self.GROQ_MODEL,
        }[self.LLM_PROVIDER]

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Cached settings instance — only reads .env once per process.
    Use this everywhere instead of instantiating Settings() directly.
    """
    return Settings()


# Module-level convenience alias
settings = get_settings()