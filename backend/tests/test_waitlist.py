import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from app.db.supabase import get_supabase_client
from app.main import app

FACILITY_ID = "11111111-1111-1111-1111-111111111111"
USER_A = str(uuid4())
USER_B = str(uuid4())
USER_C = str(uuid4())

SLOT_START = "2026-09-10T10:00:00+00:00"
SLOT_END = "2026-09-10T11:00:00+00:00"


@pytest.fixture
def mock_db_store(monkeypatch):
    """
    In-memory isolated test mock database store for waitlist and booking state machine.
    """
    bookings = {}
    waitlists = {}

    async def fake_book_slot(facility_id, slot_start, slot_end, user_id, idempotency_key):
        key = f"{facility_id}_{slot_start}"
        # Check idempotency
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

        # Trigger promotion on cancel
        await fake_promote_on_cancel(target_b["facility_id"], target_b["slot_start"])
        return {"ok": True, "reason": "cancelled", "booking_id": str(booking_id)}

    async def fake_join_waitlist(facility_id, slot_start, slot_end, user_id):
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

        pos = len([w for w in waitlists.values() if w["facility_id"] == str(facility_id) and w["slot_start"] == slot_start and w["status"] in ("waiting", "offered")]) + 1
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

    async def fake_promote_on_cancel(facility_id, slot_start, claim_minutes=10):
        candidates = [
            w for w in waitlists.values()
            if w["facility_id"] == str(facility_id)
            and w["slot_start"] == slot_start
            and w["status"] == "waiting"
        ]
        if not candidates:
            return {"ok": False, "reason": "no_waitlist_candidates"}

        candidates.sort(key=lambda x: (x["created_at"], x["id"]))
        promoted = candidates[0]
        promoted["status"] = "offered"
        promoted["claim_expires_at"] = (datetime.now(timezone.utc) + timedelta(minutes=claim_minutes)).isoformat()
        return {"ok": True, "reason": "promoted", "entry_id": promoted["id"], "user_id": promoted["user_id"]}

    async def fake_claim_waitlist_slot(entry_id, user_id, idempotency_key):
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

        book_res = await fake_book_slot(entry["facility_id"], entry["slot_start"], entry["slot_end"], user_id, idempotency_key)
        if book_res.get("ok"):
            entry["status"] = "claimed"
            return {"ok": True, "reason": "claimed", "booking_id": book_res["booking_id"], "booking": book_res["booking"]}
        return book_res

    async def fake_expire_waitlist_claims():
        count = 0
        now_utc = datetime.now(timezone.utc)
        for w in list(waitlists.values()):
            if w["status"] == "offered" and w.get("claim_expires_at"):
                exp = datetime.fromisoformat(w["claim_expires_at"].replace("Z", "+00:00"))
                if exp < now_utc:
                    w["status"] = "expired"
                    count += 1
                    await fake_promote_on_cancel(w["facility_id"], w["slot_start"])
        return {"ok": True, "expired_count": count}

    monkeypatch.setattr("app.api.bookings.call_book_slot_rpc", fake_book_slot)
    monkeypatch.setattr("app.api.bookings.cancel_booking_db", fake_cancel_booking)
    monkeypatch.setattr("app.api.waitlist.join_waitlist_db", fake_join_waitlist)
    monkeypatch.setattr("app.api.waitlist.claim_waitlist_slot_db", fake_claim_waitlist_slot)
    monkeypatch.setattr("app.api.waitlist.get_waitlist_entry_by_id_db", lambda e_id: waitlists.get(str(e_id)))
    monkeypatch.setattr("app.api.waitlist.get_user_waitlists_db", lambda u_id: [w for w in waitlists.values() if w["user_id"] == str(u_id)])
    monkeypatch.setattr("app.services.scheduler.expire_waitlist_claims_db", fake_expire_waitlist_claims)

    return {"bookings": bookings, "waitlists": waitlists, "book": fake_book_slot, "expire": fake_expire_waitlist_claims}


@pytest.mark.asyncio
async def test_waitlist_open_slot_rejected(mock_db_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"X-User-ID": USER_A}
        res = await ac.post(
            f"/waitlist/{FACILITY_ID}",
            headers=headers,
            json={"slot_start": SLOT_START, "slot_end": SLOT_END},
        )
        assert res.status_code == 400
        assert res.json()["detail"]["reason"] == "slot_available"


@pytest.mark.asyncio
async def test_waitlist_fifo_and_promotion(mock_db_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. User A books the slot
        book_res = await ac.post(
            "/bookings",
            headers={"X-User-ID": USER_A},
            json={
                "facility_id": FACILITY_ID,
                "slot_start": SLOT_START,
                "slot_end": SLOT_END,
                "idempotency_key": str(uuid4()),
            },
        )
        assert book_res.status_code == 201
        booking_id = book_res.json()["booking_id"]

        # 2. User B joins waitlist -> Position #1
        w_res_b = await ac.post(
            f"/waitlist/{FACILITY_ID}",
            headers={"X-User-ID": USER_B},
            json={"slot_start": SLOT_START, "slot_end": SLOT_END},
        )
        assert w_res_b.status_code == 201
        entry_b = w_res_b.json()["waitlist_entry"]
        assert entry_b["position"] == 1
        assert entry_b["status"] == "waiting"

        # 3. User C joins waitlist -> Position #2
        w_res_c = await ac.post(
            f"/waitlist/{FACILITY_ID}",
            headers={"X-User-ID": USER_C},
            json={"slot_start": SLOT_START, "slot_end": SLOT_END},
        )
        assert w_res_c.status_code == 201
        entry_c = w_res_c.json()["waitlist_entry"]
        assert entry_c["position"] == 2

        # 4. User B joins duplicate waitlist -> Returns existing entry #1
        dup_res = await ac.post(
            f"/waitlist/{FACILITY_ID}",
            headers={"X-User-ID": USER_B},
            json={"slot_start": SLOT_START, "slot_end": SLOT_END},
        )
        assert dup_res.status_code == 201
        assert dup_res.json()["reason"] == "already_joined"

        # 5. User A cancels booking -> User B promoted to offered!
        cancel_res = await ac.delete(f"/bookings/{booking_id}", headers={"X-User-ID": USER_A})
        assert cancel_res.status_code == 200

        b_waitlist = mock_db_store["waitlists"][entry_b["id"]]
        assert b_waitlist["status"] == "offered"
        assert b_waitlist["claim_expires_at"] is not None

        # 6. User C attempts unauthorized claim of B's offer -> 403 Forbidden
        unauth_claim = await ac.post(
            f"/waitlist/{entry_b['id']}/claim",
            headers={"X-User-ID": USER_C},
            json={"idempotency_key": str(uuid4())},
        )
        assert unauth_claim.status_code == 403

        # 7. User B claims offer -> Booking confirmed & status claimed!
        claim_res = await ac.post(
            f"/waitlist/{entry_b['id']}/claim",
            headers={"X-User-ID": USER_B},
            json={"idempotency_key": str(uuid4())},
        )
        assert claim_res.status_code == 200
        assert claim_res.json()["reason"] == "claimed"
        assert b_waitlist["status"] == "claimed"


@pytest.mark.asyncio
async def test_waitlist_claim_expiration_promotes_next(mock_db_store):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # User A books
        b_res = await ac.post(
            "/bookings",
            headers={"X-User-ID": USER_A},
            json={"facility_id": FACILITY_ID, "slot_start": SLOT_START, "slot_end": SLOT_END, "idempotency_key": str(uuid4())},
        )
        b_id = b_res.json()["booking_id"]

        # User B & User C join waitlist
        w_b = (await ac.post(f"/waitlist/{FACILITY_ID}", headers={"X-User-ID": USER_B}, json={"slot_start": SLOT_START, "slot_end": SLOT_END})).json()["waitlist_entry"]
        w_c = (await ac.post(f"/waitlist/{FACILITY_ID}", headers={"X-User-ID": USER_C}, json={"slot_start": SLOT_START, "slot_end": SLOT_END})).json()["waitlist_entry"]

        # User A cancels -> B promoted
        await ac.delete(f"/bookings/{b_id}", headers={"X-User-ID": USER_A})
        assert mock_db_store["waitlists"][w_b["id"]]["status"] == "offered"

        # Fast forward B's claim expiry to past
        mock_db_store["waitlists"][w_b["id"]]["claim_expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

        # Run claim expiry scheduler
        await mock_db_store["expire"]()

        # B is now expired, C is promoted to offered!
        assert mock_db_store["waitlists"][w_b["id"]]["status"] == "expired"
        assert mock_db_store["waitlists"][w_c["id"]]["status"] == "offered"
