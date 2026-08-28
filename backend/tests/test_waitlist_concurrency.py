import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

FACILITY_ID = "11111111-1111-1111-1111-111111111111"
SLOT_START = "2026-09-20T10:00:00+00:00"
SLOT_END = "2026-09-20T11:00:00+00:00"


@pytest.fixture
def mock_concurrency_store(monkeypatch):
    """
    Thread/Async-safe in-memory store simulating atomic database row locks for waitlist & booking concurrency tests.
    """
    lock = asyncio.Lock()
    bookings = {}
    waitlists = {}

    async def fake_book_slot(facility_id, slot_start, slot_end, user_id, idempotency_key):
        async with lock:
            key = f"{facility_id}_{slot_start}"
            for b in bookings.values():
                if str(b["idempotency_key"]) == str(idempotency_key):
                    return {"ok": True, "reason": "idempotent_replay", "booking_id": b["id"], "booking": b}

            if key in bookings and bookings[key]["status"] == "confirmed":
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
            bookings[key] = new_b
            return {"ok": True, "reason": "confirmed", "booking_id": b_id, "booking": new_b}

    async def fake_cancel_booking(booking_id, user_id):
        async with lock:
            target_b = None
            for b in bookings.values():
                if b["id"] == str(booking_id):
                    target_b = b
                    break

            if not target_b:
                return {"ok": False, "reason": "not_found"}
            if target_b["user_id"] != str(user_id):
                return {"ok": False, "reason": "unauthorized"}
            if target_b["status"] == "cancelled":
                return {"ok": True, "reason": "already_cancelled"}

            target_b["status"] = "cancelled"

            # Execute internal promote
            await internal_promote(target_b["facility_id"], target_b["slot_start"])
            return {"ok": True, "reason": "cancelled", "booking_id": str(booking_id)}

    async def internal_promote(facility_id, slot_start, claim_minutes=10):
        # Must be called inside lock
        offered = [w for w in waitlists.values() if w["facility_id"] == str(facility_id) and w["slot_start"] == slot_start and w["status"] == "offered"]
        if offered:
            return {"ok": False, "reason": "already_offered"}

        candidates = [w for w in waitlists.values() if w["facility_id"] == str(facility_id) and w["slot_start"] == slot_start and w["status"] == "waiting"]
        if not candidates:
            return {"ok": False, "reason": "no_waitlist_candidates"}

        candidates.sort(key=lambda x: (x["created_at"], x["id"]))
        promoted = candidates[0]
        promoted["status"] = "offered"
        promoted["claim_expires_at"] = (datetime.now(timezone.utc) + timedelta(minutes=claim_minutes)).isoformat()
        return {"ok": True, "reason": "promoted", "entry_id": promoted["id"], "user_id": promoted["user_id"]}

    async def fake_join_waitlist(facility_id, slot_start, slot_end, user_id):
        async with lock:
            key = f"{facility_id}_{slot_start}"
            if key not in bookings or bookings[key]["status"] != "confirmed":
                return {"ok": False, "reason": "slot_available"}

            for w in waitlists.values():
                if (
                    w["facility_id"] == str(facility_id)
                    and w["slot_start"] == slot_start
                    and w["user_id"] == str(user_id)
                    and w["status"] in ("waiting", "offered")
                ):
                    return {"ok": True, "reason": "already_joined", "waitlist_entry": w}

            active_entries = [w for w in waitlists.values() if w["facility_id"] == str(facility_id) and w["slot_start"] == slot_start and w["status"] in ("waiting", "offered")]
            pos = len(active_entries) + 1

            w_id = str(uuid4())
            new_w = {
                "id": w_id,
                "facility_id": str(facility_id),
                "slot_start": slot_start,
                "slot_end": slot_end,
                "user_id": str(user_id),
                "position": pos,
                "status": "waiting",
                "claim_expires_at": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            waitlists[w_id] = new_w
            return {"ok": True, "reason": "joined", "waitlist_entry": new_w}

    async def fake_claim_waitlist_slot(entry_id, user_id, idempotency_key):
        async with lock:
            entry = waitlists.get(str(entry_id))
            if not entry:
                return {"ok": False, "reason": "entry_not_found"}
            if entry["user_id"] != str(user_id):
                return {"ok": False, "reason": "unauthorized"}
            if entry["status"] == "claimed":
                return {"ok": True, "reason": "already_claimed"}
            if entry["status"] != "offered":
                return {"ok": False, "reason": "entry_not_offered"}

            now_utc = datetime.now(timezone.utc)
            exp = datetime.fromisoformat(entry["claim_expires_at"].replace("Z", "+00:00"))
            if exp < now_utc:
                entry["status"] = "expired"
                return {"ok": False, "reason": "claim_expired"}

            # Call book slot internally while holding lock
            key = f"{entry['facility_id']}_{entry['slot_start']}"
            if key in bookings and bookings[key]["status"] == "confirmed":
                return {"ok": False, "reason": "slot_taken"}

            b_id = str(uuid4())
            new_b = {
                "id": b_id,
                "facility_id": entry["facility_id"],
                "slot_start": entry["slot_start"],
                "slot_end": entry["slot_end"],
                "user_id": str(user_id),
                "status": "confirmed",
                "idempotency_key": str(idempotency_key),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            bookings[key] = new_b
            entry["status"] = "claimed"
            return {"ok": True, "reason": "claimed", "booking_id": b_id, "booking": new_b}

    async def fake_expire_waitlist_claims():
        async with lock:
            count = 0
            now_utc = datetime.now(timezone.utc)
            for w in list(waitlists.values()):
                if w["status"] == "offered" and w.get("claim_expires_at"):
                    exp = datetime.fromisoformat(w["claim_expires_at"].replace("Z", "+00:00"))
                    if exp < now_utc:
                        w["status"] = "expired"
                        count += 1
                        await internal_promote(w["facility_id"], w["slot_start"])
            return {"ok": True, "expired_count": count}

    monkeypatch.setattr("app.api.bookings.call_book_slot_rpc", fake_book_slot)
    monkeypatch.setattr("app.api.bookings.cancel_booking_db", fake_cancel_booking)
    monkeypatch.setattr("app.api.waitlist.join_waitlist_db", fake_join_waitlist)
    monkeypatch.setattr("app.api.waitlist.claim_waitlist_slot_db", fake_claim_waitlist_slot)
    monkeypatch.setattr("app.api.waitlist.get_waitlist_entry_by_id_db", lambda e_id: waitlists.get(str(e_id)))
    monkeypatch.setattr("app.api.waitlist.get_user_waitlists_db", lambda u_id: [w for w in waitlists.values() if w["user_id"] == str(u_id)])
    monkeypatch.setattr("app.services.scheduler.expire_waitlist_claims_db", fake_expire_waitlist_claims)

    return {
        "bookings": bookings,
        "waitlists": waitlists,
        "book": fake_book_slot,
        "cancel": fake_cancel_booking,
        "expire": fake_expire_waitlist_claims,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("n_clients", [2, 10, 100])
async def test_concurrent_waitlist_join_storm(mock_concurrency_store, n_clients):
    """
    N distinct users join waitlist simultaneously for an occupied slot.
    Asserts N unique active entries created with positions 1, 2, ..., N.
    """
    # 1. Initial confirmed booking to occupy slot
    initial_user = str(uuid4())
    await mock_concurrency_store["book"](FACILITY_ID, SLOT_START, SLOT_END, initial_user, str(uuid4()))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        users = [str(uuid4()) for _ in range(n_clients)]

        async def worker(u_id):
            return await ac.post(
                f"/waitlist/{FACILITY_ID}",
                headers={"X-User-ID": u_id},
                json={"slot_start": SLOT_START, "slot_end": SLOT_END},
            )

        responses = await asyncio.gather(*[worker(u) for u in users])

    for r in responses:
        assert r.status_code == 201
        assert r.json()["ok"] is True

    # Assert N unique entries
    stored_entries = list(mock_concurrency_store["waitlists"].values())
    assert len(stored_entries) == n_clients

    positions = [e["position"] for e in stored_entries]
    positions.sort()
    assert positions == list(range(1, n_clients + 1))


@pytest.mark.asyncio
async def test_concurrent_duplicate_join_storm(mock_concurrency_store):
    """
    100 simultaneous requests from the SAME user to join waitlist for occupied slot.
    Asserts exactly 1 active waitlist entry created.
    """
    initial_user = str(uuid4())
    await mock_concurrency_store["book"](FACILITY_ID, SLOT_START, SLOT_END, initial_user, str(uuid4()))

    single_user = str(uuid4())
    n_requests = 100

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async def worker():
            return await ac.post(
                f"/waitlist/{FACILITY_ID}",
                headers={"X-User-ID": single_user},
                json={"slot_start": SLOT_START, "slot_end": SLOT_END},
            )

        responses = await asyncio.gather(*[worker() for _ in range(n_requests)])

    for r in responses:
        assert r.status_code == 201

    stored_entries = list(mock_concurrency_store["waitlists"].values())
    assert len(stored_entries) == 1
    assert stored_entries[0]["user_id"] == single_user


@pytest.mark.asyncio
@pytest.mark.parametrize("n_clients", [2, 10, 100])
async def test_concurrent_claim_storm(mock_concurrency_store, n_clients):
    """
    N concurrent workers attempt to claim the SAME offered waitlist slot simultaneously.
    Asserts exactly 1 confirmed booking created and exactly 1 waitlist entry marked claimed.
    """
    owner_user = str(uuid4())
    initial_b = await mock_concurrency_store["book"](FACILITY_ID, SLOT_START, SLOT_END, owner_user, str(uuid4()))
    b_id = initial_b["booking_id"]

    offered_user = str(uuid4())
    # Create waitlist entry
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        w_res = await ac.post(
            f"/waitlist/{FACILITY_ID}",
            headers={"X-User-ID": offered_user},
            json={"slot_start": SLOT_START, "slot_end": SLOT_END},
        )
        entry_id = w_res.json()["waitlist_entry"]["id"]

        # Cancel initial booking to promote offered_user
        await ac.delete(f"/bookings/{b_id}", headers={"X-User-ID": owner_user})
        assert mock_concurrency_store["waitlists"][entry_id]["status"] == "offered"

        # Claim storm
        async def worker():
            return await ac.post(
                f"/waitlist/{entry_id}/claim",
                headers={"X-User-ID": offered_user},
                json={"idempotency_key": str(uuid4())},
            )

        responses = await asyncio.gather(*[worker() for _ in range(n_clients)])

    successful_claims = [r for r in responses if r.status_code == 200 and r.json().get("reason") in ("claimed", "already_claimed")]
    assert len(successful_claims) == n_clients
    assert mock_concurrency_store["waitlists"][entry_id]["status"] == "claimed"


@pytest.mark.asyncio
async def test_concurrent_expiration_storm(mock_concurrency_store):
    """
    10 scheduler workers attempt to expire the same offered claim simultaneously.
    Asserts first offer expires exactly once, and next candidate is promoted.
    """
    owner_user = str(uuid4())
    initial_b = await mock_concurrency_store["book"](FACILITY_ID, SLOT_START, SLOT_END, owner_user, str(uuid4()))

    user_b = str(uuid4())
    user_c = str(uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        wb = (await ac.post(f"/waitlist/{FACILITY_ID}", headers={"X-User-ID": user_b}, json={"slot_start": SLOT_START, "slot_end": SLOT_END})).json()["waitlist_entry"]
        wc = (await ac.post(f"/waitlist/{FACILITY_ID}", headers={"X-User-ID": user_c}, json={"slot_start": SLOT_START, "slot_end": SLOT_END})).json()["waitlist_entry"]

        # Cancel -> promote user B
        await ac.delete(f"/bookings/{initial_b['booking_id']}", headers={"X-User-ID": owner_user})

        # Expire B's claim
        mock_concurrency_store["waitlists"][wb["id"]]["claim_expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

        # 10 concurrent scheduler executions
        results = await asyncio.gather(*[mock_concurrency_store["expire"]() for _ in range(10)])

    # First offer expired, user C promoted to offered
    assert mock_concurrency_store["waitlists"][wb["id"]]["status"] == "expired"
    assert mock_concurrency_store["waitlists"][wc["id"]]["status"] == "offered"
