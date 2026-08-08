"""
WebSocket endpoint for streaming agent steps.

WebSocket URL: ws://localhost:8000/api/v1/ws/{project_id}/{session_id}

This endpoint streams:
  - agent_step events with partial step data
  - final_response events with the complete response

The frontend connects via lib/websocket.ts which handles:
  - Connecting with project_id and session_id
  - Listening for 'agent_step' and 'final_response' events
  - Closing connection on disconnect
"""

from __future__ import annotations

import logging
import asyncio
from typing import Any, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Active connections tracking ────────────────────────────────────────────────

# Maps (project_id, session_id) -> set of connected WebSocket connections
active_connections: Dict[tuple[str, str], set[WebSocket]] = {}


async def _websocket_endpoint(websocket: WebSocket, project_id: str, session_id: str):
    """
    WebSocket endpoint for streaming agent steps during chat.
    
    Clients connect with project_id and session_id.
    The connection remains open until the chat completes or times out.
    """
    await websocket.accept()
    
    key = (project_id, session_id)
    
    # Track this connection
    if key not in active_connections:
        active_connections[key] = set()
    active_connections[key].add(websocket)
    
    logger.info(
        f"WebSocket connected | project={project_id} session={session_id} "
        f"total_connections={len(active_connections[key])}"
    )
    
    try:
        while True:
            # Wait for messages (keep-alive / heartbeat)
            try:
                # Use a timeout to detect disconnected clients
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=60.0
                )
                # Optionally handle client messages (ping/pong)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Send keepalive
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
        # Cleanup
        if key in active_connections:
            active_connections[key].discard(websocket)
            if not active_connections[key]:
                del active_connections[key]
        await websocket.close()


# Add the WebSocket route
router.add_websocket_route(
    "/ws/{project_id}/{session_id}",
    _websocket_endpoint,
    name="websocket"
)


# ── Helper functions for sending messages ─────────────────────────────────────

async def broadcast_agent_step(project_id: str, session_id: str, step: Any):
    """Send agent step to all connected clients for this session."""
    key = (project_id, session_id)
    if key not in active_connections:
        return
    
    message = {"type": "agent_step", "step": step}
    disconnected = set()
    
    for conn in active_connections[key]:
        try:
            await conn.send_json(message)
        except Exception as exc:
            logger.warning(
                f"Failed to send agent_step | project={project_id} "
                f"session={session_id} error={exc}"
            )
            disconnected.add(conn)
    
    # Remove disconnected clients
    for conn in disconnected:
        active_connections[key].discard(conn)
    if not active_connections[key]:
        del active_connections[key]


async def broadcast_final_response(project_id: str, session_id: str, content: str):
    """Send final response to all connected clients for this session."""
    key = (project_id, session_id)
    if key not in active_connections:
        return
    
    message = {"type": "final_response", "content": content}
    disconnected = set()
    
    for conn in active_connections[key]:
        try:
            await conn.send_json(message)
        except Exception as exc:
            logger.warning(
                f"Failed to send final_response | project={project_id} "
                f"session={session_id} error={exc}"
            )
            disconnected.add(conn)
    
    # Remove disconnected clients
    for conn in disconnected:
        active_connections[key].discard(conn)
    if not active_connections[key]:
        del active_connections[key]
