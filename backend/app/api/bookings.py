import logging
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from pydantic import BaseModel
from app.core.dependencies import enforce_rate_limit, get_current_user_id
from app.db.supabase import (
    add_booking_members_db,
    call_book_slot_rpc,
    cancel_booking_db,
    check_in_booking_db,
    get_booking_checkin_info_db,
    get_booking_members_db,
    get_user_bookings_db,
    get_user_invitations_db,
    get_user_priority_eligibility_db,
    respond_booking_invitation_db,
)
from app.schemas.booking import CreateBookingRequest
from app.services.notifications import (
    notify_booking_cancellation,
    notify_booking_confirmation,
)

logger = logging.getLogger("lockin.bookings")

router = APIRouter(prefix="/bookings", tags=["bookings"])


class CheckInRequest(BaseModel):
    checkin_token: UUID


class AddMembersRequest(BaseModel):
    member_user_ids: List[UUID]


class RespondInvitationRequest(BaseModel):
    response: str  # "confirmed" or "declined"


@router.get(
    "/me",
    summary="Get authenticated student's bookings",
    responses={
        200: {"description": "List of student's upcoming and past bookings"},
        401: {"description": "Missing or invalid authentication credentials"},
    },
)
async def get_my_bookings(
    user_id: UUID = Depends(get_current_user_id),
):
    """
    Returns all upcoming, past, and cancelled bookings belonging to the authenticated student.
    """
    try:
        bookings = await get_user_bookings_db(user_id=user_id)
        return {
            "ok": True,
            "count": len(bookings),
            "user_id": str(user_id),
            "bookings": bookings,
        }
    except Exception as exc:
        logger.error(f"Error fetching user bookings: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"ok": False, "reason": "internal_error"},
        )


@router.get(
    "/priority/eligibility/me",
    summary="Get authenticated student's priority eligibility status",
)
async def get_my_priority_eligibility(
    user_id: UUID = Depends(get_current_user_id),
):
    try:
        eligibilities = await get_user_priority_eligibility_db(user_id=user_id)
        return {
            "ok": True,
            "user_id": str(user_id),
            "is_priority_eligible": len(eligibilities) > 0,
            "eligibilities": eligibilities,
        }
    except Exception as exc:
        logger.error(f"Error fetching priority eligibility: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"ok": False, "reason": "internal_error"},
        )


@router.get(
    "/invitations/me",
    summary="Get authenticated student's pending group invitations",
)
async def get_my_invitations(
    user_id: UUID = Depends(get_current_user_id),
):
    try:
        invitations = await get_user_invitations_db(user_id=user_id)
        return {
            "ok": True,
            "count": len(invitations),
            "user_id": str(user_id),
            "invitations": invitations,
        }
    except Exception as exc:
        logger.error(f"Error fetching user invitations: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"ok": False, "reason": "internal_error"},
        )


@router.post(
    "/invitations/{member_id}/respond",
    summary="Respond to a group booking invitation",
)
async def respond_invitation(
    member_id: UUID,
    req: RespondInvitationRequest,
    user_id: UUID = Depends(get_current_user_id),
):
    res = await respond_booking_invitation_db(
        member_id=member_id,
        user_id=user_id,
        response_status=req.response,
    )
    if not res.get("ok"):
        reason = res.get("reason")
        if reason == "invitation_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"ok": False, "reason": "invitation_not_found"},
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
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a confirmed booking (Atomic RPC path)",
)
async def create_booking(
    req: CreateBookingRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
):
    """
    Single authoritative booking write path.
    Calls PostgreSQL `book_slot` RPC function directly.
    """
    await enforce_rate_limit(user_id)
    logger.info(
        f"Booking attempt: facility={req.facility_id}, start={req.slot_start}, user={user_id}, idempotency_key={req.idempotency_key}"
    )

    try:
        rpc_res = await call_book_slot_rpc(
            facility_id=req.facility_id,
            slot_start=req.slot_start.isoformat(),
            slot_end=req.slot_end.isoformat(),
            user_id=user_id,
            idempotency_key=req.idempotency_key,
        )
    except Exception as exc:
        logger.error(f"PostgreSQL RPC execution error: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"ok": False, "reason": "internal_error"},
        )

    ok = rpc_res.get("ok", False)
    reason = rpc_res.get("reason", "unknown")

    logger.info(f"Booking result: ok={ok}, reason={reason}, booking_id={rpc_res.get('booking_id')}")

    if ok:
        if reason == "idempotent_replay":
            response.status_code = status.HTTP_200_OK
        else:
            response.status_code = status.HTTP_201_CREATED
            if rpc_res.get("booking"):
                background_tasks.add_task(
                    notify_booking_confirmation,
                    booking=rpc_res["booking"],
                    user_email="student@iitg.ac.in",
                )
        return rpc_res

    # Error handling & HTTP status classification
    if reason in ("slot_taken", "booking_window_not_open", "facility_blocked"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"ok": False, "reason": reason},
        )
    elif reason == "idempotency_key_reused":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ok": False, "reason": "idempotency_key_reused"},
        )
    elif reason in ("invalid_time_range", "slot_in_past"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"ok": False, "reason": reason},
        )
    elif reason == "facility_not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"ok": False, "reason": "facility_not_found"},
        )
    elif reason == "facility_not_open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ok": False, "reason": "facility_not_open"},
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ok": False, "reason": reason},
        )


@router.delete(
    "/{booking_id}",
    status_code=status.HTTP_200_OK,
    summary="Cancel a confirmed booking",
)
async def cancel_booking(
    booking_id: UUID,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
):
    logger.info(f"Cancellation attempt: booking_id={booking_id}, user={user_id}")

    try:
        res = await cancel_booking_db(booking_id=booking_id, user_id=user_id)
    except Exception as exc:
        logger.error(f"Cancellation error: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"ok": False, "reason": "internal_error"},
        )

    if not res.get("ok"):
        reason = res.get("reason")
        if reason == "not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"ok": False, "reason": "not_found"},
            )
        elif reason == "unauthorized":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"ok": False, "reason": "unauthorized"},
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"ok": False, "reason": reason},
            )

    if res.get("reason") == "cancelled":
        background_tasks.add_task(
            notify_booking_cancellation,
            booking_id=str(booking_id),
            user_id=str(user_id),
            user_email="student@iitg.ac.in",
        )

    return res


@router.get(
    "/{booking_id}/checkin",
    summary="Get check-in QR token details for booking owner",
)
async def get_checkin_info(
    booking_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
):
    info = await get_booking_checkin_info_db(booking_id, user_id)
    if not info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"ok": False, "reason": "booking_not_found"},
        )
    return {"ok": True, "booking": info}


@router.post(
    "/{booking_id}/checkin",
    summary="Execute QR check-in for booking",
)
async def execute_checkin(
    booking_id: UUID,
    req: CheckInRequest,
    user_id: UUID = Depends(get_current_user_id),
):
    logger.info(f"Check-in attempt: booking={booking_id}, user={user_id}")

    try:
        res = await check_in_booking_db(booking_id=booking_id, user_id=user_id, checkin_token=req.checkin_token)
    except Exception as exc:
        logger.error(f"Check-in execution error: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"ok": False, "reason": "internal_error"},
        )

    if not res.get("ok"):
        reason = res.get("reason")
        if reason == "booking_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"ok": False, "reason": "booking_not_found"},
            )
        elif reason == "unauthorized":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"ok": False, "reason": "unauthorized"},
            )
        elif reason == "invalid_token":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"ok": False, "reason": "invalid_token"},
            )
        elif reason == "too_early":
            msg = res.get("message") or "⚠️ Warning: Check-in is only permitted starting 15 minutes before your reserved slot time."
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "ok": False,
                    "reason": "too_early",
                    "message": msg,
                    "minutes_remaining": res.get("minutes_remaining"),
                    "window_start": res.get("window_start"),
                },
            )
        elif reason in ("checkin_window_expired", "checkin_window_closed"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"ok": False, "reason": reason, "message": "Check-in window has closed or expired."},
            )
        elif reason == "booking_not_confirmed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"ok": False, "reason": "booking_not_confirmed"},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ok": False, "reason": reason},
        )

    return res


@router.post(
    "/{booking_id}/members",
    summary="Invite team members to a group booking",
)
async def add_members(
    booking_id: UUID,
    req: AddMembersRequest,
    user_id: UUID = Depends(get_current_user_id),
):
    res = await add_booking_members_db(
        booking_id=booking_id,
        host_id=user_id,
        member_user_ids=req.member_user_ids,
    )
    if not res.get("ok"):
        reason = res.get("reason")
        if reason == "booking_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"ok": False, "reason": "booking_not_found"},
            )
        elif reason == "unauthorized":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"ok": False, "reason": "unauthorized"},
            )
        elif reason == "group_size_exceeded":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"ok": False, "reason": "group_size_exceeded", "max_allowed": res.get("max_allowed")},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"ok": False, "reason": reason},
        )
    return res


@router.get(
    "/{booking_id}/members",
    summary="List all members of a group booking",
)
async def get_members(
    booking_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
):
    members = await get_booking_members_db(booking_id)
    return {"ok": True, "count": len(members), "booking_id": str(booking_id), "members": members}
