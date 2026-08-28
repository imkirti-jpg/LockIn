import logging
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from app.core.dependencies import get_current_user_id
from app.db.supabase import (
    create_facility_block_db,
    delete_facility_block_db,
    get_admin_analytics_db,
    get_facility_by_id_db,
    get_user_roles_db,
    list_facilities_db,
    list_facility_blocks_db,
    update_facility_status_db,
    verify_admin_access_db,
)

logger = logging.getLogger("lockin.admin")

router = APIRouter(prefix="/admin", tags=["admin"])


class CreateBlockRequest(BaseModel):
    start_time: str
    end_time: str
    reason: str
    block_type: str = "maintenance"


class UpdateFacilityStatusRequest(BaseModel):
    status: str  # open / maintenance / closed


@router.get("/me/roles", summary="Get authenticated student/admin roles")
async def get_my_roles(
    user_id: UUID = Depends(get_current_user_id),
):
    roles = await get_user_roles_db(user_id)
    return {"ok": True, "user_id": str(user_id), "roles": roles}


@router.get("/facilities", summary="Get admin overview of all facilities and blocks")
async def get_admin_facilities(
    user_id: UUID = Depends(get_current_user_id),
):
    auth = await verify_admin_access_db(user_id)
    if not auth["authorized"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"ok": False, "reason": "unauthorized_admin"},
        )

    facilities = await list_facilities_db()
    blocks = await list_facility_blocks_db()

    return {
        "ok": True,
        "count": len(facilities),
        "admin_role": auth.get("role"),
        "facilities": facilities,
        "active_blocks": blocks,
    }


@router.patch("/facilities/{facility_id}/status", summary="Update facility status (open/maintenance/closed)")
async def set_facility_status(
    facility_id: UUID,
    req: UpdateFacilityStatusRequest,
    user_id: UUID = Depends(get_current_user_id),
):
    res = await update_facility_status_db(facility_id=facility_id, new_status=req.status, user_id=user_id)
    if not res.get("ok"):
        reason = res.get("reason")
        if reason == "unauthorized":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"ok": False, "reason": "unauthorized"},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ok": False, "reason": reason},
        )
    return res


@router.get("/facilities/{facility_id}/blocks", summary="Get active blocks for a facility")
async def get_facility_blocks(
    facility_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
):
    auth = await verify_admin_access_db(user_id, facility_id)
    if not auth["authorized"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"ok": False, "reason": "unauthorized"},
        )

    blocks = await list_facility_blocks_db(facility_id=facility_id)
    return {"ok": True, "facility_id": str(facility_id), "blocks": blocks}


@router.post("/facilities/{facility_id}/blocks", summary="Create administrative facility block")
async def create_block(
    facility_id: UUID,
    req: CreateBlockRequest,
    user_id: UUID = Depends(get_current_user_id),
):
    res = await create_facility_block_db(
        facility_id=facility_id,
        start_time=req.start_time,
        end_time=req.end_time,
        reason=req.reason,
        block_type=req.block_type,
        user_id=user_id,
    )
    if not res.get("ok"):
        reason = res.get("reason")
        if reason == "unauthorized":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"ok": False, "reason": "unauthorized"},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ok": False, "reason": reason},
        )
    return res


@router.delete("/blocks/{block_id}", summary="Deactivate / remove a facility block")
async def remove_block(
    block_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
):
    res = await delete_facility_block_db(block_id=block_id, user_id=user_id)
    if not res.get("ok"):
        reason = res.get("reason")
        if reason == "block_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"ok": False, "reason": "block_not_found"},
            )
        elif reason == "unauthorized":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"ok": False, "reason": "unauthorized"},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ok": False, "reason": reason},
        )
    return res


@router.get("/analytics", summary="Get operational analytics & utilization metrics")
async def get_analytics(
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    user_id: UUID = Depends(get_current_user_id),
):
    auth = await verify_admin_access_db(user_id)
    if not auth["authorized"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"ok": False, "reason": "unauthorized"},
        )

    if not from_date:
        from_date = "2026-08-01"
    if not to_date:
        to_date = "2026-08-31"

    res = await get_admin_analytics_db(from_date=from_date, to_date=to_date)
    return res
