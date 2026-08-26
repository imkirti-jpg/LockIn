-- Lockin Phase 2: Atomic Transactional Booking RPC

CREATE OR REPLACE FUNCTION book_slot(
    p_facility_id UUID,
    p_slot_start TIMESTAMPTZ,
    p_slot_end TIMESTAMPTZ,
    p_user_id UUID,
    p_idempotency_key UUID
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_facility_status TEXT;
    v_existing_booking RECORD;
    v_new_booking RECORD;
BEGIN
    -- 1. Input Time Validation
    IF p_slot_end <= p_slot_start THEN
        RETURN jsonb_build_object(
            'ok', false,
            'reason', 'invalid_time_range',
            'booking_id', NULL,
            'booking', NULL
        );
    END IF;

    -- 2. Validate Facility Existence and Status
    SELECT status INTO v_facility_status
    FROM facilities
    WHERE id = p_facility_id;

    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'ok', false,
            'reason', 'facility_not_found',
            'booking_id', NULL,
            'booking', NULL
        );
    END IF;

    IF v_facility_status != 'open' THEN
        RETURN jsonb_build_object(
            'ok', false,
            'reason', 'facility_not_open',
            'booking_id', NULL,
            'booking', NULL
        );
    END IF;

    -- 3. Check Idempotency Key Replay vs Reuse
    SELECT id, facility_id, slot_start, slot_end, user_id, status, idempotency_key, created_at
    INTO v_existing_booking
    FROM bookings
    WHERE idempotency_key = p_idempotency_key;

    IF FOUND THEN
        -- Exact match of parameters: return idempotent replay
        IF v_existing_booking.facility_id = p_facility_id
           AND v_existing_booking.slot_start = p_slot_start
           AND v_existing_booking.slot_end = p_slot_end
           AND v_existing_booking.user_id = p_user_id THEN
            RETURN jsonb_build_object(
                'ok', true,
                'reason', 'idempotent_replay',
                'booking_id', v_existing_booking.id,
                'booking', jsonb_build_object(
                    'id', v_existing_booking.id,
                    'facility_id', v_existing_booking.facility_id,
                    'slot_start', v_existing_booking.slot_start,
                    'slot_end', v_existing_booking.slot_end,
                    'user_id', v_existing_booking.user_id,
                    'status', v_existing_booking.status,
                    'idempotency_key', v_existing_booking.idempotency_key,
                    'created_at', v_existing_booking.created_at
                )
            );
        ELSE
            -- Same idempotency key used for a different booking request: reject
            RETURN jsonb_build_object(
                'ok', false,
                'reason', 'idempotency_key_reused',
                'booking_id', NULL,
                'booking', NULL
            );
        END IF;
    END IF;

    -- 4. Serialize Facility Attempts & Insert Booking under Constraints
    -- Row-level lock on facility row to serialize competing attempts
    PERFORM 1 FROM facilities WHERE id = p_facility_id FOR UPDATE;

    BEGIN
        INSERT INTO bookings (
            facility_id,
            slot_start,
            slot_end,
            user_id,
            status,
            idempotency_key
        )
        VALUES (
            p_facility_id,
            p_slot_start,
            p_slot_end,
            p_user_id,
            'confirmed',
            p_idempotency_key
        )
        RETURNING id, facility_id, slot_start, slot_end, user_id, status, idempotency_key, created_at
        INTO v_new_booking;

        RETURN jsonb_build_object(
            'ok', true,
            'reason', 'confirmed',
            'booking_id', v_new_booking.id,
            'booking', jsonb_build_object(
                'id', v_new_booking.id,
                'facility_id', v_new_booking.facility_id,
                'slot_start', v_new_booking.slot_start,
                'slot_end', v_new_booking.slot_end,
                'user_id', v_new_booking.user_id,
                'status', v_new_booking.status,
                'idempotency_key', v_new_booking.idempotency_key,
                'created_at', v_new_booking.created_at
            )
        );
    EXCEPTION
        WHEN unique_violation THEN
            -- Handle potential race condition on idempotency key or exact-slot index
            IF EXISTS (SELECT 1 FROM bookings WHERE idempotency_key = p_idempotency_key) THEN
                RETURN jsonb_build_object(
                    'ok', false,
                    'reason', 'idempotency_key_reused',
                    'booking_id', NULL,
                    'booking', NULL
                );
            ELSE
                RETURN jsonb_build_object(
                    'ok', false,
                    'reason', 'slot_taken',
                    'booking_id', NULL,
                    'booking', NULL
                );
            END IF;
        WHEN exclusion_violation THEN
            RETURN jsonb_build_object(
                'ok', false,
                'reason', 'slot_taken',
                'booking_id', NULL,
                'booking', NULL
            );
    END;
END;
$$;
