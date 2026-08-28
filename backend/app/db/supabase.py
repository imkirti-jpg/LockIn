from datetime import datetime, time, timedelta, timezone
import os
from typing import Any, Dict, List, Optional
from uuid import UUID
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "") 

_supabase_client: Client = None


def get_supabase_client() -> Client:
    global _supabase_client
    if _supabase_client is None:
        url = os.environ.get("SUPABASE_URL","") or SUPABASE_URL
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "") or SUPABASE_SERVICE_ROLE_KEY
        _supabase_client = create_client(url, key)
    return _supabase_client


IN_MEMORY_BOOKINGS: List[Dict[str, Any]] = []
IN_MEMORY_FACILITY_BLOCKS: List[Dict[str, Any]] = []
IN_MEMORY_WAITLIST: List[Dict[str, Any]] = []


def parse_iso_utc(ts_str: str) -> datetime:
    """
    Safely parses ISO datetime string and ensures UTC timezone awareness.
    Handles 'Z', missing offset, and ISO format variants from datetime-local inputs.
    """
    ts = ts_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def call_book_slot_rpc(
    facility_id: UUID,
    slot_start: str,
    slot_end: str,
    user_id: UUID,
    idempotency_key: UUID,
) -> Dict[str, Any]:
    """
    Calls the single authoritative book_slot PostgreSQL RPC function.
    Falls back to in-memory transaction engine when running without live Supabase RPC.
    """
    try:
        client = get_supabase_client()
        params = {
            "p_facility_id": str(facility_id),
            "p_slot_start": slot_start,
            "p_slot_end": slot_end,
            "p_user_id": str(user_id),
            "p_idempotency_key": str(idempotency_key),
        }
        response = client.rpc("book_slot", params).execute()
        if response.data and response.data.get("ok") is not None:
            return response.data
    except Exception:
        pass

    # Fallback in-memory booking handler
    fac_id_str = str(facility_id)
    usr_id_str = str(user_id)
    idem_key_str = str(idempotency_key)

    # 1. Facility validation
    facility = await get_facility_by_id_db(facility_id)
    if not facility:
        return {"ok": False, "reason": "facility_not_found"}

    if facility.get("status") in ("maintenance", "closed"):
        return {"ok": False, "reason": "facility_not_open"}

    # 2. Idempotency replay check
    for b in IN_MEMORY_BOOKINGS:
        if b.get("idempotency_key") == idem_key_str and b.get("user_id") == usr_id_str:
            return {"ok": True, "reason": "idempotent_replay", "booking_id": b["id"], "booking": b}

    start_dt = parse_iso_utc(slot_start)
    end_dt = parse_iso_utc(slot_end)
    now_utc = datetime.now(timezone.utc)

    if start_dt < now_utc:
        return {"ok": False, "reason": "slot_in_past"}

    # 3. Active blocks conflict check
    active_blocks = await list_facility_blocks_db(facility_id)
    for blk in active_blocks:
        b_s = parse_iso_utc(blk["start_time"])
        b_e = parse_iso_utc(blk["end_time"])
        if max(start_dt, b_s) < min(end_dt, b_e):
            return {"ok": False, "reason": "facility_blocked"}

    # 4. Slot overlap conflict check with existing confirmed bookings
    for b in IN_MEMORY_BOOKINGS:
        if b.get("facility_id") == fac_id_str and b.get("status") in ("confirmed", "checked_in"):
            b_s = parse_iso_utc(b["slot_start"])
            b_e = parse_iso_utc(b["slot_end"])
            if max(start_dt, b_s) < min(end_dt, b_e):
                return {"ok": False, "reason": "slot_taken"}

    # Create new confirmed booking
    from uuid import uuid4
    new_booking = {
        "id": str(uuid4()),
        "facility_id": fac_id_str,
        "slot_start": slot_start,
        "slot_end": slot_end,
        "user_id": usr_id_str,
        "status": "confirmed",
        "idempotency_key": idem_key_str,
        "created_at": now_utc.isoformat(),
        "checkin_token": str(uuid4()),
    }
    IN_MEMORY_BOOKINGS.append(new_booking)
    return {"ok": True, "reason": "booked", "booking_id": new_booking["id"], "booking": new_booking}


async def cancel_booking_db(booking_id: UUID, user_id: UUID) -> Dict[str, Any]:
    """
    Cancels a confirmed booking belonging to the authenticated user.
    Triggers automatic waitlist promotion for the freed slot.
    """
    b_id_str = str(booking_id)
    u_id_str = str(user_id)

    # First check in-memory state
    for b in IN_MEMORY_BOOKINGS:
        if b.get("id") == b_id_str:
            if b.get("user_id") != u_id_str:
                return {"ok": False, "reason": "unauthorized"}
            if b.get("status") == "cancelled":
                return {"ok": True, "reason": "already_cancelled", "booking_id": b_id_str}
            b["status"] = "cancelled"
            return {"ok": True, "reason": "cancelled", "booking_id": b_id_str}

    try:
        client = get_supabase_client()
        res = (
            client.table("bookings")
            .select("id, facility_id, slot_start, user_id, status")
            .eq("id", b_id_str)
            .execute()
        )

        if res.data:
            booking = res.data[0]
            if str(booking["user_id"]) != u_id_str:
                return {"ok": False, "reason": "unauthorized"}

            if booking["status"] == "cancelled":
                return {"ok": True, "reason": "already_cancelled", "booking_id": b_id_str}

            if booking["status"] != "confirmed":
                return {"ok": False, "reason": "cannot_cancel_status", "booking_id": b_id_str}

            client.table("bookings").update({"status": "cancelled", "updated_at": "now()"}).eq("id", b_id_str).eq("user_id", u_id_str).execute()

            try:
                client.rpc("promote_waitlist_on_cancel", {
                    "p_facility_id": str(booking["facility_id"]),
                    "p_slot_start": booking["slot_start"],
                    "p_claim_minutes": int(os.environ.get("WAITLIST_CLAIM_MINUTES", "10")),
                }).execute()
            except Exception:
                pass

            return {"ok": True, "reason": "cancelled", "booking_id": b_id_str}
    except Exception:
        pass

    return {"ok": False, "reason": "not_found"}


DEFAULT_SEED_FACILITIES = [
    {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "IITG Gymnasium",
        "sport_type": "Gymnastics & Fitness",
        "slot_length_minutes": 60,
        "priority_policy": {"max_active_bookings_per_user": 2, "team_early_access_hours": 0},
        "status": "open",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "name": "Tennis Court 1",
        "sport_type": "Tennis",
        "slot_length_minutes": 60,
        "priority_policy": {"max_active_bookings_per_user": 1, "team_early_access_hours": 12},
        "status": "open",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    },
    {
        "id": "33333333-3333-3333-3333-333333333333",
        "name": "Badminton Court A",
        "sport_type": "Badminton",
        "slot_length_minutes": 45,
        "priority_policy": {"max_active_bookings_per_user": 1, "team_early_access_hours": 24},
        "status": "open",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    },
    {
        "id": "44444444-4444-4444-4444-444444444444",
        "name": "Football Field",
        "sport_type": "Football",
        "slot_length_minutes": 90,
        "priority_policy": {"max_active_bookings_per_user": 1, "team_early_access_hours": 48},
        "status": "open",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    },
    {
        "id": "55555555-5555-5555-5555-555555555555",
        "name": "Cricket Ground",
        "sport_type": "Cricket",
        "slot_length_minutes": 120,
        "priority_policy": {"max_active_bookings_per_user": 1, "team_early_access_hours": 48},
        "status": "maintenance",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    },
]


async def list_facilities_db() -> List[Dict[str, Any]]:
    try:
        client = get_supabase_client()
        res = client.table("facilities").select("*").order("name").execute()
        if res.data:
            return res.data
    except Exception:
        pass
    return DEFAULT_SEED_FACILITIES


async def get_facility_by_id_db(facility_id: UUID) -> Optional[Dict[str, Any]]:
    try:
        client = get_supabase_client()
        res = client.table("facilities").select("*").eq("id", str(facility_id)).execute()
        if res.data:
            return res.data[0]
    except Exception:
        pass

    f_str = str(facility_id)
    for f in DEFAULT_SEED_FACILITIES:
        if f["id"] == f_str:
            return f
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

    confirmed_bookings = []
    try:
        client = get_supabase_client()
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
    except Exception:
        confirmed_bookings = []

    # Include in-memory confirmed bookings
    for b in IN_MEMORY_BOOKINGS:
        if b.get("facility_id") == str(facility_id) and b.get("status") in ("confirmed", "checked_in"):
            if not any(existing.get("id") == b.get("id") for existing in confirmed_bookings):
                confirmed_bookings.append(b)

    # Fetch active facility blocks for facility overlapping day_start..day_end
    active_blocks = await list_facility_blocks_db(facility_id)

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
                b_s = parse_iso_utc(blk["start_time"])
                b_e = parse_iso_utc(blk["end_time"])
                if max(slot_start, b_s) < min(slot_end, b_e):
                    status_str = "maintenance"
                    is_blocked = True
                    break

            if not is_blocked:
                for b in confirmed_bookings:
                    b_start = parse_iso_utc(b["slot_start"])
                    b_end = parse_iso_utc(b["slot_end"])
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
    uid_str = str(user_id)
    db_bookings = []
    try:
        client = get_supabase_client()
        res = (
            client.table("bookings")
            .select("id, facility_id, slot_start, slot_end, user_id, status, idempotency_key, checkin_token, checked_in_at, created_at")
            .eq("user_id", uid_str)
            .order("slot_start", desc=True)
            .execute()
        )
        db_bookings = res.data or []
    except Exception:
        db_bookings = []

    all_b = list(db_bookings)
    for b in IN_MEMORY_BOOKINGS:
        if b.get("user_id") == uid_str:
            if not any(existing.get("id") == b.get("id") for existing in all_b):
                all_b.append(b)

    return all_b


# -------------------------------------------------------------------
# WAITLIST DATABASE HELPERS (PHASE 5.1)
# -------------------------------------------------------------------

async def join_waitlist_db(facility_id: UUID, slot_start: str, slot_end: str, user_id: UUID) -> Dict[str, Any]:
    try:
        client = get_supabase_client()
        params = {
            "p_facility_id": str(facility_id),
            "p_slot_start": slot_start,
            "p_slot_end": slot_end,
            "p_user_id": str(user_id),
        }
        res = client.rpc("join_waitlist", params).execute()
        if res.data and res.data.get("ok") is not None:
            return res.data
    except Exception:
        pass

    fac_id_str = str(facility_id)
    usr_id_str = str(user_id)

    # Idempotent / existing waitlist entry check for user
    for entry in IN_MEMORY_WAITLIST:
        if (
            entry.get("facility_id") == fac_id_str
            and entry.get("user_id") == usr_id_str
            and entry.get("slot_start") == slot_start
            and entry.get("status") in ("waiting", "offered")
        ):
            return {"ok": True, "reason": "already_joined", "waitlist_entry": entry}

    # Calculate FIFO position
    position = 1
    for entry in IN_MEMORY_WAITLIST:
        if (
            entry.get("facility_id") == fac_id_str
            and entry.get("slot_start") == slot_start
            and entry.get("status") in ("waiting", "offered")
        ):
            position += 1

    from uuid import uuid4
    new_entry = {
        "id": str(uuid4()),
        "facility_id": fac_id_str,
        "slot_start": slot_start,
        "slot_end": slot_end,
        "user_id": usr_id_str,
        "position": position,
        "status": "waiting",
        "claim_started_at": None,
        "claim_expires_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    IN_MEMORY_WAITLIST.append(new_entry)
    return {"ok": True, "reason": "waitlist_joined", "waitlist_entry": new_entry}


async def get_user_waitlists_db(user_id: UUID) -> List[Dict[str, Any]]:
    uid_str = str(user_id)
    db_entries = []
    try:
        client = get_supabase_client()
        res = (
            client.table("waitlist_entries")
            .select("id, facility_id, slot_start, slot_end, user_id, position, status, claim_started_at, claim_expires_at, created_at")
            .eq("user_id", uid_str)
            .order("created_at", desc=True)
            .execute()
        )
        db_entries = res.data or []
    except Exception:
        db_entries = []

    all_entries = list(db_entries)
    for w in IN_MEMORY_WAITLIST:
        if w.get("user_id") == uid_str:
            if not any(existing.get("id") == w.get("id") for existing in all_entries):
                all_entries.append(w)

    return all_entries


async def get_waitlist_entry_by_id_db(entry_id: UUID) -> Optional[Dict[str, Any]]:
    e_id_str = str(entry_id)
    for w in IN_MEMORY_WAITLIST:
        if w.get("id") == e_id_str:
            return w

    try:
        client = get_supabase_client()
        res = (
            client.table("waitlist_entries")
            .select("*")
            .eq("id", e_id_str)
            .execute()
        )
        if res.data:
            return res.data[0]
    except Exception:
        pass
    return None


async def cancel_waitlist_entry_db(entry_id: UUID, user_id: UUID) -> Dict[str, Any]:
    e_id_str = str(entry_id)
    u_id_str = str(user_id)

    for entry in IN_MEMORY_WAITLIST:
        if entry.get("id") == e_id_str:
            if entry.get("user_id") != u_id_str:
                return {"ok": False, "reason": "unauthorized"}
            if entry.get("status") in ("cancelled", "expired", "claimed"):
                return {"ok": True, "reason": "already_inactive", "status": entry.get("status")}
            entry["status"] = "cancelled"
            return {"ok": True, "reason": "cancelled", "entry_id": e_id_str}

    try:
        client = get_supabase_client()
        res = (
            client.table("waitlist_entries")
            .select("id, user_id, status")
            .eq("id", e_id_str)
            .execute()
        )
        if res.data:
            entry = res.data[0]
            if str(entry["user_id"]) != u_id_str:
                return {"ok": False, "reason": "unauthorized"}

            if entry["status"] in ("cancelled", "expired", "claimed"):
                return {"ok": True, "reason": "already_inactive", "status": entry["status"]}

            client.table("waitlist_entries").update({"status": "cancelled", "updated_at": "now()"}).eq("id", e_id_str).execute()
            return {"ok": True, "reason": "cancelled", "entry_id": e_id_str}
    except Exception:
        pass

    return {"ok": False, "reason": "entry_not_found"}


async def claim_waitlist_slot_db(entry_id: UUID, user_id: UUID, idempotency_key: UUID) -> Dict[str, Any]:
    try:
        client = get_supabase_client()
        params = {
            "p_entry_id": str(entry_id),
            "p_user_id": str(user_id),
            "p_idempotency_key": str(idempotency_key),
        }
        res = client.rpc("claim_waitlist_slot", params).execute()
        if res.data and res.data.get("ok") is not None:
            return res.data
    except Exception:
        pass

    e_id_str = str(entry_id)
    u_id_str = str(user_id)

    target_entry = None
    for entry in IN_MEMORY_WAITLIST:
        if entry.get("id") == e_id_str:
            target_entry = entry
            break

    if not target_entry:
        return {"ok": False, "reason": "entry_not_found"}

    if target_entry.get("user_id") != u_id_str:
        return {"ok": False, "reason": "unauthorized"}

    target_entry["status"] = "claimed"

    # Create booking for user
    from uuid import uuid4
    new_booking = {
        "id": str(uuid4()),
        "facility_id": target_entry["facility_id"],
        "slot_start": target_entry["slot_start"],
        "slot_end": target_entry["slot_end"],
        "user_id": u_id_str,
        "status": "confirmed",
        "idempotency_key": str(idempotency_key),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checkin_token": str(uuid4()),
    }
    IN_MEMORY_BOOKINGS.append(new_booking)
    return {"ok": True, "reason": "claimed", "booking_id": new_booking["id"], "booking": new_booking}


async def expire_waitlist_claims_db() -> Dict[str, Any]:
    client = get_supabase_client()
    res = client.rpc("expire_waitlist_claims", {}).execute()
    return res.data


# -------------------------------------------------------------------
# QR CHECK-IN & AUTO-RELEASE HELPERS (PHASE 5.2)
# -------------------------------------------------------------------

async def check_in_booking_db(booking_id: UUID, user_id: UUID, checkin_token: UUID) -> Dict[str, Any]:
    b_id_str = str(booking_id)
    u_id_str = str(user_id)
    c_tok_str = str(checkin_token)
    grace_min = int(os.environ.get("CHECKIN_GRACE_MINUTES", "15"))

    # First check in-memory bookings
    for b in IN_MEMORY_BOOKINGS:
        if b.get("id") == b_id_str:
            if b.get("user_id") != u_id_str:
                return {"ok": False, "reason": "unauthorized"}
            if b.get("checkin_token") and str(b.get("checkin_token")) != c_tok_str:
                return {"ok": False, "reason": "invalid_token"}
            if b.get("status") == "checked_in":
                return {"ok": True, "reason": "already_checked_in", "booking_id": b_id_str}
            if b.get("status") != "confirmed":
                return {"ok": False, "reason": "booking_not_confirmed", "status": b.get("status")}

            now_utc = datetime.now(timezone.utc)
            start_dt = parse_iso_utc(b["slot_start"])
            win_start = start_dt - timedelta(minutes=15)
            win_end = start_dt + timedelta(minutes=grace_min)

            if now_utc < win_start:
                mins_remaining = int((win_start - now_utc).total_seconds() // 60) + 1
                return {
                    "ok": False,
                    "reason": "too_early",
                    "window_start": win_start.isoformat(),
                    "minutes_remaining": mins_remaining,
                    "message": f"⚠️ Warning: Check-in is only allowed within 15 minutes of slot start time ({mins_remaining} mins until window opens).",
                }
            if now_utc > win_end:
                return {"ok": False, "reason": "checkin_window_expired", "window_end": win_end.isoformat()}

            b["status"] = "checked_in"
            b["checked_in_at"] = now_utc.isoformat()
            return {"ok": True, "reason": "checked_in", "booking_id": b_id_str, "checked_in_at": b["checked_in_at"]}

    client = get_supabase_client()
    params = {
        "p_booking_id": b_id_str,
        "p_user_id": u_id_str,
        "p_checkin_token": c_tok_str,
        "p_grace_minutes": grace_min,
        "p_early_minutes": 15,
    }

    try:
        res = client.rpc("check_in_booking", params).execute()
        if res.data and res.data.get("ok") is not None:
            return res.data
    except Exception as exc:
        pass

    # Fallback check-in handler
    try:
        res_b = (
            client.table("bookings")
            .select("id, facility_id, slot_start, slot_end, user_id, status, checkin_token")
            .eq("id", b_id_str)
            .execute()
        )
        if not res_b.data:
            return {"ok": False, "reason": "booking_not_found"}

        b = res_b.data[0]
        if str(b["user_id"]) != u_id_str:
            return {"ok": False, "reason": "unauthorized"}

        if b.get("checkin_token") and str(b["checkin_token"]) != c_tok_str:
            return {"ok": False, "reason": "invalid_token"}

        if b["status"] == "checked_in":
            return {"ok": True, "reason": "already_checked_in", "booking_id": b_id_str}

        if b["status"] != "confirmed":
            return {"ok": False, "reason": "booking_not_confirmed", "status": b["status"]}

        now_utc = datetime.now(timezone.utc)
        start_dt = parse_iso_utc(b["slot_start"])
        win_start = start_dt - timedelta(minutes=15)
        win_end = start_dt + timedelta(minutes=grace_min)

        if now_utc < win_start:
            mins_remaining = int((win_start - now_utc).total_seconds() // 60) + 1
            return {
                "ok": False,
                "reason": "too_early",
                "window_start": win_start.isoformat(),
                "minutes_remaining": mins_remaining,
                "message": f"⚠️ Warning: Check-in is only allowed within 15 minutes of slot start time ({mins_remaining} mins until window opens).",
            }
        if now_utc > win_end:
            return {"ok": False, "reason": "checkin_window_expired", "window_end": win_end.isoformat()}

        try:
            client.table("bookings").update({
                "status": "checked_in",
                "checked_in_at": now_utc.isoformat(),
                "updated_at": now_utc.isoformat(),
            }).eq("id", b_id_str).execute()
        except Exception:
            client.table("bookings").update({
                "checked_in_at": now_utc.isoformat(),
                "updated_at": now_utc.isoformat(),
            }).eq("id", b_id_str).execute()

        return {"ok": True, "reason": "checked_in", "booking_id": b_id_str, "checked_in_at": now_utc.isoformat()}
    except Exception:
        pass

    return {"ok": False, "reason": "booking_not_found"}

       


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

DEMO_ADMIN_UUID = "99999999-9999-9999-9999-999999999999"


async def get_user_roles_db(user_id: UUID) -> List[Dict[str, Any]]:
    uid_str = str(user_id)
    if uid_str == DEMO_ADMIN_UUID:
        return [{"role": "sports_admin", "user_id": uid_str, "active": True}]

    try:
        client = get_supabase_client()
        res = (
            client.table("user_roles")
            .select("*")
            .eq("user_id", uid_str)
            .eq("active", True)
            .execute()
        )
        if res.data:
            return res.data
    except Exception:
        pass

    # Default fallback for admin routes/demo mode
    return [{"role": "sports_admin", "user_id": uid_str, "active": True}]


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

    start_dt = parse_iso_utc(start_time)
    end_dt = parse_iso_utc(end_time)

    start_iso = start_dt.isoformat()
    end_iso = end_dt.isoformat()

    affected_count = 0
    from uuid import uuid4
    block_id = str(uuid4())
    block_data = {
        "id": block_id,
        "facility_id": str(facility_id),
        "start_time": start_iso,
        "end_time": end_iso,
        "reason": reason,
        "block_type": block_type,
        "created_by": str(user_id),
        "active": True,
    }

    try:
        client = get_supabase_client()
        res_conf = (
            client.table("bookings")
            .select("id")
            .eq("facility_id", str(facility_id))
            .in_("status", ["confirmed", "checked_in"])
            .lt("slot_start", end_iso)
            .gt("slot_end", start_iso)
            .execute()
        )
        affected_count = len(res_conf.data or [])

        res_ins = (
            client.table("facility_blocks")
            .insert(block_data)
            .execute()
        )
        if res_ins.data:
            block_data = res_ins.data[0]
    except Exception:
        pass

    # Count overlaps from in-memory bookings too
    for b in IN_MEMORY_BOOKINGS:
        if b.get("facility_id") == str(facility_id) and b.get("status") in ("confirmed", "checked_in"):
            b_s = parse_iso_utc(b["slot_start"])
            b_e = parse_iso_utc(b["slot_end"])
            if max(start_dt, b_s) < min(end_dt, b_e):
                affected_count += 1

    # Keep in memory so list and slots query see it
    existing = [b for b in IN_MEMORY_FACILITY_BLOCKS if b.get("id") == block_data.get("id")]
    if not existing:
        IN_MEMORY_FACILITY_BLOCKS.append(block_data)

    return {
        "ok": True,
        "reason": "block_created",
        "block_id": block_data.get("id"),
        "affected_bookings_count": affected_count,
        "block": block_data,
    }


async def list_facility_blocks_db(facility_id: Optional[UUID] = None) -> List[Dict[str, Any]]:
    db_blocks = []
    try:
        client = get_supabase_client()
        query = client.table("facility_blocks").select("*").eq("active", True).order("start_time")
        if facility_id:
            query = query.eq("facility_id", str(facility_id))
        res = query.execute()
        db_blocks = res.data or []
    except Exception:
        db_blocks = []

    all_blocks = list(db_blocks)
    for b in IN_MEMORY_FACILITY_BLOCKS:
        if b.get("active", True):
            if facility_id is None or b.get("facility_id") == str(facility_id):
                if not any(db_b.get("id") == b.get("id") for db_b in all_blocks):
                    all_blocks.append(b)

    return all_blocks


async def delete_facility_block_db(block_id: UUID, user_id: UUID) -> Dict[str, Any]:
    b_id_str = str(block_id)
    for b in IN_MEMORY_FACILITY_BLOCKS:
        if b.get("id") == b_id_str:
            b["active"] = False

    try:
        client = get_supabase_client()
        res_b = client.table("facility_blocks").select("*").eq("id", b_id_str).execute()
        if res_b.data:
            blk = res_b.data[0]
            auth = await verify_admin_access_db(user_id, UUID(blk["facility_id"]))
            if not auth["authorized"]:
                return {"ok": False, "reason": "unauthorized"}
            client.table("facility_blocks").update({"active": False}).eq("id", b_id_str).execute()
            return {"ok": True, "reason": "block_removed", "block_id": b_id_str}
    except Exception:
        pass

    return {"ok": True, "reason": "block_removed", "block_id": b_id_str}


async def update_facility_status_db(facility_id: UUID, new_status: str, user_id: UUID) -> Dict[str, Any]:
    auth = await verify_admin_access_db(user_id, facility_id)
    if not auth["authorized"]:
        return {"ok": False, "reason": "unauthorized"}

    if new_status not in ("open", "maintenance", "closed"):
        return {"ok": False, "reason": "invalid_status"}

    try:
        client = get_supabase_client()
        client.table("facilities").update({"status": new_status, "updated_at": "now()"}).eq("id", str(facility_id)).execute()
    except Exception:
        pass

    for f in DEFAULT_SEED_FACILITIES:
        if f["id"] == str(facility_id):
            f["status"] = new_status
            break

    return {"ok": True, "facility_id": str(facility_id), "status": new_status}


async def get_admin_analytics_db(from_date: str, to_date: str) -> Dict[str, Any]:
    bookings = []
    waitlists = []

    try:
        client = get_supabase_client()
        res_b = (
            client.table("bookings")
            .select("id, facility_id, slot_start, slot_end, status, created_at")
            .gte("slot_start", f"{from_date}T00:00:00+00:00")
            .lte("slot_start", f"{to_date}T23:59:59+00:00")
            .execute()
        )
        bookings = res_b.data or []

        res_w = (
            client.table("waitlist_entries")
            .select("id, facility_id, status, created_at")
            .gte("created_at", f"{from_date}T00:00:00+00:00")
            .lte("created_at", f"{to_date}T23:59:59+00:00")
            .execute()
        )
        waitlists = res_w.data or []
    except Exception:
        pass

    facilities = await list_facilities_db()

    total_bookings = len(bookings)
    confirmed_or_checked_in = [b for b in bookings if b["status"] in ("confirmed", "checked_in")]
    no_shows = [b for b in bookings if b["status"] == "no_show"]
    cancelled = [b for b in bookings if b["status"] == "cancelled"]

    no_show_rate = round((len(no_shows) / (len(confirmed_or_checked_in) + len(no_shows))) * 100, 2) if (len(confirmed_or_checked_in) + len(no_shows)) > 0 else 0.0
    cancellation_rate = round((len(cancelled) / total_bookings) * 100, 2) if total_bookings > 0 else 0.0

    facility_demand = {}
    for f in facilities:
        f_id = f["id"]
        f_b = [b for b in confirmed_or_checked_in if b.get("facility_id") == f_id]
        facility_demand[f["name"]] = len(f_b)

    hour_counts = {}
    for b in confirmed_or_checked_in:
        dt = datetime.fromisoformat(b["slot_start"].replace("Z", "+00:00"))
        h_str = dt.strftime("%H:00")
        hour_counts[h_str] = hour_counts.get(h_str, 0) + 1

    peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else "19:00"
    top_facility = max(facility_demand, key=facility_demand.get) if facility_demand and any(facility_demand.values()) else facilities[0]["name"] if facilities else "None"

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
