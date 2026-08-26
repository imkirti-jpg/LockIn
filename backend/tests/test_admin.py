import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

FACILITY_A = "11111111-1111-1111-1111-111111111111"
FACILITY_B = "22222222-2222-2222-2222-222222222222"

STUDENT_USER = str(uuid4())
SPORTS_ADMIN_USER = str(uuid4())
FACILITY_A_MANAGER_USER = str(uuid4())

BLOCK_START = "2026-10-15T18:00:00+00:00"
BLOCK_END = "2026-10-15T20:00:00+00:00"


@pytest.fixture
def mock_admin_store(monkeypatch):
    roles = {
        SPORTS_ADMIN_USER: [{"role": "sports_admin", "facility_id": None, "active": True}],
        FACILITY_A_MANAGER_USER: [{"role": "facility_manager", "facility_id": FACILITY_A, "active": True}],
        STUDENT_USER: [],
    }
    facilities = {
        FACILITY_A: {"id": FACILITY_A, "name": "Gymnasium", "sport_type": "Gym", "slot_length_minutes": 60, "priority_policy": {}, "status": "open"},
        FACILITY_B: {"id": FACILITY_B, "name": "Tennis Court", "sport_type": "Tennis", "slot_length_minutes": 60, "priority_policy": {}, "status": "open"},
    }
    blocks = {}
    bookings = {}

    async def fake_verify_admin(user_id, target_facility_id=None):
        r_list = roles.get(str(user_id), [])
        for r in r_list:
            if r["role"] == "sports_admin":
                return {"authorized": True, "role": "sports_admin"}
            elif r["role"] == "facility_manager":
                if target_facility_id is None or r.get("facility_id") is None or str(r.get("facility_id")) == str(target_facility_id):
                    return {"authorized": True, "role": "facility_manager", "facility_id": r.get("facility_id")}
        return {"authorized": False, "reason": "unauthorized"}

    async def fake_list_facilities():
        return list(facilities.values())

    async def fake_list_facility_blocks(facility_id=None):
        return [b for b in blocks.values() if b["active"] and (facility_id is None or b["facility_id"] == str(facility_id))]

    async def fake_book_slot(facility_id, slot_start, slot_end, user_id, idempotency_key):
        # Check active blocks overlap
        start_dt = datetime.fromisoformat(slot_start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(slot_end.replace("Z", "+00:00"))

        for blk in blocks.values():
            if blk["facility_id"] == str(facility_id) and blk["active"]:
                b_s = datetime.fromisoformat(blk["start_time"].replace("Z", "+00:00"))
                b_e = datetime.fromisoformat(blk["end_time"].replace("Z", "+00:00"))
                if max(start_dt, b_s) < min(end_dt, b_e):
                    return {"ok": False, "reason": "facility_blocked"}

        b_id = str(uuid4())
        new_b = {
            "id": b_id,
            "facility_id": str(facility_id),
            "slot_start": slot_start,
            "slot_end": slot_end,
            "user_id": str(user_id),
            "status": "confirmed",
            "idempotency_key": str(idempotency_key),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        bookings[b_id] = new_b
        return {"ok": True, "reason": "confirmed", "booking_id": b_id, "booking": new_b}

    async def fake_create_block(facility_id, start_time, end_time, reason, block_type, user_id):
        auth = await fake_verify_admin(user_id, facility_id)
        if not auth["authorized"]:
            return {"ok": False, "reason": "unauthorized"}

        b_id = str(uuid4())
        blk = {
            "id": b_id,
            "facility_id": str(facility_id),
            "start_time": start_time,
            "end_time": end_time,
            "reason": reason,
            "block_type": block_type,
            "created_by": str(user_id),
            "active": True,
        }
        blocks[b_id] = blk
        return {"ok": True, "reason": "block_created", "block_id": b_id, "affected_bookings_count": 0, "block": blk}

    monkeypatch.setattr("app.api.admin.verify_admin_access_db", fake_verify_admin)
    monkeypatch.setattr("app.api.admin.list_facilities_db", fake_list_facilities)
    monkeypatch.setattr("app.api.admin.list_facility_blocks_db", fake_list_facility_blocks)
    monkeypatch.setattr("app.api.admin.create_facility_block_db", fake_create_block)
    monkeypatch.setattr("app.api.admin.delete_facility_block_db", lambda block_id, user_id: {"ok": True, "reason": "block_removed", "block_id": str(block_id)})
    monkeypatch.setattr("app.api.admin.update_facility_status_db", lambda facility_id, new_status, user_id: {"ok": True, "facility_id": str(facility_id), "status": new_status})
    monkeypatch.setattr("app.api.admin.get_admin_analytics_db", lambda from_date, to_date: {
        "ok": True, "from_date": from_date, "to_date": to_date, "total_bookings": 10, "confirmed_count": 8, "no_show_count": 1, "cancelled_count": 1,
        "waitlist_joins_count": 3, "no_show_rate_percent": 11.11, "cancellation_rate_percent": 10.0, "peak_hour": "19:00", "top_facility": "Gymnasium", "facility_demand": {"Gymnasium": 8}
    })
    monkeypatch.setattr("app.api.bookings.call_book_slot_rpc", fake_book_slot)

    return {"roles": roles, "facilities": facilities, "blocks": blocks, "bookings": bookings}


@pytest.mark.asyncio
async def test_unauthorized_student_access_rejected(mock_admin_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Student access to facilities endpoint -> 403
        res = await ac.get("/admin/facilities", headers={"X-User-ID": STUDENT_USER})
        assert res.status_code == 403
        assert res.json()["detail"]["reason"] == "unauthorized_admin"

        # Student access to analytics endpoint -> 403
        res_an = await ac.get("/admin/analytics", headers={"X-User-ID": STUDENT_USER})
        assert res_an.status_code == 403


@pytest.mark.asyncio
async def test_sports_admin_full_access(mock_admin_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/admin/facilities", headers={"X-User-ID": SPORTS_ADMIN_USER})
        assert res.status_code == 200
        assert res.json()["admin_role"] == "sports_admin"

        # Create block for Facility A
        block_res = await ac.post(
            f"/admin/facilities/{FACILITY_A}/blocks",
            headers={"X-User-ID": SPORTS_ADMIN_USER},
            json={"start_time": BLOCK_START, "end_time": BLOCK_END, "reason": "Gym Maintenance", "block_type": "maintenance"},
        )
        assert block_res.status_code == 200
        assert block_res.json()["reason"] == "block_created"


@pytest.mark.asyncio
async def test_facility_manager_scope_enforcement(mock_admin_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Manager for Facility A creates block for Facility A -> OK
        ok_res = await ac.post(
            f"/admin/facilities/{FACILITY_A}/blocks",
            headers={"X-User-ID": FACILITY_A_MANAGER_USER},
            json={"start_time": BLOCK_START, "end_time": BLOCK_END, "reason": "Cleaning", "block_type": "maintenance"},
        )
        assert ok_res.status_code == 200

        # Manager for Facility A attempts block for Facility B -> 403 Forbidden
        bad_res = await ac.post(
            f"/admin/facilities/{FACILITY_B}/blocks",
            headers={"X-User-ID": FACILITY_A_MANAGER_USER},
            json={"start_time": BLOCK_START, "end_time": BLOCK_END, "reason": "Unauthorized block", "block_type": "maintenance"},
        )
        assert bad_res.status_code == 403


@pytest.mark.asyncio
async def test_booking_rejected_in_blocked_interval(mock_admin_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Admin blocks Facility A from 18:00 to 20:00
        await ac.post(
            f"/admin/facilities/{FACILITY_A}/blocks",
            headers={"X-User-ID": SPORTS_ADMIN_USER},
            json={"start_time": BLOCK_START, "end_time": BLOCK_END, "reason": "Tournament", "block_type": "event"},
        )

        # Student attempts booking inside block 18:30–19:30 -> 409 facility_blocked
        overlap_res = await ac.post(
            "/bookings",
            headers={"X-User-ID": STUDENT_USER},
            json={
                "facility_id": FACILITY_A,
                "slot_start": "2026-10-15T18:30:00+00:00",
                "slot_end": "2026-10-15T19:30:00+00:00",
                "idempotency_key": str(uuid4()),
            },
        )
        assert overlap_res.status_code == 409
        assert overlap_res.json()["detail"]["reason"] == "facility_blocked"

        # Adjacent non-overlapping booking 20:00–21:00 -> 201 Created
        adjacent_res = await ac.post(
            "/bookings",
            headers={"X-User-ID": STUDENT_USER},
            json={
                "facility_id": FACILITY_A,
                "slot_start": "2026-10-15T20:00:00+00:00",
                "slot_end": "2026-10-15T21:00:00+00:00",
                "idempotency_key": str(uuid4()),
            },
        )
        assert adjacent_res.status_code == 201
