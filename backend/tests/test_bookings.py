from datetime import datetime, timezone
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

TEST_FACILITY_ID = "11111111-1111-1111-1111-111111111111"
TEST_USER_1 = str(uuid4())
TEST_USER_2 = str(uuid4())


@pytest.fixture
def mock_db_rpc(monkeypatch):
    """
    Mock in-memory RPC store simulating PostgreSQL constraints & book_slot RPC function
    when live database is not connected.
    """
    store = {}  # idempotency_key -> booking
    slot_store = []  # list of confirmed booking dicts

    async def fake_rpc(facility_id, slot_start, slot_end, user_id, idempotency_key):
        idempotency_key = str(idempotency_key)
        facility_id = str(facility_id)
        user_id = str(user_id)

        # Idempotency check
        if idempotency_key in store:
            existing = store[idempotency_key]
            if (
                existing["facility_id"] == facility_id
                and existing["slot_start"] == slot_start
                and existing["slot_end"] == slot_end
                and existing["user_id"] == user_id
            ):
                return {
                    "ok": True,
                    "reason": "idempotent_replay",
                    "booking_id": existing["id"],
                    "booking": existing,
                }
            else:
                return {
                    "ok": False,
                    "reason": "idempotency_key_reused",
                    "booking_id": None,
                    "booking": None,
                }

        # Check for slot collision / overlap with confirmed bookings
        start_dt = datetime.fromisoformat(slot_start)
        end_dt = datetime.fromisoformat(slot_end)

        for b in slot_store:
            if b["facility_id"] == facility_id and b["status"] == "confirmed":
                b_start = datetime.fromisoformat(b["slot_start"])
                b_end = datetime.fromisoformat(b["slot_end"])
                # Range overlap condition: max(start1, start2) < min(end1, end2)
                if max(start_dt, b_start) < min(end_dt, b_end):
                    return {
                        "ok": False,
                        "reason": "slot_taken",
                        "booking_id": None,
                        "booking": None,
                    }

        # Successful insert
        new_booking = {
            "id": str(uuid4()),
            "facility_id": facility_id,
            "slot_start": slot_start,
            "slot_end": slot_end,
            "user_id": user_id,
            "status": "confirmed",
            "idempotency_key": idempotency_key,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        store[idempotency_key] = new_booking
        slot_store.append(new_booking)
        return {
            "ok": True,
            "reason": "confirmed",
            "booking_id": new_booking["id"],
            "booking": new_booking,
        }

    async def fake_cancel(booking_id, user_id):
        booking_id = str(booking_id)
        user_id = str(user_id)
        for b in slot_store:
            if b["id"] == booking_id:
                if b["user_id"] != user_id:
                    return {"ok": False, "reason": "unauthorized"}
                if b["status"] == "cancelled":
                    return {"ok": True, "reason": "already_cancelled", "booking_id": booking_id}
                b["status"] = "cancelled"
                return {"ok": True, "reason": "cancelled", "booking_id": booking_id}
        return {"ok": False, "reason": "not_found"}

    monkeypatch.setattr("app.api.bookings.call_book_slot_rpc", fake_rpc)
    monkeypatch.setattr("app.api.bookings.cancel_booking_db", fake_cancel)
    return {"store": store, "slot_store": slot_store}


@pytest.mark.asyncio
async def test_normal_booking_success(mock_db_rpc):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "facility_id": TEST_FACILITY_ID,
            "slot_start": "2026-09-01T10:00:00Z",
            "slot_end": "2026-09-01T11:00:00Z",
            "idempotency_key": str(uuid4()),
        }
        res = await client.post("/bookings", json=payload, headers={"X-User-ID": TEST_USER_1})
        assert res.status_code == 201
        data = res.json()
        assert data["ok"] is True
        assert data["reason"] == "confirmed"
        assert data["booking"]["user_id"] == TEST_USER_1


@pytest.mark.asyncio
async def test_duplicate_idempotency_replay(mock_db_rpc):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ikey = str(uuid4())
        payload = {
            "facility_id": TEST_FACILITY_ID,
            "slot_start": "2026-09-01T12:00:00Z",
            "slot_end": "2026-09-01T13:00:00Z",
            "idempotency_key": ikey,
        }
        res1 = await client.post("/bookings", json=payload, headers={"X-User-ID": TEST_USER_1})
        assert res1.status_code == 201

        # Replay identical request with same idempotency key
        res2 = await client.post("/bookings", json=payload, headers={"X-User-ID": TEST_USER_1})
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["ok"] is True
        assert data2["reason"] == "idempotent_replay"
        assert data2["booking_id"] == res1.json()["booking_id"]


@pytest.mark.asyncio
async def test_idempotency_key_reuse_different_request(mock_db_rpc):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ikey = str(uuid4())
        payload1 = {
            "facility_id": TEST_FACILITY_ID,
            "slot_start": "2026-09-01T14:00:00Z",
            "slot_end": "2026-09-01T15:00:00Z",
            "idempotency_key": ikey,
        }
        res1 = await client.post("/bookings", json=payload1, headers={"X-User-ID": TEST_USER_1})
        assert res1.status_code == 201

        # Different time slot with SAME idempotency key
        payload2 = {
            "facility_id": TEST_FACILITY_ID,
            "slot_start": "2026-09-01T15:00:00Z",
            "slot_end": "2026-09-01T16:00:00Z",
            "idempotency_key": ikey,
        }
        res2 = await client.post("/bookings", json=payload2, headers={"X-User-ID": TEST_USER_1})
        assert res2.status_code == 400
        assert res2.json()["detail"]["reason"] == "idempotency_key_reused"


@pytest.mark.asyncio
async def test_sequential_slot_conflict(mock_db_rpc):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload1 = {
            "facility_id": TEST_FACILITY_ID,
            "slot_start": "2026-09-01T16:00:00Z",
            "slot_end": "2026-09-01T17:00:00Z",
            "idempotency_key": str(uuid4()),
        }
        res1 = await client.post("/bookings", json=payload1, headers={"X-User-ID": TEST_USER_1})
        assert res1.status_code == 201

        # Second user targeting exact same slot
        payload2 = {
            "facility_id": TEST_FACILITY_ID,
            "slot_start": "2026-09-01T16:00:00Z",
            "slot_end": "2026-09-01T17:00:00Z",
            "idempotency_key": str(uuid4()),
        }
        res2 = await client.post("/bookings", json=payload2, headers={"X-User-ID": TEST_USER_2})
        assert res2.status_code == 409
        assert res2.json()["detail"]["reason"] == "slot_taken"


@pytest.mark.asyncio
async def test_overlapping_slot_conflict(mock_db_rpc):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload1 = {
            "facility_id": TEST_FACILITY_ID,
            "slot_start": "2026-09-01T18:00:00Z",
            "slot_end": "2026-09-01T19:00:00Z",
            "idempotency_key": str(uuid4()),
        }
        res1 = await client.post("/bookings", json=payload1, headers={"X-User-ID": TEST_USER_1})
        assert res1.status_code == 201

        # Overlapping range 18:30 -> 19:30
        payload2 = {
            "facility_id": TEST_FACILITY_ID,
            "slot_start": "2026-09-01T18:30:00Z",
            "slot_end": "2026-09-01T19:30:00Z",
            "idempotency_key": str(uuid4()),
        }
        res2 = await client.post("/bookings", json=payload2, headers={"X-User-ID": TEST_USER_2})
        assert res2.status_code == 409
        assert res2.json()["detail"]["reason"] == "slot_taken"


@pytest.mark.asyncio
async def test_cancellation_and_rebooking(mock_db_rpc):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload1 = {
            "facility_id": TEST_FACILITY_ID,
            "slot_start": "2026-09-01T20:00:00Z",
            "slot_end": "2026-09-01T21:00:00Z",
            "idempotency_key": str(uuid4()),
        }
        res1 = await client.post("/bookings", json=payload1, headers={"X-User-ID": TEST_USER_1})
        assert res1.status_code == 201
        b_id = res1.json()["booking_id"]

        # Cancel booking 1
        res_cancel = await client.delete(f"/bookings/{b_id}", headers={"X-User-ID": TEST_USER_1})
        assert res_cancel.status_code == 200
        assert res_cancel.json()["reason"] == "cancelled"

        # Now User 2 can book the freed slot
        payload2 = {
            "facility_id": TEST_FACILITY_ID,
            "slot_start": "2026-09-01T20:00:00Z",
            "slot_end": "2026-09-01T21:00:00Z",
            "idempotency_key": str(uuid4()),
        }
        res2 = await client.post("/bookings", json=payload2, headers={"X-User-ID": TEST_USER_2})
        assert res2.status_code == 201
        assert res2.json()["booking"]["user_id"] == TEST_USER_2


@pytest.mark.asyncio
async def test_unauthorized_cancellation(mock_db_rpc):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload1 = {
            "facility_id": TEST_FACILITY_ID,
            "slot_start": "2026-09-01T21:00:00Z",
            "slot_end": "2026-09-01T22:00:00Z",
            "idempotency_key": str(uuid4()),
        }
        res1 = await client.post("/bookings", json=payload1, headers={"X-User-ID": TEST_USER_1})
        assert res1.status_code == 201
        b_id = res1.json()["booking_id"]

        # User 2 attempts to cancel User 1's booking
        res_cancel = await client.delete(f"/bookings/{b_id}", headers={"X-User-ID": TEST_USER_2})
        assert res_cancel.status_code == 403
        assert res_cancel.json()["detail"]["reason"] == "unauthorized"
