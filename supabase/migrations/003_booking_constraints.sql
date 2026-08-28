-- Lockin Database Correctness Constraints

-- 1. Idempotency Key Uniqueness:
-- Prevents client retries or duplicate network requests from creating duplicate booking rows.
ALTER TABLE bookings
ADD CONSTRAINT unique_idempotency_key UNIQUE (idempotency_key);

-- 2. Exact-Slot Uniqueness for Confirmed Bookings:
-- Partial unique index ensuring a facility and exact slot start time cannot have more than one confirmed booking.
CREATE UNIQUE INDEX idx_unique_confirmed_facility_slot
ON bookings (facility_id, slot_start)
WHERE status = 'confirmed';

-- 3. Overlapping Time-Range Protection for Confirmed Bookings (GiST Exclusion Constraint):
-- Uses btree_gist extension to reject overlapping time ranges for confirmed bookings on the same facility.
-- The predicate `WHERE (status = 'confirmed')` ensures cancelled or no-show bookings release their time range.
ALTER TABLE bookings
ADD CONSTRAINT exclude_overlapping_confirmed_bookings
EXCLUDE USING gist (
    facility_id WITH =,
    tstzrange(slot_start, slot_end) WITH &&
)
WHERE (status = 'confirmed');
