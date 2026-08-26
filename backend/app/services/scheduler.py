import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from app.db.supabase import auto_release_no_shows_db, expire_waitlist_claims_db, get_supabase_client
from app.services.notifications import notify_booking_reminder

load_dotenv()

logger = logging.getLogger("lockin.scheduler")

scheduler: AsyncIOScheduler = None


async def is_reminder_already_sent(booking_id: str, reminder_type: str) -> bool:
    """
    Deduplication check: queries notifications table to verify if reminder was already sent.
    """
    try:
        client = get_supabase_client()
        res = (
            client.table("notifications")
            .select("id")
            .eq("type", reminder_type)
            .eq("payload->>booking_id", booking_id)
            .execute()
        )
        return len(res.data or []) > 0
    except Exception as exc:
        logger.error(f"Error checking notification deduplication in DB: {exc}")
        return False


async def process_reminders() -> None:
    """
    Scheduled job scanning for confirmed bookings approaching 24h and 30m windows.
    Runs deduplicated notification dispatch.
    """
    logger.info("Executing scheduled reminder scan...")
    now_utc = datetime.now(timezone.utc)

    window_24h_start = (now_utc + timedelta(hours=23, minutes=30)).isoformat()
    window_24h_end = (now_utc + timedelta(hours=24, minutes=30)).isoformat()

    window_30m_start = (now_utc + timedelta(minutes=20)).isoformat()
    window_30m_end = (now_utc + timedelta(minutes=40)).isoformat()

    client = get_supabase_client()

    try:
        res_24h = (
            client.table("bookings")
            .select("id, facility_id, slot_start, slot_end, user_id, status")
            .eq("status", "confirmed")
            .gte("slot_start", window_24h_start)
            .lte("slot_start", window_24h_end)
            .execute()
        )
        candidates_24h = res_24h.data or []

        for booking in candidates_24h:
            b_id = booking["id"]
            if not await is_reminder_already_sent(b_id, "reminder_24h"):
                logger.info(f"Sending 24h reminder for booking {b_id}")
                await notify_booking_reminder(booking, "reminder_24h")

        res_30m = (
            client.table("bookings")
            .select("id, facility_id, slot_start, slot_end, user_id, status")
            .eq("status", "confirmed")
            .gte("slot_start", window_30m_start)
            .lte("slot_start", window_30m_end)
            .execute()
        )
        candidates_30m = res_30m.data or []

        for booking in candidates_30m:
            b_id = booking["id"]
            if not await is_reminder_already_sent(b_id, "reminder_30m"):
                logger.info(f"Sending 30m reminder for booking {b_id}")
                await notify_booking_reminder(booking, "reminder_30m")

    except Exception as exc:
        logger.error(f"Error processing scheduled reminders: {exc}")


async def process_expired_waitlist_claims() -> None:
    """
    Scheduled job scanning for expired waitlist claims and promoting next student in queue.
    """
    try:
        res = await expire_waitlist_claims_db()
        expired_count = res.get("expired_count", 0)
        if expired_count > 0:
            logger.info(f"Expired {expired_count} waitlist claims and promoted next candidates.")
    except Exception as exc:
        logger.error(f"Error processing expired waitlist claims: {exc}")


async def process_no_show_auto_release() -> None:
    """
    Scheduled job scanning for un-checked-in confirmed bookings past grace period.
    Transitions status to no_show and promotes waitlist.
    """
    try:
        res = await auto_release_no_shows_db()
        released_count = res.get("released_count", 0)
        if released_count > 0:
            logger.info(f"Auto-released {released_count} no-show bookings and triggered waitlist promotion.")
    except Exception as exc:
        logger.error(f"Error processing no-show auto release: {exc}")


def start_scheduler() -> AsyncIOScheduler:
    """
    Initializes and starts background APScheduler.
    """
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            process_reminders,
            "interval",
            minutes=5,
            id="process_reminders_job",
            replace_existing=True,
        )
        scheduler.add_job(
            process_expired_waitlist_claims,
            "interval",
            minutes=1,
            id="process_expired_waitlist_claims_job",
            replace_existing=True,
        )
        scheduler.add_job(
            process_no_show_auto_release,
            "interval",
            minutes=1,
            id="process_no_show_auto_release_job",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("APScheduler background engine started (5m reminders, 1m waitlist expiry, 1m no-show release)")
    return scheduler
