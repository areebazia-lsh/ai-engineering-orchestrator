"""
FastAPI application entry point.

Startup sequence (via lifespan):
  1. Setup structured logging
  2. Validate critical environment variables
  3. Initialise Supabase client
  4. Initialise LLM provider
  5. Compile LangGraph workflow (expensive once, cheap forever)
  6. Attach everything to app.state for dependency injection

Shutdown sequence:
  1. Log shutdown message
  (Resources are garbage collected — Supabase and LLM clients are stateless)

Design decisions:
  - lifespan context manager (not deprecated on_startup/on_shutdown events)
  - app.state carries compiled_graph and llm so routes access them via
    Request.app.state — no module-level globals needed in route files
  - Global exception handler catches unhandled errors and returns clean JSON
    instead of leaking tracebacks to clients
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import setup_logging
from app.database.supabase_client import init_supabase_client
from app.models.llm_providers import create_llm_provider
from app.orchestration.graph import build_graph
from app.api.v1.routes import chat, projects, sessions, ingestion, patches
from app.api.v1.routes import settings as settings_router


def _warmup_embedder() -> None:
    """Load embedding model synchronously — runs once in a thread at startup."""
    from app.ingestion.embedder import warmup
    warmup()


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler.
    Code before yield runs at startup; code after yield runs at shutdown.
    """
    # ── STARTUP ────────────────────────────────────────────────────────────────
    logger = logging.getLogger(__name__)

    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Environment: {settings.APP_ENV}")

    # Validate required env vars early — fail loud at startup, not mid-request
    missing: list[str] = []
    if not settings.SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not settings.SUPABASE_SERVICE_ROLE_KEY:
        missing.append("SUPABASE_SERVICE_ROLE_KEY")
    if not settings.active_llm_api_key:
        missing.append(f"{settings.LLM_PROVIDER.upper()}_API_KEY")
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Check your .env file."
        )

    # Supabase client
    logger.info("Initialising Supabase client...")
    supabase_client = init_supabase_client()

    # Vector store (Phase 2)
    logger.info("Initialising vector store...")
    from app.knowledge.vector_store.supabase_store import SupabaseVectorStore
    vector_store = SupabaseVectorStore(supabase_client)
    app.state.vector_store = vector_store

    # Embedding model warmup — downloads ~22 MB on first run, then cached
    logger.info("Warming up embedding model (fastembed BAAI/bge-small-en-v1.5)...")
    await asyncio.to_thread(_warmup_embedder)

    # LLM provider
    logger.info(f"Initialising LLM provider: {settings.LLM_PROVIDER}...")
    llm = create_llm_provider()
    app.state.llm = llm

    # LangGraph — compiled once, reused for every request
    logger.info("Compiling LangGraph workflow...")
    compiled_graph = build_graph(llm, vector_store=vector_store)
    app.state.compiled_graph = compiled_graph
    
    # Also store the nodes dict for single-agent execution
    from app.orchestration.nodes import create_nodes
    nodes = create_nodes(llm, vector_store=vector_store)
    app.state.orchestration_nodes = nodes

    logger.info("Application startup complete. Ready to accept requests.")

    yield  # ← Application runs here

    # ── SHUTDOWN ───────────────────────────────────────────────────────────────
    logger.info(f"Shutting down {settings.APP_NAME}...")


# ── Application factory ────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    Called once at module level — the returned app is the ASGI entry point.
    """
    # Logging must be configured before anything else
    setup_logging()

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Agentic AI system for software engineering teams. "
            "Understands codebases, plans tasks, generates patches, "
            "and maintains long-term project knowledge."
        ),
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        openapi_url="/openapi.json" if settings.is_development else None,
        lifespan=lifespan,
    )

    # ── CORS ───────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Global exception handler ───────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger = logging.getLogger(__name__)
        logger.exception(
            f"Unhandled exception | method={request.method} "
            f"path={request.url.path} error={exc}"
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "An unexpected error occurred. Please try again.",
                "error_code": "INTERNAL_SERVER_ERROR",
            },
        )

    # ── Routers ────────────────────────────────────────────────────────────────
    prefix = settings.API_V1_PREFIX   # "/api/v1"

    app.include_router(
        chat.router,
        prefix=prefix,
        tags=["Chat"],
    )
    app.include_router(
        projects.router,
        prefix=prefix,
        tags=["Projects"],
    )
    app.include_router(
        sessions.router,
        prefix=prefix,
        tags=["Sessions"],
    )
    app.include_router(
        ingestion.router,
        prefix=prefix,
        tags=["Ingestion"],
    )
    app.include_router(
        patches.router,
        prefix=prefix,
        tags=["Patches"],
    )
    app.include_router(
        settings_router.router,
        prefix=prefix,
        tags=["Settings"],
    )

    # ── WebSocket route (must be added directly, not via router) ───────────────
    @app.websocket("/ws/{project_id}/{session_id}")
    async def websocket_endpoint(
        websocket: WebSocket,
        project_id: str,
        session_id: str,
    ):
        """WebSocket endpoint for streaming agent steps during chat."""
        await websocket.accept()
        
        key = (project_id, session_id)
        
        if key not in websocket.active_connections:
            websocket.active_connections[key] = set()
        websocket.active_connections[key].add(websocket)
        
        logger.info(
            f"WebSocket connected | project={project_id} session={session_id} "
            f"total_connections={len(websocket.active_connections[key])}"
        )
        
        try:
            while True:
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=60.0
                    )
                    if data == "ping":
                        await websocket.send_text("pong")
                except asyncio.TimeoutError:
                    await websocket.send_text("ping")
                    
        except WebSocketDisconnect:
            logger.info(
                f"WebSocket disconnected | project={project_id} session={session_id}"
            )
        except Exception as exc:
            logger.error(
                f"WebSocket error | project={project_id} session={session_id} error={exc}"
            )
        finally:
            if key in websocket.active_connections:
                websocket.active_connections[key].discard(websocket)
                if not websocket.active_connections[key]:
                    del websocket.active_connections[key]
            await websocket.close()

    # Add active_connections to app.state for broadcast functions
    app.state.websocket_active_connections = {}

    # ── Root health check ──────────────────────────────────────────────────────
    @app.get("/", tags=["Health"])
    async def root():
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "running",
            "docs": "/docs" if settings.is_development else "disabled",
        }

    return app


# ── ASGI app instance ──────────────────────────────────────────────────────────
# uvicorn imports this object: `uvicorn app.main:app`
app = create_app()
