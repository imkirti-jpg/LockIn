from datetime import datetime, timezone
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

TEST_FACILITY_ID = "11111111-1111-1111-1111-111111111111"
TEST_USER_1 = str(uuid4())


@pytest.fixture
def mock_facilities_db(monkeypatch):
    facilities_data = [
        {
            "id": TEST_FACILITY_ID,
            "name": "IITG Gymnasium",
            "sport_type": "Fitness",
            "slot_length_minutes": 60,
            "priority_policy": {},
            "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "name": "Tennis Court 1",
            "sport_type": "Tennis",
            "slot_length_minutes": 60,
            "priority_policy": {},
            "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    ]

    async def fake_list_facilities():
        return facilities_data

    async def fake_get_facility(facility_id):
        f_id = str(facility_id)
        for f in facilities_data:
            if f["id"] == f_id:
                return f
        return None

    async def fake_get_slots(facility_id, target_date_str):
        if str(facility_id) != TEST_FACILITY_ID:
            return {"ok": False, "reason": "facility_not_found"}
        return {
            "ok": True,
            "facility_id": str(facility_id),
            "date": target_date_str,
            "slot_length_minutes": 60,
            "slots": [
                {
                    "slot_id": f"{facility_id}_1000",
                    "facility_id": str(facility_id),
                    "start_time": f"{target_date_str}T10:00:00Z",
                    "end_time": f"{target_date_str}T11:00:00Z",
                    "status": "open",
                    "booking_id": None,
                },
                {
                    "slot_id": f"{facility_id}_1100",
                    "facility_id": str(facility_id),
                    "start_time": f"{target_date_str}T11:00:00Z",
                    "end_time": f"{target_date_str}T12:00:00Z",
                    "status": "full",
                    "booking_id": str(uuid4()),
                },
            ],
        }

    async def fake_get_user_bookings(user_id):
        return [
            {
                "id": str(uuid4()),
                "facility_id": TEST_FACILITY_ID,
                "slot_start": "2026-09-01T10:00:00Z",
                "slot_end": "2026-09-01T11:00:00Z",
                "user_id": str(user_id),
                "status": "confirmed",
                "idempotency_key": str(uuid4()),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ]

    monkeypatch.setattr("app.api.facilities.list_facilities_db", fake_list_facilities)
    monkeypatch.setattr("app.api.facilities.get_facility_by_id_db", fake_get_facility)
    monkeypatch.setattr("app.api.facilities.get_facility_slots_db", fake_get_slots)
    monkeypatch.setattr("app.api.bookings.get_user_bookings_db", fake_get_user_bookings)


@pytest.mark.asyncio
async def test_list_facilities(mock_facilities_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/facilities")
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["count"] == 2
        assert data["facilities"][0]["name"] == "IITG Gymnasium"


@pytest.mark.asyncio
async def test_get_facility_detail(mock_facilities_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(f"/facilities/{TEST_FACILITY_ID}")
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["facility"]["id"] == TEST_FACILITY_ID


@pytest.mark.asyncio
async def test_get_facility_slots(mock_facilities_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(f"/facilities/{TEST_FACILITY_ID}/slots?date=2026-09-01")
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert len(data["slots"]) == 2
        assert data["slots"][0]["status"] == "open"
        assert data["slots"][1]["status"] == "full"


@pytest.mark.asyncio
async def test_get_my_bookings(mock_facilities_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/bookings/me", headers={"X-User-ID": TEST_USER_1})
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["user_id"] == TEST_USER_1
        assert len(data["bookings"]) == 1
        assert data["bookings"][0]["status"] == "confirmed"
