import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID
from dotenv import load_dotenv
import httpx
from app.db.supabase import get_supabase_client

load_dotenv()

logger = logging.getLogger("lockin.notifications")

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
NOTIFICATION_FROM_EMAIL = os.environ.get("NOTIFICATION_FROM_EMAIL", "notifications@lockin.iitg.ac.in")


async def record_notification_in_db(user_id: str, notif_type: str, payload: Dict[str, Any]) -> None:
    """
    Records a notification entry in the notifications audit trail table.
    """
    try:
        client = get_supabase_client()
        client.table("notifications").insert({
            "user_id": user_id,
            "type": notif_type,
            "payload": payload,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as exc:
        logger.error(f"Failed to record notification in audit table: {exc}")


async def send_email(to_email: str, subject: str, body_text: str, html_content: str) -> bool:
    """
    Sends email via Resend API or logs email to console if API key is not configured.
    """
    if not RESEND_API_KEY:
        logger.info(
            f"[MOCK EMAIL SENT]\nTo: {to_email}\nFrom: {NOTIFICATION_FROM_EMAIL}\nSubject: {subject}\nBody: {body_text}"
        )
        return True

    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": NOTIFICATION_FROM_EMAIL,
                    "to": [to_email],
                    "subject": subject,
                    "text": body_text,
                    "html": html_content,
                },
                timeout=5.0,
            )
            if res.status_code in (200, 201):
                logger.info(f"Resend email sent to {to_email}: {res.json()}")
                return True
            else:
                logger.error(f"Resend API error ({res.status_code}): {res.text}")
                return False
    except Exception as exc:
        logger.error(f"Failed to send email via Resend: {exc}")
        return False


async def notify_booking_confirmation(booking: Dict[str, Any], user_email: str = "student@iitg.ac.in") -> None:
    """
    Sends booking confirmation email and records notification audit trail.
    Isolates errors so booking transaction is never affected.
    """
    try:
        b_id = booking.get("id")
        user_id = booking.get("user_id")
        slot_start = booking.get("slot_start", "")
        slot_end = booking.get("slot_end", "")

        subject = "🏆 Lockin Court Booking Confirmed — IIT Guwahati"
        body = (
            f"Hello Student,\n\n"
            f"Your sports facility booking has been CONFIRMED!\n\n"
            f"Booking ID: {b_id}\n"
            f"Start Time: {slot_start}\n"
            f"End Time: {slot_end}\n\n"
            f"See you on the court!\nLockin Platform"
        )
        html = f"""
        <div style="font-family: monospace; background: #0F1417; color: #F3F4F6; padding: 24px; border: 1px solid #2D373E;">
            <h2 style="color: #C97A2B; margin-top: 0;">LOCKIN COURT BOOKING CONFIRMED</h2>
            <p>Your sports facility booking is locked in.</p>
            <table style="width: 100%; border-collapse: collapse; margin: 16px 0; border: 1px solid #2D373E;">
                <tr><td style="padding: 8px; border: 1px solid #2D373E; color: #9CA3AF;">Booking ID:</td><td style="padding: 8px; border: 1px solid #2D373E; font-weight: bold;">{b_id}</td></tr>
                <tr><td style="padding: 8px; border: 1px solid #2D373E; color: #9CA3AF;">Slot Start:</td><td style="padding: 8px; border: 1px solid #2D373E; color: #10B981;">{slot_start}</td></tr>
                <tr><td style="padding: 8px; border: 1px solid #2D373E; color: #9CA3AF;">Slot End:</td><td style="padding: 8px; border: 1px solid #2D373E; color: #10B981;">{slot_end}</td></tr>
            </table>
            <p style="color: #9CA3AF; font-size: 12px;">IIT Guwahati Sports Board</p>
        </div>
        """

        sent = await send_email(user_email, subject, body, html)
        if sent and user_id:
            await record_notification_in_db(
                user_id=str(user_id),
                notif_type="booking_confirmation",
                payload={"booking_id": b_id, "slot_start": slot_start, "slot_end": slot_end},
            )
    except Exception as exc:
        logger.error(f"Error in notify_booking_confirmation: {exc}")


async def notify_booking_cancellation(booking_id: str, user_id: str, user_email: str = "student@iitg.ac.in") -> None:
    """
    Sends booking cancellation email and records notification audit trail.
    """
    try:
        subject = "🚫 Lockin Court Booking Cancelled — IIT Guwahati"
        body = (
            f"Hello Student,\n\n"
            f"Your sports facility booking ({booking_id}) has been CANCELLED.\n\n"
            f"The time slot has been released for other students.\n\n"
            f"Lockin Platform"
        )
        html = f"""
        <div style="font-family: monospace; background: #0F1417; color: #F3F4F6; padding: 24px; border: 1px solid #2D373E;">
            <h2 style="color: #EF4444; margin-top: 0;">LOCKIN BOOKING CANCELLED</h2>
            <p>Your booking has been cancelled and the time slot was released.</p>
            <p style="color: #9CA3AF; font-size: 12px;">Booking ID: {booking_id}</p>
        </div>
        """

        sent = await send_email(user_email, subject, body, html)
        if sent and user_id:
            await record_notification_in_db(
                user_id=str(user_id),
                notif_type="booking_cancellation",
                payload={"booking_id": booking_id},
            )
    except Exception as exc:
        logger.error(f"Error in notify_booking_cancellation: {exc}")


async def notify_booking_reminder(
    booking: Dict[str, Any],
    reminder_type: str,  # "reminder_24h" or "reminder_30m"
    user_email: str = "student@iitg.ac.in",
) -> None:
    """
    Sends scheduled 24h or 30m booking reminder.
    """
    try:
        b_id = booking.get("id")
        user_id = booking.get("user_id")
        slot_start = booking.get("slot_start", "")

        label = "24-Hour" if reminder_type == "reminder_24h" else "30-Minute"
        subject = f"⏰ Lockin {label} Reminder: Upcoming Court Booking — IIT Guwahati"
        body = (
            f"Hello Student,\n\n"
            f"Reminder: You have an upcoming court booking in {label.lower()}!\n\n"
            f"Booking ID: {b_id}\n"
            f"Start Time: {slot_start}\n\n"
            f"Lockin Platform"
        )
        html = f"""
        <div style="font-family: monospace; background: #0F1417; color: #F3F4F6; padding: 24px; border: 1px solid #2D373E;">
            <h2 style="color: #F59E0B; margin-top: 0;">UPCOMING COURT BOOKING ({label.upper()})</h2>
            <p>Your reserved time slot is starting soon.</p>
            <p style="color: #C97A2B; font-weight: bold;">Start Time: {slot_start}</p>
        </div>
        """

        sent = await send_email(user_email, subject, body, html)
        if sent and user_id:
            await record_notification_in_db(
                user_id=str(user_id),
                notif_type=reminder_type,
                payload={"booking_id": b_id, "slot_start": slot_start, "reminder_type": reminder_type},
            )
    except Exception as exc:
        logger.error(f"Error in notify_booking_reminder: {exc}")
