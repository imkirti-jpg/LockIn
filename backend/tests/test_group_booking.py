import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

FACILITY_ID = "11111111-1111-1111-1111-111111111111"
HOST_USER = str(uuid4())
MEMBER_1 = str(uuid4())
MEMBER_2 = str(uuid4())

SLOT_START = "2026-09-25T10:00:00+00:00"
SLOT_END = "2026-09-25T11:00:00+00:00"


@pytest.fixture
def mock_group_store(monkeypatch):
    bookings = {}
    members = {}

    async def fake_book_slot(facility_id, slot_start, slot_end, user_id, idempotency_key):
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
        # Host is added as confirmed member
        m_id = str(uuid4())
        members[m_id] = {"id": m_id, "booking_id": b_id, "user_id": str(user_id), "status": "confirmed"}
        return {"ok": True, "reason": "confirmed", "booking_id": b_id, "booking": new_b}

    async def fake_add_members(booking_id, host_id, member_user_ids):
        b = bookings.get(str(booking_id))
        if not b:
            return {"ok": False, "reason": "booking_not_found"}

        if b["user_id"] != str(host_id):
            return {"ok": False, "reason": "unauthorized"}

        max_size = 4
        curr_count = len([m for m in members.values() if m["booking_id"] == str(booking_id) and m["status"] != "declined"])
        if curr_count + len(member_user_ids) > max_size:
            return {"ok": False, "reason": "group_size_exceeded", "max_allowed": max_size}

        added = 0
        for uid in member_user_ids:
            if str(uid) != str(host_id):
                m_id = str(uuid4())
                members[m_id] = {"id": m_id, "booking_id": str(booking_id), "user_id": str(uid), "status": "invited"}
                added += 1
        return {"ok": True, "reason": "members_added", "added_count": added, "booking_id": str(booking_id)}

    async def fake_respond(member_id, user_id, response_status):
        m = members.get(str(member_id))
        if not m:
            return {"ok": False, "reason": "invitation_not_found"}
        if m["user_id"] != str(user_id):
            return {"ok": False, "reason": "unauthorized"}

        m["status"] = response_status
        return {"ok": True, "reason": "invitation_updated", "member_id": str(member_id), "status": response_status}

    async def fake_get_booking_members(booking_id):
        return [m for m in members.values() if m["booking_id"] == str(booking_id)]

    async def fake_get_user_invitations(user_id):
        return [m for m in members.values() if m["user_id"] == str(user_id) and m["status"] == "invited"]

    monkeypatch.setattr("app.api.bookings.call_book_slot_rpc", fake_book_slot)
    monkeypatch.setattr("app.api.bookings.add_booking_members_db", fake_add_members)
    monkeypatch.setattr("app.api.bookings.get_booking_members_db", fake_get_booking_members)
    monkeypatch.setattr("app.api.bookings.get_user_invitations_db", fake_get_user_invitations)
    monkeypatch.setattr("app.api.bookings.respond_booking_invitation_db", fake_respond)

    return {"bookings": bookings, "members": members}


@pytest.mark.asyncio
async def test_group_booking_invite_and_respond(mock_group_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Host creates booking
        b_res = await ac.post(
            "/bookings",
            headers={"X-User-ID": HOST_USER},
            json={"facility_id": FACILITY_ID, "slot_start": SLOT_START, "slot_end": SLOT_END, "idempotency_key": str(uuid4())},
        )
        b_id = b_res.json()["booking_id"]

        # 2. Host invites MEMBER_1 and MEMBER_2
        add_res = await ac.post(
            f"/bookings/{b_id}/members",
            headers={"X-User-ID": HOST_USER},
            json={"member_user_ids": [MEMBER_1, MEMBER_2]},
        )
        assert add_res.status_code == 200
        assert add_res.json()["added_count"] == 2

        # 3. MEMBER_1 checks pending invitations
        inv_res = await ac.get("/bookings/invitations/me", headers={"X-User-ID": MEMBER_1})
        assert inv_res.status_code == 200
        invitations = inv_res.json()["invitations"]
        assert len(invitations) == 1
        m1_inv_id = invitations[0]["id"]

        # 4. MEMBER_1 accepts invitation -> status confirmed
        resp_res = await ac.post(
            f"/bookings/invitations/{m1_inv_id}/respond",
            headers={"X-User-ID": MEMBER_1},
            json={"response": "confirmed"},
        )
        assert resp_res.status_code == 200
        assert resp_res.json()["status"] == "confirmed"


@pytest.mark.asyncio
async def test_group_size_exceeded_rejected(mock_group_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        b_res = await ac.post(
            "/bookings",
            headers={"X-User-ID": HOST_USER},
            json={"facility_id": FACILITY_ID, "slot_start": SLOT_START, "slot_end": SLOT_END, "idempotency_key": str(uuid4())},
        )
        b_id = b_res.json()["booking_id"]

        # Attempt to invite 10 users exceeding max_group_size (4)
        large_group = [str(uuid4()) for _ in range(10)]
        add_res = await ac.post(
            f"/bookings/{b_id}/members",
            headers={"X-User-ID": HOST_USER},
            json={"member_user_ids": large_group},
        )
        assert add_res.status_code == 400
        assert add_res.json()["detail"]["reason"] == "group_size_exceeded"
