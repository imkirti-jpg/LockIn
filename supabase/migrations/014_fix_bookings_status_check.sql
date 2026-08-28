-- Lockin Migration 014: Fix bookings_status_check constraint for check-in state

ALTER TABLE bookings
DROP CONSTRAINT IF EXISTS bookings_status_check;

ALTER TABLE bookings
ADD CONSTRAINT bookings_status_check
CHECK (status IN ('confirmed', 'cancelled', 'no_show', 'checked_in'));
