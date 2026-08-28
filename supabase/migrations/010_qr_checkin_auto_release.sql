-- Lockin Phase 5.2: QR Check-in & Auto-release Migration

-- 1. Alter bookings table to support check-in tokens and attendance state
ALTER TABLE bookings
ADD COLUMN IF NOT EXISTS checkin_token UUID DEFAULT gen_random_uuid(),
ADD COLUMN IF NOT EXISTS checked_in_at TIMESTAMPTZ;

-- 2. Indexes for security token lookup and scheduler scan
CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_checkin_token
ON bookings (checkin_token)
WHERE checkin_token IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_bookings_no_show_scan
ON bookings (status, slot_start)
WHERE status = 'confirmed';


-------------------------------------------------------------------
-- 3. CHECK-IN BOOKING RPC
-------------------------------------------------------------------
CREATE OR REPLACE FUNCTION check_in_booking(
    p_booking_id UUID,
    p_user_id UUID,
    p_checkin_token UUID,
    p_grace_minutes INTEGER DEFAULT 15,
    p_early_minutes INTEGER DEFAULT 15
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_booking RECORD;
    v_now TIMESTAMPTZ := now();
    v_window_start TIMESTAMPTZ;
    v_window_end TIMESTAMPTZ;
BEGIN
    -- Fetch & lock booking row
    SELECT id, facility_id, slot_start, slot_end, user_id, status, checkin_token, checked_in_at
    INTO v_booking
    FROM bookings
    WHERE id = p_booking_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'booking_not_found');
    END IF;

    -- Authorization check: owner or authorized scanner
    IF p_user_id IS NOT NULL AND v_booking.user_id != p_user_id THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'unauthorized');
    END IF;

    -- Check-in token validation
    IF v_booking.checkin_token != p_checkin_token THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'invalid_token');
    END IF;

    -- Idempotency check
    IF v_booking.status = 'checked_in' THEN
        RETURN jsonb_build_object(
            'ok', true,
            'reason', 'already_checked_in',
            'booking_id', v_booking.id,
            'checked_in_at', v_booking.checked_in_at
        );
    END IF;

    IF v_booking.status != 'confirmed' THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'booking_not_confirmed', 'status', v_booking.status);
    END IF;

    -- Window check: slot_start - early_minutes <= now <= slot_start + grace_minutes
    v_window_start := v_booking.slot_start - (p_early_minutes || ' minutes')::interval;
    v_window_end := v_booking.slot_start + (p_grace_minutes || ' minutes')::interval;

    IF v_now < v_window_start THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'too_early', 'window_start', v_window_start);
    END IF;

    IF v_now > v_window_end THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'checkin_window_expired', 'window_end', v_window_end);
    END IF;

    -- Execute check-in transition
    UPDATE bookings
    SET status = 'checked_in',
        checked_in_at = v_now,
        updated_at = v_now
    WHERE id = p_booking_id;

    RETURN jsonb_build_object(
        'ok', true,
        'reason', 'checked_in',
        'booking_id', p_booking_id,
        'checked_in_at', v_now
    );
END;
$$;


-------------------------------------------------------------------
-- 4. AUTO-RELEASE NO-SHOWS RPC
-------------------------------------------------------------------
CREATE OR REPLACE FUNCTION auto_release_no_shows(
    p_grace_minutes INTEGER DEFAULT 15
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_rec RECORD;
    v_released_count INTEGER := 0;
    v_now TIMESTAMPTZ := now();
    v_cutoff TIMESTAMPTZ;
BEGIN
    v_cutoff := v_now - (p_grace_minutes || ' minutes')::interval;

    FOR v_rec IN
        SELECT id, facility_id, slot_start, user_id
        FROM bookings
        WHERE status = 'confirmed'
          AND slot_start <= v_cutoff
        FOR UPDATE SKIP LOCKED
    LOOP
        -- Transition to no_show
        UPDATE bookings
        SET status = 'no_show',
            updated_at = v_now
        WHERE id = v_rec.id;

        v_released_count := v_released_count + 1;

        -- Reuse Phase 5.1 waitlist promotion logic for freed slot
        PERFORM promote_waitlist_on_cancel(v_rec.facility_id, v_rec.slot_start);
    END LOOP;

    RETURN jsonb_build_object(
        'ok', true,
        'released_count', v_released_count
    );
END;
$$;
