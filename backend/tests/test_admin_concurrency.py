import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

FACILITY_A = "11111111-1111-1111-1111-111111111111"
SPORTS_ADMIN_USER = str(uuid4())
STUDENT_USER = str(uuid4())

BLOCK_START = "2026-11-01T18:00:00+00:00"
BLOCK_END = "2026-11-01T19:00:00+00:00"


@pytest.fixture
def mock_admin_concurrency_store(monkeypatch):
    lock = asyncio.Lock()
    blocks = {}
    bookings = {}

    async def fake_verify_admin(user_id, target_facility_id=None):
        return {"authorized": True, "role": "sports_admin"}

    async def fake_create_block(facility_id, start_time, end_time, reason, block_type, user_id):
        async with lock:
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

    async def fake_book_slot(facility_id, slot_start, slot_end, user_id, idempotency_key):
        async with lock:
            start_dt = datetime.fromisoformat(slot_start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(slot_end.replace("Z", "+00:00"))

            # Reject if overlapping active block exists
            for blk in blocks.values():
                if blk["facility_id"] == str(facility_id) and blk["active"]:
                    b_s = datetime.fromisoformat(blk["start_time"].replace("Z", "+00:00"))
                    b_e = datetime.fromisoformat(blk["end_time"].replace("Z", "+00:00"))
                    if max(start_dt, b_s) < min(end_dt, b_e):
                        return {"ok": False, "reason": "facility_blocked"}

            # Check if slot taken
            for b in bookings.values():
                if b["facility_id"] == str(facility_id) and b["slot_start"] == slot_start and b["status"] == "confirmed":
                    return {"ok": False, "reason": "slot_taken"}

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

    monkeypatch.setattr("app.api.admin.verify_admin_access_db", fake_verify_admin)
    monkeypatch.setattr("app.api.admin.create_facility_block_db", fake_create_block)
    monkeypatch.setattr("app.api.bookings.call_book_slot_rpc", fake_book_slot)

    return {"blocks": blocks, "bookings": bookings}


@pytest.mark.asyncio
async def test_admin_block_vs_student_booking_race(mock_admin_concurrency_store):
    """
    50 Admin block requests + 50 Student booking requests submitted simultaneously for the SAME slot.
    Expected: Zero confirmed bookings exist inside an active block when transaction state settles.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async def admin_worker(idx):
            return await ac.post(
                f"/admin/facilities/{FACILITY_A}/blocks",
                headers={"X-User-ID": SPORTS_ADMIN_USER},
                json={"start_time": BLOCK_START, "end_time": BLOCK_END, "reason": f"Maint-{idx}", "block_type": "maintenance"},
            )

        async def student_worker(idx):
            return await ac.post(
                "/bookings",
                headers={"X-User-ID": str(uuid4())},
                json={"facility_id": FACILITY_A, "slot_start": BLOCK_START, "slot_end": BLOCK_END, "idempotency_key": str(uuid4())},
            )

        tasks = [admin_worker(i) for i in range(50)] + [student_worker(i) for i in range(50)]
        responses = await asyncio.gather(*tasks)

    # State invariant check: if block active, no confirmed booking in same window
    has_active_block = any(b["active"] for b in mock_admin_concurrency_store["blocks"].values())
    confirmed_b = [b for b in mock_admin_concurrency_store["bookings"].values() if b["status"] == "confirmed"]

    if has_active_block:
        assert len(confirmed_b) == 0
    else:
        assert len(confirmed_b) <= 1
