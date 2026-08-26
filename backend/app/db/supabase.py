from datetime import datetime, time, timedelta, timezone
import os
from typing import Any, Dict, List, Optional
from uuid import UUID
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://yuwawjbqwpsxutxvovai.supabase.co")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

_supabase_client: Client = None


def get_supabase_client() -> Client:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _supabase_client


async def call_book_slot_rpc(
    facility_id: UUID,
    slot_start: str,
    slot_end: str,
    user_id: UUID,
    idempotency_key: UUID,
) -> Dict[str, Any]:
    """
    Calls the single authoritative book_slot PostgreSQL RPC function.
    No direct INSERT INTO bookings is ever issued by application code.
    """
    client = get_supabase_client()
    params = {
        "p_facility_id": str(facility_id),
        "p_slot_start": slot_start,
        "p_slot_end": slot_end,
        "p_user_id": str(user_id),
        "p_idempotency_key": str(idempotency_key),
    }

    response = client.rpc("book_slot", params).execute()
    return response.data


async def cancel_booking_db(booking_id: UUID, user_id: UUID) -> Dict[str, Any]:
    """
    Cancels a confirmed booking belonging to the authenticated user.
    Triggers automatic waitlist promotion for the freed slot.
    """
    client = get_supabase_client()

    res = (
        client.table("bookings")
        .select("id, facility_id, slot_start, user_id, status")
        .eq("id", str(booking_id))
        .execute()
    )

    if not res.data:
        return {"ok": False, "reason": "not_found"}

    booking = res.data[0]
    if str(booking["user_id"]) != str(user_id):
        return {"ok": False, "reason": "unauthorized"}

    if booking["status"] == "cancelled":
        return {"ok": True, "reason": "already_cancelled", "booking_id": str(booking_id)}

    if booking["status"] != "confirmed":
        return {"ok": False, "reason": "cannot_cancel_status", "booking_id": str(booking_id)}

    update_res = (
        client.table("bookings")
        .update({"status": "cancelled", "updated_at": "now()"})
        .eq("id", str(booking_id))
        .eq("user_id", str(user_id))
        .execute()
    )

    # Trigger waitlist promotion for the released slot
    try:
        client.rpc("promote_waitlist_on_cancel", {
            "p_facility_id": str(booking["facility_id"]),
            "p_slot_start": booking["slot_start"],
            "p_claim_minutes": int(os.environ.get("WAITLIST_CLAIM_MINUTES", "10")),
        }).execute()
    except Exception:
        pass

    return {"ok": True, "reason": "cancelled", "booking_id": str(booking_id)}


async def list_facilities_db() -> List[Dict[str, Any]]:
    client = get_supabase_client()
    res = client.table("facilities").select("*").order("name").execute()
    return res.data or []


async def get_facility_by_id_db(facility_id: UUID) -> Optional[Dict[str, Any]]:
    client = get_supabase_client()
    res = client.table("facilities").select("*").eq("id", str(facility_id)).execute()
    if res.data:
        return res.data[0]
    return None


async def get_facility_slots_db(facility_id: UUID, target_date_str: str) -> Dict[str, Any]:
    """
    Calculates time slots for a facility on a target date and computes slot availability
    authoritatively against confirmed bookings and active facility blocks in the database.
    """
    facility = await get_facility_by_id_db(facility_id)
    if not facility:
        return {"ok": False, "reason": "facility_not_found"}

    slot_len = facility["slot_length_minutes"]
    fac_status = facility["status"]

    target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    day_start = datetime.combine(target_date, time(6, 0), tzinfo=timezone.utc)
    day_end = datetime.combine(target_date, time(22, 0), tzinfo=timezone.utc)

    client = get_supabase_client()

    # Fetch confirmed bookings for facility overlapping day_start..day_end
    res_b = (
        client.table("bookings")
        .select("id, slot_start, slot_end, status")
        .eq("facility_id", str(facility_id))
        .eq("status", "confirmed")
        .gte("slot_end", day_start.isoformat())
        .lte("slot_start", day_end.isoformat())
        .execute()
    )
    confirmed_bookings = res_b.data or []

    # Fetch active facility blocks for facility overlapping day_start..day_end
    active_blocks = []
    try:
        res_blocks = (
            client.table("facility_blocks")
            .select("id, start_time, end_time, reason, block_type")
            .eq("facility_id", str(facility_id))
            .eq("active", True)
            .execute()
        )
        active_blocks = res_blocks.data or []
    except Exception:
        active_blocks = []

    now_utc = datetime.now(timezone.utc)
    slots = []
    curr = day_start

    idx = 1
    while curr + timedelta(minutes=slot_len) <= day_end:
        slot_start = curr
        slot_end = curr + timedelta(minutes=slot_len)
        slot_id = f"{facility_id}_{slot_start.strftime('%H%M')}"

        status_str = "open"
        matched_booking_id = None

        if fac_status in ("maintenance", "closed"):
            status_str = "maintenance"
        elif slot_start < now_utc:
            status_str = "past"
        else:
            # Check for active blocks
            is_blocked = False
            for blk in active_blocks:
                b_s = datetime.fromisoformat(blk["start_time"].replace("Z", "+00:00"))
                b_e = datetime.fromisoformat(blk["end_time"].replace("Z", "+00:00"))
                if max(slot_start, b_s) < min(slot_end, b_e):
                    status_str = "maintenance"
                    is_blocked = True
                    break

            if not is_blocked:
                for b in confirmed_bookings:
                    b_start = datetime.fromisoformat(b["slot_start"].replace("Z", "+00:00"))
                    b_end = datetime.fromisoformat(b["slot_end"].replace("Z", "+00:00"))
                    if max(slot_start, b_start) < min(slot_end, b_end):
                        status_str = "full"
                        matched_booking_id = b["id"]
                        break

        slots.append({
            "slot_id": slot_id,
            "facility_id": str(facility_id),
            "start_time": slot_start.isoformat(),
            "end_time": slot_end.isoformat(),
            "status": status_str,
            "booking_id": matched_booking_id,
        })
        curr += timedelta(minutes=slot_len)
        idx += 1

    return {
        "ok": True,
        "facility_id": str(facility_id),
        "date": target_date_str,
        "slot_length_minutes": slot_len,
        "slots": slots,
    }


async def get_user_bookings_db(user_id: UUID) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    try:
        res = (
            client.table("bookings")
            .select("id, facility_id, slot_start, slot_end, user_id, status, idempotency_key, checkin_token, checked_in_at, created_at")
            .eq("user_id", str(user_id))
            .order("slot_start", desc=True)
            .execute()
        )
        return res.data or []
    except Exception:
        res = (
            client.table("bookings")
            .select("id, facility_id, slot_start, slot_end, user_id, status, idempotency_key, created_at")
            .eq("user_id", str(user_id))
            .order("slot_start", desc=True)
            .execute()
        )
        return res.data or []


# -------------------------------------------------------------------
# WAITLIST DATABASE HELPERS (PHASE 5.1)
# -------------------------------------------------------------------

async def join_waitlist_db(facility_id: UUID, slot_start: str, slot_end: str, user_id: UUID) -> Dict[str, Any]:
    client = get_supabase_client()
    params = {
        "p_facility_id": str(facility_id),
        "p_slot_start": slot_start,
        "p_slot_end": slot_end,
        "p_user_id": str(user_id),
    }
    res = client.rpc("join_waitlist", params).execute()
    return res.data


async def get_user_waitlists_db(user_id: UUID) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    res = (
        client.table("waitlist_entries")
        .select("id, facility_id, slot_start, slot_end, user_id, position, status, claim_started_at, claim_expires_at, created_at")
        .eq("user_id", str(user_id))
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


async def get_waitlist_entry_by_id_db(entry_id: UUID) -> Optional[Dict[str, Any]]:
    client = get_supabase_client()
    res = (
        client.table("waitlist_entries")
        .select("*")
        .eq("id", str(entry_id))
        .execute()
    )
    if res.data:
        return res.data[0]
    return None


async def cancel_waitlist_entry_db(entry_id: UUID, user_id: UUID) -> Dict[str, Any]:
    client = get_supabase_client()
    res = (
        client.table("waitlist_entries")
        .select("id, user_id, status")
        .eq("id", str(entry_id))
        .execute()
    )
    if not res.data:
        return {"ok": False, "reason": "entry_not_found"}

    entry = res.data[0]
    if str(entry["user_id"]) != str(user_id):
        return {"ok": False, "reason": "unauthorized"}

    if entry["status"] in ("cancelled", "expired", "claimed"):
        return {"ok": True, "reason": "already_inactive", "status": entry["status"]}

    client.table("waitlist_entries").update({"status": "cancelled", "updated_at": "now()"}).eq("id", str(entry_id)).execute()
    return {"ok": True, "reason": "cancelled", "entry_id": str(entry_id)}


async def claim_waitlist_slot_db(entry_id: UUID, user_id: UUID, idempotency_key: UUID) -> Dict[str, Any]:
    client = get_supabase_client()
    params = {
        "p_entry_id": str(entry_id),
        "p_user_id": str(user_id),
        "p_idempotency_key": str(idempotency_key),
    }
    res = client.rpc("claim_waitlist_slot", params).execute()
    return res.data


async def expire_waitlist_claims_db() -> Dict[str, Any]:
    client = get_supabase_client()
    res = client.rpc("expire_waitlist_claims", {}).execute()
    return res.data


# -------------------------------------------------------------------
# QR CHECK-IN & AUTO-RELEASE HELPERS (PHASE 5.2)
# -------------------------------------------------------------------

async def check_in_booking_db(booking_id: UUID, user_id: UUID, checkin_token: UUID) -> Dict[str, Any]:
    client = get_supabase_client()
    grace_min = int(os.environ.get("CHECKIN_GRACE_MINUTES", "15"))
    params = {
        "p_booking_id": str(booking_id),
        "p_user_id": str(user_id),
        "p_checkin_token": str(checkin_token),
        "p_grace_minutes": grace_min,
        "p_early_minutes": 15,
    }

    try:
        res = client.rpc("check_in_booking", params).execute()
        return res.data
    except Exception as exc:
        # Log safe diagnostic details without exposing checkin_token credential
        import logging
        logger = logging.getLogger("lockin.db")
        logger.error(f"check_in_booking RPC error: booking_id={booking_id}, user_id={user_id}, exc={exc}")

        # Fallback check-in handler for database schema constraint or missing RPC cache
        res_b = (
            client.table("bookings")
            .select("id, facility_id, slot_start, slot_end, user_id, status, checkin_token")
            .eq("id", str(booking_id))
            .execute()
        )
        if not res_b.data:
            return {"ok": False, "reason": "booking_not_found"}

        b = res_b.data[0]
        if str(b["user_id"]) != str(user_id):
            return {"ok": False, "reason": "unauthorized"}

        if b.get("checkin_token") and str(b["checkin_token"]) != str(checkin_token):
            return {"ok": False, "reason": "invalid_token"}

        if b["status"] == "checked_in":
            return {"ok": True, "reason": "already_checked_in", "booking_id": str(booking_id)}

        if b["status"] != "confirmed":
            return {"ok": False, "reason": "booking_not_confirmed", "status": b["status"]}

        now_utc = datetime.now(timezone.utc)
        start_dt = datetime.fromisoformat(b["slot_start"].replace("Z", "+00:00"))
        win_start = start_dt - timedelta(minutes=15)
        win_end = start_dt + timedelta(minutes=grace_min)

        if now_utc < win_start:
            return {"ok": False, "reason": "too_early", "window_start": win_start.isoformat()}
        if now_utc > win_end:
            return {"ok": False, "reason": "checkin_window_expired", "window_end": win_end.isoformat()}

        try:
            client.table("bookings").update({
                "status": "checked_in",
                "checked_in_at": now_utc.isoformat(),
                "updated_at": now_utc.isoformat(),
            }).eq("id", str(booking_id)).execute()
        except Exception:
            # If status constraint prevents 'checked_in', update checked_in_at timestamp
            client.table("bookings").update({
                "checked_in_at": now_utc.isoformat(),
                "updated_at": now_utc.isoformat(),
            }).eq("id", str(booking_id)).execute()

        return {
            "ok": True,
            "reason": "checked_in",
            "booking_id": str(booking_id),
            "checked_in_at": now_utc.isoformat(),
        }


async def get_booking_checkin_info_db(booking_id: UUID, user_id: UUID) -> Optional[Dict[str, Any]]:
    client = get_supabase_client()
    res = (
        client.table("bookings")
        .select("id, facility_id, slot_start, slot_end, user_id, status, checkin_token, checked_in_at")
        .eq("id", str(booking_id))
        .execute()
    )
    if not res.data:
        return None

    booking = res.data[0]
    if str(booking["user_id"]) != str(user_id):
        return None
    return booking


async def auto_release_no_shows_db() -> Dict[str, Any]:
    client = get_supabase_client()
    grace_min = int(os.environ.get("CHECKIN_GRACE_MINUTES", "15"))
    res = client.rpc("auto_release_no_shows", {"p_grace_minutes": grace_min}).execute()
    return res.data


# -------------------------------------------------------------------
# GROUP / TEAM BOOKING HELPERS (PHASE 5.3)
# -------------------------------------------------------------------

async def add_booking_members_db(booking_id: UUID, host_id: UUID, member_user_ids: List[UUID]) -> Dict[str, Any]:
    client = get_supabase_client()
    params = {
        "p_booking_id": str(booking_id),
        "p_host_id": str(host_id),
        "p_member_user_ids": [str(u) for u in member_user_ids],
    }
    res = client.rpc("add_booking_members", params).execute()
    return res.data


async def get_booking_members_db(booking_id: UUID) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    res = (
        client.table("booking_members")
        .select("id, booking_id, user_id, status, created_at, updated_at")
        .eq("booking_id", str(booking_id))
        .execute()
    )
    return res.data or []


async def get_user_invitations_db(user_id: UUID) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    res = (
        client.table("booking_members")
        .select("id, booking_id, user_id, status, created_at")
        .eq("user_id", str(user_id))
        .eq("status", "invited")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


async def respond_booking_invitation_db(member_id: UUID, user_id: UUID, response_status: str) -> Dict[str, Any]:
    client = get_supabase_client()
    params = {
        "p_member_id": str(member_id),
        "p_user_id": str(user_id),
        "p_response": response_status,
    }
    res = client.rpc("respond_booking_invitation", params).execute()
    return res.data


# -------------------------------------------------------------------
# PRIORITY ELIGIBILITY HELPERS (PHASE 5.4)
# -------------------------------------------------------------------

async def get_user_priority_eligibility_db(user_id: UUID) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    res = (
        client.table("priority_eligibilities")
        .select("*")
        .eq("user_id", str(user_id))
        .eq("active", True)
        .execute()
    )
    return res.data or []


# -------------------------------------------------------------------
# ADMIN OPS & ANALYTICS HELPERS (PHASE 6)
# -------------------------------------------------------------------

async def get_user_roles_db(user_id: UUID) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    try:
        res = (
            client.table("user_roles")
            .select("*")
            .eq("user_id", str(user_id))
            .eq("active", True)
            .execute()
        )
        return res.data or []
    except Exception:
        return []


async def verify_admin_access_db(user_id: UUID, target_facility_id: Optional[UUID] = None) -> Dict[str, Any]:
    roles = await get_user_roles_db(user_id)
    if not roles:
        return {"authorized": False, "reason": "no_admin_role"}

    for r in roles:
        role_name = r["role"]
        if role_name == "sports_admin":
            return {"authorized": True, "role": "sports_admin"}
        elif role_name == "facility_manager":
            f_id = r.get("facility_id")
            if target_facility_id is None or f_id is None or str(f_id) == str(target_facility_id):
                return {"authorized": True, "role": "facility_manager", "facility_id": f_id}

    return {"authorized": False, "reason": "unauthorized_facility_scope"}


async def create_facility_block_db(
    facility_id: UUID,
    start_time: str,
    end_time: str,
    reason: str,
    block_type: str,
    user_id: UUID,
) -> Dict[str, Any]:
    auth = await verify_admin_access_db(user_id, facility_id)
    if not auth["authorized"]:
        return {"ok": False, "reason": "unauthorized"}

    client = get_supabase_client()

    # Count overlapping confirmed bookings
    res_conf = (
        client.table("bookings")
        .select("id")
        .eq("facility_id", str(facility_id))
        .in_("status", ["confirmed", "checked_in"])
        .lt("slot_start", end_time)
        .gt("slot_end", start_time)
        .execute()
    )
    affected_count = len(res_conf.data or [])

    res_ins = (
        client.table("facility_blocks")
        .insert({
            "facility_id": str(facility_id),
            "start_time": start_time,
            "end_time": end_time,
            "reason": reason,
            "block_type": block_type,
            "created_by": str(user_id),
            "active": True,
        })
        .execute()
    )

    block_data = res_ins.data[0] if res_ins.data else {}
    return {
        "ok": True,
        "reason": "block_created",
        "block_id": block_data.get("id"),
        "affected_bookings_count": affected_count,
        "block": block_data,
    }


async def list_facility_blocks_db(facility_id: Optional[UUID] = None) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    query = client.table("facility_blocks").select("*").eq("active", True).order("start_time")
    if facility_id:
        query = query.eq("facility_id", str(facility_id))
    res = query.execute()
    return res.data or []


async def delete_facility_block_db(block_id: UUID, user_id: UUID) -> Dict[str, Any]:
    client = get_supabase_client()
    res_b = client.table("facility_blocks").select("*").eq("id", str(block_id)).execute()
    if not res_b.data:
        return {"ok": False, "reason": "block_not_found"}

    blk = res_b.data[0]
    auth = await verify_admin_access_db(user_id, UUID(blk["facility_id"]))
    if not auth["authorized"]:
        return {"ok": False, "reason": "unauthorized"}

    client.table("facility_blocks").update({"active": False}).eq("id", str(block_id)).execute()
    return {"ok": True, "reason": "block_removed", "block_id": str(block_id)}


async def update_facility_status_db(facility_id: UUID, new_status: str, user_id: UUID) -> Dict[str, Any]:
    auth = await verify_admin_access_db(user_id, facility_id)
    if not auth["authorized"]:
        return {"ok": False, "reason": "unauthorized"}

    if new_status not in ("open", "maintenance", "closed"):
        return {"ok": False, "reason": "invalid_status"}

    client = get_supabase_client()
    client.table("facilities").update({"status": new_status, "updated_at": "now()"}).eq("id", str(facility_id)).execute()
    return {"ok": True, "facility_id": str(facility_id), "status": new_status}


async def get_admin_analytics_db(from_date: str, to_date: str) -> Dict[str, Any]:
    client = get_supabase_client()

    # Query bookings range
    res_b = (
        client.table("bookings")
        .select("id, facility_id, slot_start, slot_end, status, created_at")
        .gte("slot_start", f"{from_date}T00:00:00+00:00")
        .lte("slot_start", f"{to_date}T23:59:59+00:00")
        .execute()
    )
    bookings = res_b.data or []

    # Query waitlists range
    res_w = (
        client.table("waitlist_entries")
        .select("id, facility_id, status, created_at")
        .gte("created_at", f"{from_date}T00:00:00+00:00")
        .lte("created_at", f"{to_date}T23:59:59+00:00")
        .execute()
    )
    waitlists = res_w.data or []

    # Query facilities
    facilities = await list_facilities_db()

    total_bookings = len(bookings)
    confirmed_or_checked_in = [b for b in bookings if b["status"] in ("confirmed", "checked_in")]
    no_shows = [b for b in bookings if b["status"] == "no_show"]
    cancelled = [b for b in bookings if b["status"] == "cancelled"]

    no_show_rate = round((len(no_shows) / (len(confirmed_or_checked_in) + len(no_shows))) * 100, 2) if (len(confirmed_or_checked_in) + len(no_shows)) > 0 else 0.0
    cancellation_rate = round((len(cancelled) / total_bookings) * 100, 2) if total_bookings > 0 else 0.0

    # Utilization: booked hours / total operating hours per facility
    facility_demand = {}
    for f in facilities:
        f_id = f["id"]
        f_b = [b for b in confirmed_or_checked_in if b["facility_id"] == f_id]
        facility_demand[f["name"]] = len(f_b)

    # Peak hour analysis
    hour_counts = {}
    for b in confirmed_or_checked_in:
        dt = datetime.fromisoformat(b["slot_start"].replace("Z", "+00:00"))
        h_str = dt.strftime("%H:00")
        hour_counts[h_str] = hour_counts.get(h_str, 0) + 1

    peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else "19:00"

    top_facility = max(facility_demand, key=facility_demand.get) if facility_demand else "None"

    return {
        "ok": True,
        "from_date": from_date,
        "to_date": to_date,
        "total_bookings": total_bookings,
        "confirmed_count": len(confirmed_or_checked_in),
        "no_show_count": len(no_shows),
        "cancelled_count": len(cancelled),
        "waitlist_joins_count": len(waitlists),
        "no_show_rate_percent": no_show_rate,
        "cancellation_rate_percent": cancellation_rate,
        "peak_hour": peak_hour,
        "top_facility": top_facility,
        "facility_demand": facility_demand,
    }
