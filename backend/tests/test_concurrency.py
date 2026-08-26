import asyncio
import logging
import time
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

logger = logging.getLogger("lockin.concurrency_test")
TEST_FACILITY_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def concurrency_mock_rpc(monkeypatch):
    """
    Simulates atomic Postgres RPC execution under async concurrency.
    Ensures exact-slot single-winner guarantee in memory.
    """
    confirmed_booking = None
    lock = asyncio.Lock()

    async def fake_rpc(facility_id, slot_start, slot_end, user_id, idempotency_key):
        nonlocal confirmed_booking
        async with lock:
            if confirmed_booking is not None:
                return {
                    "ok": False,
                    "reason": "slot_taken",
                    "booking_id": None,
                    "booking": None,
                }

            # Simulates successful first row insert
            confirmed_booking = {
                "id": str(uuid4()),
                "facility_id": str(facility_id),
                "slot_start": slot_start,
                "slot_end": slot_end,
                "user_id": str(user_id),
                "status": "confirmed",
                "idempotency_key": str(idempotency_key),
            }
            return {
                "ok": True,
                "reason": "confirmed",
                "booking_id": confirmed_booking["id"],
                "booking": confirmed_booking,
            }

    monkeypatch.setattr("app.api.bookings.call_book_slot_rpc", fake_rpc)
    return lambda: confirmed_booking


async def run_concurrency_storm(n: int, client: AsyncClient):
    """
    Fires N concurrent HTTP requests targeting the exact same facility and slot.
    Uses unique user_id and unique idempotency_key per request.
    """
    target_slot_start = "2026-09-02T18:00:00Z"
    target_slot_end = "2026-09-02T19:00:00Z"

    async def send_single_request():
        simulated_user = str(uuid4())
        idempotency_key = str(uuid4())
        payload = {
            "facility_id": TEST_FACILITY_ID,
            "slot_start": target_slot_start,
            "slot_end": target_slot_end,
            "idempotency_key": idempotency_key,
        }
        return await client.post(
            "/bookings",
            json=payload,
            headers={"X-User-ID": simulated_user},
        )

    start_time = time.perf_counter()
    responses = await asyncio.gather(*[send_single_request() for _ in range(n)])
    duration_ms = (time.perf_counter() - start_time) * 1000

    confirmed = [r for r in responses if r.status_code == 201]
    rejected = [r for r in responses if r.status_code == 409]

    print(f"\nLockin Concurrency Test (N={n})")
    print("-----------------------")
    print(f"Requests:       {n}")
    print(f"Confirmed:      {len(confirmed)}")
    print(f"Rejected:       {len(rejected)}")
    print(f"Duration:       {duration_ms:.2f} ms")
    print(f"Result:         {'PASS' if len(confirmed) == 1 and len(rejected) == n - 1 else 'FAIL'}")

    return {
        "n": n,
        "confirmed": len(confirmed),
        "rejected": len(rejected),
        "duration_ms": duration_ms,
        "responses": responses,
    }


@pytest.mark.asyncio
async def test_concurrency_n_2(concurrency_mock_rpc):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await run_concurrency_storm(2, client)
        assert res["confirmed"] == 1
        assert res["rejected"] == 1


@pytest.mark.asyncio
async def test_concurrency_n_10(concurrency_mock_rpc):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await run_concurrency_storm(10, client)
        assert res["confirmed"] == 1
        assert res["rejected"] == 9


@pytest.mark.asyncio
async def test_concurrency_n_100(concurrency_mock_rpc):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await run_concurrency_storm(100, client)
        assert res["confirmed"] == 1
        assert res["rejected"] == 99
