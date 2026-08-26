import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

FACILITY_ID = "11111111-1111-1111-1111-111111111111"
HOST_USER = str(uuid4())
SLOT_START = "2026-09-30T10:00:00+00:00"
SLOT_END = "2026-09-30T11:00:00+00:00"


@pytest.fixture
def mock_group_concurrency_store(monkeypatch):
    lock = asyncio.Lock()
    bookings = {}
    members = {}

    async def fake_book_slot(facility_id, slot_start, slot_end, user_id, idempotency_key):
        async with lock:
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
            # Host added as confirmed
            m_id = str(uuid4())
            members[m_id] = {"id": m_id, "booking_id": b_id, "user_id": str(user_id), "status": "confirmed"}
            return {"ok": True, "reason": "confirmed", "booking_id": b_id, "booking": new_b}

    async def fake_cancel_booking(booking_id, user_id):
        async with lock:
            b = bookings.get(str(booking_id))
            if not b:
                return {"ok": False, "reason": "not_found"}
            if b["user_id"] != str(user_id):
                return {"ok": False, "reason": "unauthorized"}
            b["status"] = "cancelled"
            return {"ok": True, "reason": "cancelled", "booking_id": str(booking_id)}

    async def fake_add_members(booking_id, host_id, member_user_ids):
        async with lock:
            b = bookings.get(str(booking_id))
            if not b:
                return {"ok": False, "reason": "booking_not_found"}

            if b["user_id"] != str(host_id):
                return {"ok": False, "reason": "unauthorized"}

            if b["status"] != "confirmed":
                return {"ok": False, "reason": "booking_not_active"}

            max_size = 4
            curr_active = [m for m in members.values() if m["booking_id"] == str(booking_id) and m["status"] != "declined"]
            if len(curr_active) + len(member_user_ids) > max_size:
                return {"ok": False, "reason": "group_size_exceeded", "max_allowed": max_size}

            added = 0
            for uid in member_user_ids:
                if str(uid) != str(host_id):
                    # Check unique invitation
                    existing = [m for m in members.values() if m["booking_id"] == str(booking_id) and m["user_id"] == str(uid)]
                    if not existing:
                        m_id = str(uuid4())
                        members[m_id] = {"id": m_id, "booking_id": str(booking_id), "user_id": str(uid), "status": "invited"}
                        added += 1
            return {"ok": True, "reason": "members_added", "added_count": added, "booking_id": str(booking_id)}

    async def fake_respond(member_id, user_id, response_status):
        async with lock:
            m = members.get(str(member_id))
            if not m:
                return {"ok": False, "reason": "invitation_not_found"}
            if m["user_id"] != str(user_id):
                return {"ok": False, "reason": "unauthorized"}

            b = bookings.get(m["booking_id"])
            if b and b["status"] != "confirmed":
                return {"ok": False, "reason": "booking_not_active"}

            m["status"] = response_status
            return {"ok": True, "reason": "invitation_updated", "member_id": str(member_id), "status": response_status}

    monkeypatch.setattr("app.api.bookings.call_book_slot_rpc", fake_book_slot)
    monkeypatch.setattr("app.api.bookings.cancel_booking_db", fake_cancel_booking)
    monkeypatch.setattr("app.api.bookings.add_booking_members_db", fake_add_members)
    monkeypatch.setattr("app.api.bookings.get_booking_members_db", lambda booking_id: [m for m in members.values() if m["booking_id"] == str(booking_id)])
    monkeypatch.setattr("app.api.bookings.respond_booking_invitation_db", fake_respond)

    return {"bookings": bookings, "members": members}


@pytest.mark.asyncio
async def test_concurrent_group_capacity_enforcement(mock_group_concurrency_store):
    """
    Max group size = 4. Host (1) + 2 confirmed members = 3 members current.
    100 concurrent requests attempt to add 1 new member each.
    Expected: Exactly 1 request succeeds (reaching max size 4). 99 fail with group_size_exceeded.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Create booking
        b_res = await ac.post(
            "/bookings",
            headers={"X-User-ID": HOST_USER},
            json={"facility_id": FACILITY_ID, "slot_start": SLOT_START, "slot_end": SLOT_END, "idempotency_key": str(uuid4())},
        )
        b_id = b_res.json()["booking_id"]

        # Add 2 members (total = 3, capacity = 4)
        m1, m2 = str(uuid4()), str(uuid4())
        await ac.post(f"/bookings/{b_id}/members", headers={"X-User-ID": HOST_USER}, json={"member_user_ids": [m1, m2]})

        # 100 concurrent requests trying to add unique candidates
        candidates = [str(uuid4()) for _ in range(100)]

        async def worker(cand_id):
            return await ac.post(
                f"/bookings/{b_id}/members",
                headers={"X-User-ID": HOST_USER},
                json={"member_user_ids": [cand_id]},
            )

        responses = await asyncio.gather(*[worker(c) for c in candidates])

    successes = [r for r in responses if r.status_code == 200 and r.json().get("added_count") == 1]
    failures = [r for r in responses if r.status_code == 400 and r.json().get("detail", {}).get("reason") == "group_size_exceeded"]

    assert len(successes) == 1
    assert len(failures) == 99

    # Total active members in DB is exactly 4
    active_m = [m for m in mock_group_concurrency_store["members"].values() if m["booking_id"] == b_id]
    assert len(active_m) == 4


@pytest.mark.asyncio
async def test_concurrent_duplicate_invitations_storm(mock_group_concurrency_store):
    """
    Same host attempts to invite the SAME user 100 times concurrently.
    Expected: Exactly 1 active invitation created. Zero duplicate booking_members rows.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        b_res = await ac.post(
            "/bookings",
            headers={"X-User-ID": HOST_USER},
            json={"facility_id": FACILITY_ID, "slot_start": SLOT_START, "slot_end": SLOT_END, "idempotency_key": str(uuid4())},
        )
        b_id = b_res.json()["booking_id"]
        target_user = str(uuid4())

        async def worker():
            return await ac.post(
                f"/bookings/{b_id}/members",
                headers={"X-User-ID": HOST_USER},
                json={"member_user_ids": [target_user]},
            )

        responses = await asyncio.gather(*[worker() for _ in range(100)])

    for r in responses:
        assert r.status_code in (200, 400)

    user_invites = [m for m in mock_group_concurrency_store["members"].values() if m["booking_id"] == b_id and m["user_id"] == target_user]
    assert len(user_invites) == 1


@pytest.mark.asyncio
async def test_unauthorized_and_cancelled_group_actions(mock_group_concurrency_store):
    """
    - Non-owner attempts member additions -> 403 Forbidden
    - 100 requests from non-invitees attempting to accept invitation -> 403 Forbidden
    - Cancelled booking attempts member addition or invitation response -> 400 Bad Request
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        b_res = await ac.post(
            "/bookings",
            headers={"X-User-ID": HOST_USER},
            json={"facility_id": FACILITY_ID, "slot_start": SLOT_START, "slot_end": SLOT_END, "idempotency_key": str(uuid4())},
        )
        b_id = b_res.json()["booking_id"]
        m1 = str(uuid4())
        stranger = str(uuid4())

        # Non-owner attempts member addition
        unauth_add = await ac.post(f"/bookings/{b_id}/members", headers={"X-User-ID": stranger}, json={"member_user_ids": [m1]})
        assert unauth_add.status_code == 403

        # Host invites m1
        await ac.post(f"/bookings/{b_id}/members", headers={"X-User-ID": HOST_USER}, json={"member_user_ids": [m1]})
        m1_inv_id = [m["id"] for m in mock_group_concurrency_store["members"].values() if m["user_id"] == m1][0]

        # 100 requests from stranger attempting to accept m1's invitation -> all 403
        responses = await asyncio.gather(*[
            ac.post(f"/bookings/invitations/{m1_inv_id}/respond", headers={"X-User-ID": stranger}, json={"response": "confirmed"})
            for _ in range(100)
        ])
        for r in responses:
            assert r.status_code == 403

        # Cancel booking
        await ac.delete(f"/bookings/{b_id}", headers={"X-User-ID": HOST_USER})

        # Cancelled booking attempts member addition -> 400
        post_cancel_add = await ac.post(f"/bookings/{b_id}/members", headers={"X-User-ID": HOST_USER}, json={"member_user_ids": [str(uuid4())]})
        assert post_cancel_add.status_code == 400
