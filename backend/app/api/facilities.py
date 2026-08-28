from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query, status
from app.db.supabase import (
    get_facility_by_id_db,
    get_facility_slots_db,
    list_facilities_db,
)
from app.schemas.facility import FacilityDetailResponse, FacilityListResponse
from app.schemas.slot import FacilitySlotsResponse

router = APIRouter(prefix="/facilities", tags=["facilities"])


@router.get(
    "",
    response_model=FacilityListResponse,
    summary="List all sports facilities",
)
async def list_facilities():
    try:
        facilities = await list_facilities_db()
        return {
            "ok": True,
            "count": len(facilities),
            "facilities": facilities,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"ok": False, "reason": str(exc)},
        )


@router.get(
    "/{facility_id}",
    response_model=FacilityDetailResponse,
    summary="Get facility details",
)
async def get_facility(facility_id: UUID):
    facility = await get_facility_by_id_db(facility_id)
    if not facility:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"ok": False, "reason": "facility_not_found"},
        )
    return {"ok": True, "facility": facility}


@router.get(
    "/{facility_id}/slots",
    response_model=FacilitySlotsResponse,
    summary="Get slot availability for a facility on a date",
)
async def get_facility_slots(
    facility_id: UUID,
    date: str = Query(..., description="Target date in YYYY-MM-DD format"),
):
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ok": False, "reason": "invalid_date_format"},
        )

    res = await get_facility_slots_db(facility_id=facility_id, target_date_str=date)
    if not res.get("ok"):
        reason = res.get("reason")
        if reason == "facility_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"ok": False, "reason": "facility_not_found"},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ok": False, "reason": reason},
        )

    return res
