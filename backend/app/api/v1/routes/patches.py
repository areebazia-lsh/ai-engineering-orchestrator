"""
Patch management API for Phase 4.

Endpoints:
  - POST /patches/apply   : Apply a generated patch (after user approval)
  - POST /patches/rollback: Rollback a previously applied patch
  - GET  /patches/history : Get patch history for a file/project
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.database.supabase_client import get_supabase_client
from supabase import Client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/patches", tags=["patches"])


# ── Models ────────────────────────────────────────────────────────────────────

class PatchApplyRequest(BaseModel):
    project_id: str
    session_id: str
    file_path: str
    patch_content: str
    original_content: str
    metadata: dict = {}


class PatchRollbackRequest(BaseModel):
    patch_id: str
    reason: str = ""


class PatchHistoryResponse(BaseModel):
    id: str
    project_id: str
    session_id: str
    file_path: str
    original_hash: str
    patch_content: str
    applied_by: str
    applied_at: datetime
    rolled_back_at: datetime | None
    rollback_reason: str | None
    metadata: dict


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/apply")
async def apply_patch(
    request: PatchApplyRequest,
    client: Client = Depends(get_supabase_client),
) -> dict:
    """
    Apply a patch to a file and record it in history.
    
    This endpoint should be called after user approves the patch.
    """
    # Calculate hash of original content for verification
    content_hash = hashlib.sha256(request.original_content.encode()).hexdigest()
    
    # Apply patch to file (simplified - in production would write to disk)
    # For now, we just record the patch in database
    patch_record = {
        "project_id": request.project_id,
        "session_id": request.session_id,
        "file_path": request.file_path,
        "original_hash": content_hash,
        "patch_content": request.patch_content,
        "applied_by": "user",  # or "agent" if auto-applied
        "metadata": request.metadata,
    }
    
    try:
        result = client.table("patch_history").insert(patch_record).execute()
        patch_id = result.data[0]["id"] if result.data else None
        
        logger.info(
            f"Patch applied | id={patch_id} project={request.project_id} "
            f"file={request.file_path}"
        )
        
        return {
            "success": True,
            "patch_id": patch_id,
            "message": "Patch recorded (simulated - file not actually modified)"
        }
        
    except Exception as e:
        logger.error(f"Failed to record patch: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to apply patch: {e}")


@router.post("/rollback")
async def rollback_patch(
    request: PatchRollbackRequest,
    client: Client = Depends(get_supabase_client),
) -> dict:
    """
    Rollback a previously applied patch.
    """
    # Get the patch record
    try:
        result = client.table("patch_history").select("*").eq("id", request.patch_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Patch not found")
        
        patch = result.data[0]
        
        # Mark as rolled back
        update_data = {
            "rolled_back_at": datetime.utcnow().isoformat(),
            "rollback_reason": request.reason,
        }
        
        client.table("patch_history").update(update_data).eq("id", request.patch_id).execute()
        
        logger.info(f"Patch rolled back | id={request.patch_id} reason={request.reason}")
        
        return {
            "success": True,
            "message": "Patch marked as rolled back (simulated - file not actually restored)"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to rollback patch: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to rollback patch: {e}")


@router.get("/history/{project_id}")
async def get_patch_history(
    project_id: str,
    file_path: str | None = None,
    client: Client = Depends(get_supabase_client),
) -> List[PatchHistoryResponse]:
    """
    Get patch history for a project (optionally filtered by file).
    """
    try:
        query = client.table("patch_history").select("*").eq("project_id", project_id)
        
        if file_path:
            query = query.eq("file_path", file_path)
        
        query = query.order("applied_at", desc=True)
        result = query.execute()
        
        patches = []
        for patch in result.data:
            patches.append(PatchHistoryResponse(
                id=patch["id"],
                project_id=patch["project_id"],
                session_id=patch["session_id"],
                file_path=patch["file_path"],
                original_hash=patch["original_hash"],
                patch_content=patch["patch_content"],
                applied_by=patch["applied_by"],
                applied_at=datetime.fromisoformat(patch["applied_at"].replace("Z", "+00:00")),
                rolled_back_at=(
                    datetime.fromisoformat(patch["rolled_back_at"].replace("Z", "+00:00"))
                    if patch["rolled_back_at"] else None
                ),
                rollback_reason=patch["rollback_reason"],
                metadata=patch["metadata"] or {},
            ))
        
        return patches
        
    except Exception as e:
        logger.error(f"Failed to fetch patch history: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch patch history: {e}")