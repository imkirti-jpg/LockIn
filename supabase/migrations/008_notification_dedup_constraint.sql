-- Lockin Phase 4: Database-Level Notification Deduplication Constraint

-- Creates a unique index preventing multi-process background schedulers
-- from inserting duplicate 24h or 30m reminder notifications for the same booking.
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_notification_reminder
ON notifications (user_id, type, (payload->>'booking_id'))
WHERE type IN ('reminder_24h', 'reminder_30m');
