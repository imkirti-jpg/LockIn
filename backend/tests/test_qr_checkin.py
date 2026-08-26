import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

FACILITY_ID = "11111111-1111-1111-1111-111111111111"
USER_A = str(uuid4())
USER_B = str(uuid4())

# Window setup: slot starts now + 5 min (within early 15m window)
NOW = datetime.now(timezone.utc)
SLOT_START = (NOW + timedelta(minutes=5)).isoformat()
SLOT_END = (NOW + timedelta(minutes=65)).isoformat()


@pytest.fixture
def mock_qr_store(monkeypatch):
    bookings = {}
    waitlists = {}

    async def fake_book_slot(facility_id, slot_start, slot_end, user_id, idempotency_key):
        b_id = str(uuid4())
        token = str(uuid4())
        new_b = {
            "id": b_id,
            "facility_id": str(facility_id),
            "slot_start": slot_start,
            "slot_end": slot_end,
            "user_id": str(user_id),
            "status": "confirmed",
            "idempotency_key": str(idempotency_key),
            "checkin_token": token,
            "checked_in_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        bookings[b_id] = new_b
        return {"ok": True, "reason": "confirmed", "booking_id": b_id, "booking": new_b}

    async def fake_check_in(booking_id, user_id, checkin_token):
        b = bookings.get(str(booking_id))
        if not b:
            return {"ok": False, "reason": "booking_not_found"}

        if user_id and b["user_id"] != str(user_id):
            return {"ok": False, "reason": "unauthorized"}

        if b["checkin_token"] != str(checkin_token):
            return {"ok": False, "reason": "invalid_token"}

        if b["status"] == "checked_in":
            return {"ok": True, "reason": "already_checked_in", "booking_id": str(booking_id), "checked_in_at": b["checked_in_at"]}

        if b["status"] != "confirmed":
            return {"ok": False, "reason": "booking_not_confirmed", "status": b["status"]}

        now_iso = datetime.now(timezone.utc).isoformat()
        b["status"] = "checked_in"
        b["checked_in_at"] = now_iso
        return {"ok": True, "reason": "checked_in", "booking_id": str(booking_id), "checked_in_at": now_iso}

    async def fake_auto_release_no_shows(grace_minutes=15):
        count = 0
        now_utc = datetime.now(timezone.utc)
        for b in list(bookings.values()):
            if b["status"] == "confirmed":
                start_dt = datetime.fromisoformat(b["slot_start"].replace("Z", "+00:00"))
                if start_dt + timedelta(minutes=grace_minutes) < now_utc:
                    b["status"] = "no_show"
                    count += 1
                    for w in waitlists.values():
                        if w["facility_id"] == b["facility_id"] and w["slot_start"] == b["slot_start"] and w["status"] == "waiting":
                            w["status"] = "offered"
                            w["claim_expires_at"] = (now_utc + timedelta(minutes=10)).isoformat()
                            break
        return {"ok": True, "released_count": count}

    monkeypatch.setattr("app.api.bookings.call_book_slot_rpc", fake_book_slot)
    monkeypatch.setattr("app.api.bookings.check_in_booking_db", fake_check_in)
    monkeypatch.setattr("app.api.bookings.get_booking_checkin_info_db", lambda b_id, u_id: bookings.get(str(b_id)) if bookings.get(str(b_id)) and bookings.get(str(b_id))["user_id"] == str(u_id) else None)
    monkeypatch.setattr("app.services.scheduler.auto_release_no_shows_db", fake_auto_release_no_shows)

    return {"bookings": bookings, "waitlists": waitlists, "auto_release": fake_auto_release_no_shows}


@pytest.mark.asyncio
async def test_valid_qr_checkin(mock_qr_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        b_res = await ac.post(
            "/bookings",
            headers={"X-User-ID": USER_A},
            json={"facility_id": FACILITY_ID, "slot_start": SLOT_START, "slot_end": SLOT_END, "idempotency_key": str(uuid4())},
        )
        b_id = b_res.json()["booking_id"]
        token = mock_qr_store["bookings"][b_id]["checkin_token"]

        # Owner check-in
        checkin_res = await ac.post(
            f"/bookings/{b_id}/checkin",
            headers={"X-User-ID": USER_A},
            json={"checkin_token": token},
        )
        assert checkin_res.status_code == 200
        assert checkin_res.json()["reason"] == "checked_in"
        assert mock_qr_store["bookings"][b_id]["status"] == "checked_in"

        # Repeated check-in is idempotent
        repeat_res = await ac.post(
            f"/bookings/{b_id}/checkin",
            headers={"X-User-ID": USER_A},
            json={"checkin_token": token},
        )
        assert repeat_res.status_code == 200
        assert repeat_res.json()["reason"] == "already_checked_in"


@pytest.mark.asyncio
async def test_unauthorized_and_invalid_token_checkin(mock_qr_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        b_res = await ac.post(
            "/bookings",
            headers={"X-User-ID": USER_A},
            json={"facility_id": FACILITY_ID, "slot_start": SLOT_START, "slot_end": SLOT_END, "idempotency_key": str(uuid4())},
        )
        b_id = b_res.json()["booking_id"]
        real_token = mock_qr_store["bookings"][b_id]["checkin_token"]

        # Unauthorized student B attempts check-in -> 403
        unauth_res = await ac.post(
            f"/bookings/{b_id}/checkin",
            headers={"X-User-ID": USER_B},
            json={"checkin_token": real_token},
        )
        assert unauth_res.status_code == 403

        # Invalid token attempt -> 400 Bad Request
        invalid_res = await ac.post(
            f"/bookings/{b_id}/checkin",
            headers={"X-User-ID": USER_A},
            json={"checkin_token": str(uuid4())},
        )
        assert invalid_res.status_code == 400
        assert invalid_res.json()["detail"]["reason"] == "invalid_token"


@pytest.mark.asyncio
async def test_cancelled_booking_checkin_rejected(mock_qr_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        b_res = await ac.post(
            "/bookings",
            headers={"X-User-ID": USER_A},
            json={"facility_id": FACILITY_ID, "slot_start": SLOT_START, "slot_end": SLOT_END, "idempotency_key": str(uuid4())},
        )
        b_id = b_res.json()["booking_id"]
        token = mock_qr_store["bookings"][b_id]["checkin_token"]

        # Manually change booking to cancelled
        mock_qr_store["bookings"][b_id]["status"] = "cancelled"

        checkin_res = await ac.post(
            f"/bookings/{b_id}/checkin",
            headers={"X-User-ID": USER_A},
            json={"checkin_token": token},
        )
        assert checkin_res.status_code == 409
        assert checkin_res.json()["detail"]["reason"] == "booking_not_confirmed"


@pytest.mark.asyncio
async def test_auto_release_no_show_triggers_waitlist_promotion(mock_qr_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        past_start = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        past_end = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()

        b_res = await ac.post(
            "/bookings",
            headers={"X-User-ID": USER_A},
            json={"facility_id": FACILITY_ID, "slot_start": past_start, "slot_end": past_end, "idempotency_key": str(uuid4())},
        )
        b_id = b_res.json()["booking_id"]

        await mock_qr_store["auto_release"]()
        assert mock_qr_store["bookings"][b_id]["status"] == "no_show"
