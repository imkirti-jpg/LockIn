from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from app.services.notifications import (
    notify_booking_cancellation,
    notify_booking_confirmation,
    notify_booking_reminder,
)

TEST_USER_ID = str(uuid4())
TEST_BOOKING_ID = str(uuid4())


@pytest.fixture
def mock_notif_store(monkeypatch):
    store = []

    async def fake_record_db(user_id, notif_type, payload):
        store.append({
            "id": str(uuid4()),
            "user_id": user_id,
            "type": notif_type,
            "payload": payload,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        })

    async def fake_is_sent(booking_id, reminder_type):
        for item in store:
            if item["type"] == reminder_type and item["payload"].get("booking_id") == booking_id:
                return True
        return False

    monkeypatch.setattr("app.services.notifications.record_notification_in_db", fake_record_db)
    monkeypatch.setattr("app.services.scheduler.is_reminder_already_sent", fake_is_sent)
    return {"store": store, "check_sent": fake_is_sent}


@pytest.mark.asyncio
async def test_booking_confirmation_notification(mock_notif_store, monkeypatch):
    sent_emails = []

    async def fake_send_email(to_email, subject, body_text, html_content):
        sent_emails.append({"to": to_email, "subject": subject})
        return True

    monkeypatch.setattr("app.services.notifications.send_email", fake_send_email)

    booking = {
        "id": TEST_BOOKING_ID,
        "facility_id": str(uuid4()),
        "slot_start": "2026-09-01T10:00:00Z",
        "slot_end": "2026-09-01T11:00:00Z",
        "user_id": TEST_USER_ID,
        "status": "confirmed",
    }

    await notify_booking_confirmation(booking, "student@iitg.ac.in")

    assert len(sent_emails) == 1
    assert "Confirmed" in sent_emails[0]["subject"]
    assert len(mock_notif_store["store"]) == 1
    assert mock_notif_store["store"][0]["type"] == "booking_confirmation"


@pytest.mark.asyncio
async def test_cancellation_notification(mock_notif_store, monkeypatch):
    sent_emails = []

    async def fake_send_email(to_email, subject, body_text, html_content):
        sent_emails.append({"to": to_email, "subject": subject})
        return True

    monkeypatch.setattr("app.services.notifications.send_email", fake_send_email)

    await notify_booking_cancellation(TEST_BOOKING_ID, TEST_USER_ID, "student@iitg.ac.in")

    assert len(sent_emails) == 1
    assert "Cancelled" in sent_emails[0]["subject"]
    assert len(mock_notif_store["store"]) == 1
    assert mock_notif_store["store"][0]["type"] == "booking_cancellation"


@pytest.mark.asyncio
async def test_email_failure_isolation(mock_notif_store, monkeypatch):
    """
    Verifies that external email provider failure does not crash or interrupt application logic.
    """
    async def failing_send_email(to_email, subject, body_text, html_content):
        raise RuntimeError("Simulated Resend API timeout")

    monkeypatch.setattr("app.services.notifications.send_email", failing_send_email)

    booking = {
        "id": TEST_BOOKING_ID,
        "user_id": TEST_USER_ID,
        "slot_start": "2026-09-01T10:00:00Z",
        "slot_end": "2026-09-01T11:00:00Z",
    }

    # Should not raise exception
    await notify_booking_confirmation(booking, "student@iitg.ac.in")


@pytest.mark.asyncio
async def test_reminder_deduplication(mock_notif_store, monkeypatch):
    sent_emails = []

    async def fake_send_email(to_email, subject, body_text, html_content):
        sent_emails.append({"to": to_email, "subject": subject})
        return True

    monkeypatch.setattr("app.services.notifications.send_email", fake_send_email)

    booking = {
        "id": TEST_BOOKING_ID,
        "user_id": TEST_USER_ID,
        "slot_start": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        "status": "confirmed",
    }

    check_sent = mock_notif_store["check_sent"]

    # First reminder dispatch
    if not await check_sent(TEST_BOOKING_ID, "reminder_24h"):
        await notify_booking_reminder(booking, "reminder_24h")

    assert len(sent_emails) == 1

    # Second reminder dispatch (simulating repeated scheduler run)
    if not await check_sent(TEST_BOOKING_ID, "reminder_24h"):
        await notify_booking_reminder(booking, "reminder_24h")

    # Second dispatch skipped due to deduplication check
    assert len(sent_emails) == 1
