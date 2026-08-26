import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

FACILITY_ID = "11111111-1111-1111-1111-111111111111"
NORMAL_USER = str(uuid4())
PRIORITY_USER = str(uuid4())
EXPIRED_PRIORITY_USER = str(uuid4())


@pytest.fixture
def mock_priority_store(monkeypatch):
    bookings = {}
    eligibilities = {
        PRIORITY_USER: [
            {
                "id": str(uuid4()),
                "user_id": PRIORITY_USER,
                "priority_group": "team",
                "facility_id": None,
                "active": True,
                "valid_from": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
                "valid_until": None,
            }
        ],
        EXPIRED_PRIORITY_USER: [
            {
                "id": str(uuid4()),
                "user_id": EXPIRED_PRIORITY_USER,
                "priority_group": "team",
                "facility_id": None,
                "active": True,
                "valid_from": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
                "valid_until": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            }
        ],
    }

    async def fake_book_slot(facility_id, slot_start, slot_end, user_id, idempotency_key):
        now_utc = datetime.now(timezone.utc)
        start_dt = datetime.fromisoformat(slot_start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(slot_end.replace("Z", "+00:00"))

        if end_dt <= start_dt:
            return {"ok": False, "reason": "invalid_time_range"}
        if start_dt <= now_utc:
            return {"ok": False, "reason": "slot_in_past"}

        # Policy: normal = 24h, priority = 72h
        normal_cutoff = start_dt - timedelta(hours=24)
        priority_cutoff = start_dt - timedelta(hours=72)

        if now_utc < priority_cutoff:
            return {"ok": False, "reason": "booking_window_not_open", "window_start": priority_cutoff.isoformat()}

        if now_utc < normal_cutoff:
            # Requires active priority eligibility
            user_eligs = eligibilities.get(str(user_id), [])
            has_valid = False
            for e in user_eligs:
                if e["active"]:
                    vf = datetime.fromisoformat(e["valid_from"].replace("Z", "+00:00"))
                    vu = datetime.fromisoformat(e["valid_until"].replace("Z", "+00:00")) if e.get("valid_until") else None
                    if vf <= now_utc and (vu is None or vu >= now_utc):
                        has_valid = True
                        break
            if not has_valid:
                return {"ok": False, "reason": "booking_window_not_open", "window_start": normal_cutoff.isoformat()}

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
    monkeypatch.setattr("app.api.bookings.get_user_priority_eligibility_db", lambda user_id: eligibilities.get(str(user_id), []))

    return {"bookings": bookings, "eligibilities": eligibilities}


@pytest.mark.asyncio
async def test_normal_user_before_window_rejected(mock_priority_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Slot 48h in future (normal window is 24h)
        start = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(hours=49)).isoformat()

        res = await ac.post(
            "/bookings",
            headers={"X-User-ID": NORMAL_USER},
            json={"facility_id": FACILITY_ID, "slot_start": start, "slot_end": end, "idempotency_key": str(uuid4())},
        )
        assert res.status_code == 409
        assert res.json()["detail"]["reason"] == "booking_window_not_open"


@pytest.mark.asyncio
async def test_normal_user_inside_window_success(mock_priority_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Slot 12h in future (normal window is 24h)
        start = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(hours=13)).isoformat()

        res = await ac.post(
            "/bookings",
            headers={"X-User-ID": NORMAL_USER},
            json={"facility_id": FACILITY_ID, "slot_start": start, "slot_end": end, "idempotency_key": str(uuid4())},
        )
        assert res.status_code == 201
        assert res.json()["reason"] == "confirmed"


@pytest.mark.asyncio
async def test_priority_user_inside_priority_window_success(mock_priority_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Slot 48h in future (inside priority window 72h, before normal 24h)
        start = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(hours=49)).isoformat()

        res = await ac.post(
            "/bookings",
            headers={"X-User-ID": PRIORITY_USER},
            json={"facility_id": FACILITY_ID, "slot_start": start, "slot_end": end, "idempotency_key": str(uuid4())},
        )
        assert res.status_code == 201
        assert res.json()["reason"] == "confirmed"


@pytest.mark.asyncio
async def test_priority_user_before_priority_window_rejected(mock_priority_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Slot 96h in future (before priority window 72h)
        start = (datetime.now(timezone.utc) + timedelta(hours=96)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(hours=97)).isoformat()

        res = await ac.post(
            "/bookings",
            headers={"X-User-ID": PRIORITY_USER},
            json={"facility_id": FACILITY_ID, "slot_start": start, "slot_end": end, "idempotency_key": str(uuid4())},
        )
        assert res.status_code == 409
        assert res.json()["detail"]["reason"] == "booking_window_not_open"


@pytest.mark.asyncio
async def test_unauthorized_priority_payload_claim_ignored(mock_priority_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        start = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(hours=49)).isoformat()

        # Normal user includes priority=true in payload
        res = await ac.post(
            "/bookings",
            headers={"X-User-ID": NORMAL_USER},
            json={
                "facility_id": FACILITY_ID,
                "slot_start": start,
                "slot_end": end,
                "idempotency_key": str(uuid4()),
                "priority": True,
                "is_team": True,
            },
        )
        assert res.status_code == 409
        assert res.json()["detail"]["reason"] == "booking_window_not_open"


@pytest.mark.asyncio
async def test_expired_priority_eligibility_rejected(mock_priority_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        start = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(hours=49)).isoformat()

        res = await ac.post(
            "/bookings",
            headers={"X-User-ID": EXPIRED_PRIORITY_USER},
            json={"facility_id": FACILITY_ID, "slot_start": start, "slot_end": end, "idempotency_key": str(uuid4())},
        )
        assert res.status_code == 409
        assert res.json()["detail"]["reason"] == "booking_window_not_open"
