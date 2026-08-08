"""
Supabase client bootstrap.

Design decisions:
- We use the SERVICE ROLE key for all backend operations so row-level security
  policies don't block server-side writes. Never expose this key to the frontend.
- A single async client is created once at startup (lifespan) and shared across
  the process — Supabase's postgrest client is thread/async safe for concurrent reads.
- The client is stored on app.state so FastAPI's dependency injection can reach it
  from any route without importing a global.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

from supabase import create_client, Client
from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level singleton — populated by init_supabase_client()
_client: Optional[Client] = None


def init_supabase_client() -> Client:
    """
    Create and cache the Supabase client.
    Called once during FastAPI lifespan startup.
    Raises clearly if credentials are missing.
    """
    global _client

    if not settings.SUPABASE_URL:
        raise ValueError("SUPABASE_URL is not set in environment variables.")
    if not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise ValueError("SUPABASE_SERVICE_ROLE_KEY is not set in environment variables.")

    _client = create_client(
        supabase_url=settings.SUPABASE_URL,
        supabase_key=settings.SUPABASE_SERVICE_ROLE_KEY,
    )

    logger.info(f"Supabase client initialised | url={settings.SUPABASE_URL}")
    return _client


def get_supabase_client() -> Client:
    """
    Return the cached Supabase client.
    Raises RuntimeError if called before init_supabase_client().
    Use this inside service classes — not directly in route handlers.
    """
    if _client is None:
        raise RuntimeError(
            "Supabase client has not been initialised. "
            "Ensure init_supabase_client() is called during app startup."
        )
    return _client
