import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

FACILITY_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def mock_priority_concurrency_store(monkeypatch):
    lock = asyncio.Lock()
    bookings = {}
    eligible_set = set()

    async def fake_book_slot(facility_id, slot_start, slot_end, user_id, idempotency_key):
        async with lock:
            now_utc = datetime.now(timezone.utc)
            start_dt = datetime.fromisoformat(slot_start.replace("Z", "+00:00"))
            normal_cutoff = start_dt - timedelta(hours=24)
            priority_cutoff = start_dt - timedelta(hours=72)

            if now_utc < priority_cutoff:
                return {"ok": False, "reason": "booking_window_not_open"}

            if now_utc < normal_cutoff:
                if str(user_id) not in eligible_set:
                    return {"ok": False, "reason": "booking_window_not_open"}

            # Check if slot already taken
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
                "created_at": now_utc.isoformat(),
            }
            bookings[b_id] = new_b
            return {"ok": True, "reason": "confirmed", "booking_id": b_id, "booking": new_b}

    monkeypatch.setattr("app.api.bookings.call_book_slot_rpc", fake_book_slot)
    return {"bookings": bookings, "eligible_set": eligible_set}


@pytest.mark.asyncio
async def test_priority_vs_normal_race(mock_priority_concurrency_store):
    """
    Slot 48h away. 1 Priority user + 99 Normal users attempt to book simultaneously.
    Expected: Exactly 1 confirmed booking (Priority user wins, Normal users fail window check).
    """
    p_user = str(uuid4())
    mock_priority_concurrency_store["eligible_set"].add(p_user)
    normal_users = [str(uuid4()) for _ in range(99)]

    start = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
    end = (datetime.now(timezone.utc) + timedelta(hours=49)).isoformat()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async def worker(u_id):
            return await ac.post(
                "/bookings",
                headers={"X-User-ID": u_id},
                json={"facility_id": FACILITY_ID, "slot_start": start, "slot_end": end, "idempotency_key": str(uuid4())},
            )

        all_users = [p_user] + normal_users
        responses = await asyncio.gather(*[worker(u) for u in all_users])

    confirmed = [r for r in responses if r.status_code == 201]
    rejected = [r for r in responses if r.status_code == 409]

    assert len(confirmed) == 1
    assert len(rejected) == 99
    assert len(mock_priority_concurrency_store["bookings"]) == 1


@pytest.mark.asyncio
async def test_priority_storm(mock_priority_concurrency_store):
    """
    100 concurrent priority users attempt to book the SAME slot (48h away).
    Expected: Exactly 1 winner (201), 99 losers (409 slot_taken).
    """
    priority_users = [str(uuid4()) for _ in range(100)]
    for u in priority_users:
        mock_priority_concurrency_store["eligible_set"].add(u)

    start = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
    end = (datetime.now(timezone.utc) + timedelta(hours=49)).isoformat()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async def worker(u_id):
            return await ac.post(
                "/bookings",
                headers={"X-User-ID": u_id},
                json={"facility_id": FACILITY_ID, "slot_start": start, "slot_end": end, "idempotency_key": str(uuid4())},
            )

        responses = await asyncio.gather(*[worker(u) for u in priority_users])

    confirmed = [r for r in responses if r.status_code == 201]
    assert len(confirmed) == 1
    assert len(mock_priority_concurrency_store["bookings"]) == 1


@pytest.mark.asyncio
async def test_normal_storm(mock_priority_concurrency_store):
    """
    100 concurrent normal users attempt to book the SAME slot (12h away, open to all).
    Expected: Exactly 1 winner (201), 99 losers (409 slot_taken).
    """
    normal_users = [str(uuid4()) for _ in range(100)]

    start = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
    end = (datetime.now(timezone.utc) + timedelta(hours=13)).isoformat()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async def worker(u_id):
            return await ac.post(
                "/bookings",
                headers={"X-User-ID": u_id},
                json={"facility_id": FACILITY_ID, "slot_start": start, "slot_end": end, "idempotency_key": str(uuid4())},
            )

        responses = await asyncio.gather(*[worker(u) for u in normal_users])

    confirmed = [r for r in responses if r.status_code == 201]
    assert len(confirmed) == 1
    assert len(mock_priority_concurrency_store["bookings"]) == 1
