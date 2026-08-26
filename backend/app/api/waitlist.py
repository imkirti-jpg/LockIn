import logging
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.dependencies import get_current_user_id
from app.db.supabase import (
    cancel_waitlist_entry_db,
    claim_waitlist_slot_db,
    get_user_waitlists_db,
    get_waitlist_entry_by_id_db,
    join_waitlist_db,
)
from app.schemas.waitlist import ClaimWaitlistRequest, JoinWaitlistRequest

logger = logging.getLogger("lockin.waitlist")

router = APIRouter(prefix="/waitlist", tags=["waitlist"])


@router.post(
    "/{facility_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Join waitlist for an occupied slot",
)
async def join_waitlist(
    facility_id: UUID,
    req: JoinWaitlistRequest,
    user_id: UUID = Depends(get_current_user_id),
):
    """
    Joins FIFO waitlist if target slot is occupied by a confirmed booking.
    Rejects if slot is open (returns slot_available).
    """
    logger.info(f"Join waitlist request: facility={facility_id}, start={req.slot_start}, user={user_id}")

    try:
        res = await join_waitlist_db(
            facility_id=facility_id,
            slot_start=req.slot_start.isoformat(),
            slot_end=req.slot_end.isoformat(),
            user_id=user_id,
        )
    except Exception as exc:
        logger.error(f"Error joining waitlist: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"ok": False, "reason": "internal_error"},
        )

    if not res.get("ok"):
        reason = res.get("reason")
        if reason == "slot_available":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"ok": False, "reason": "slot_available", "message": "Slot is currently available for normal booking"},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ok": False, "reason": reason},
        )

    return res


@router.get(
    "/me",
    summary="Get authenticated student's waitlist entries",
)
async def get_my_waitlists(
    user_id: UUID = Depends(get_current_user_id),
):
    try:
        entries = await get_user_waitlists_db(user_id=user_id)
        return {
            "ok": True,
            "count": len(entries),
            "user_id": str(user_id),
            "waitlist_entries": entries,
        }
    except Exception as exc:
        logger.error(f"Error fetching user waitlists: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"ok": False, "reason": "internal_error"},
        )


@router.get(
    "/{entry_id}",
    summary="Get specific waitlist entry detail",
)
async def get_waitlist_entry(
    entry_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
):
    entry = await get_waitlist_entry_by_id_db(entry_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"ok": False, "reason": "entry_not_found"},
        )

    if str(entry["user_id"]) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"ok": False, "reason": "unauthorized"},
        )

    return {"ok": True, "waitlist_entry": entry}


@router.delete(
    "/{entry_id}",
    summary="Cancel a waitlist entry",
)
async def cancel_waitlist_entry(
    entry_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
):
    res = await cancel_waitlist_entry_db(entry_id=entry_id, user_id=user_id)
    if not res.get("ok"):
        reason = res.get("reason")
        if reason == "entry_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"ok": False, "reason": "entry_not_found"},
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


@router.post(
    "/{entry_id}/claim",
    status_code=status.HTTP_200_OK,
    summary="Claim offered waitlist slot",
)
async def claim_waitlist_slot(
    entry_id: UUID,
    req: ClaimWaitlistRequest,
    user_id: UUID = Depends(get_current_user_id),
):
    """
    Atomically claims an offered waitlist slot using the Phase 2 book_slot RPC mechanism.
    """
    logger.info(f"Claim request: entry={entry_id}, user={user_id}, ikey={req.idempotency_key}")

    try:
        res = await claim_waitlist_slot_db(
            entry_id=entry_id,
            user_id=user_id,
            idempotency_key=req.idempotency_key,
        )
    except Exception as exc:
        logger.error(f"Error claiming waitlist slot: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"ok": False, "reason": "internal_error"},
        )

    if not res.get("ok"):
        reason = res.get("reason")
        if reason == "entry_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"ok": False, "reason": "entry_not_found"},
            )
        elif reason == "unauthorized":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"ok": False, "reason": "unauthorized"},
            )
        elif reason == "claim_expired":
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail={"ok": False, "reason": "claim_expired"},
            )
        elif reason == "slot_taken":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"ok": False, "reason": "slot_taken"},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ok": False, "reason": reason},
        )

    return res
