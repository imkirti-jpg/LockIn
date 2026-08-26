-- Lockin Phase 6: Admin Ops Console & Analytics Migration

-- 1. Create user_roles table for secure role-based access control
CREATE TABLE IF NOT EXISTS user_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('student', 'facility_manager', 'sports_admin')),
    facility_id UUID REFERENCES facilities(id) ON DELETE CASCADE, -- NULL = global/all facilities
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_roles_lookup
ON user_roles (user_id, active);

-- 2. Create facility_blocks table for administrative maintenance & event holds
CREATE TABLE IF NOT EXISTS facility_blocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facility_id UUID NOT NULL REFERENCES facilities(id) ON DELETE CASCADE,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    reason TEXT NOT NULL,
    block_type TEXT NOT NULL DEFAULT 'maintenance' CHECK (block_type IN ('maintenance', 'event', 'admin_hold')),
    created_by UUID NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT valid_block_time_range CHECK (end_time > start_time)
);

CREATE INDEX IF NOT EXISTS idx_facility_blocks_active_time
ON facility_blocks (facility_id, active, start_time, end_time);


-------------------------------------------------------------------
-- 3. EXTEND book_slot RPC WITH AUTHORITATIVE FACILITY BLOCK CHECKS
-------------------------------------------------------------------
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
    v_facility RECORD;
    v_existing_booking RECORD;
    v_new_booking RECORD;
    v_now TIMESTAMPTZ := now();
    v_normal_advance_hours INTEGER := 24;
    v_priority_advance_hours INTEGER := 72;
    v_has_priority_eligibility BOOLEAN := false;
    v_normal_cutoff TIMESTAMPTZ;
    v_priority_cutoff TIMESTAMPTZ;
    v_policy JSONB;
    v_is_blocked BOOLEAN := false;
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

    IF p_slot_start <= v_now THEN
        RETURN jsonb_build_object(
            'ok', false,
            'reason', 'slot_in_past',
            'booking_id', NULL,
            'booking', NULL
        );
    END IF;

    -- 2. Validate Facility Existence and Status
    SELECT id, status, priority_policy
    INTO v_facility
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

    IF v_facility.status != 'open' THEN
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
            RETURN jsonb_build_object(
                'ok', false,
                'reason', 'idempotency_key_reused',
                'booking_id', NULL,
                'booking', NULL
            );
        END IF;
    END IF;

    -- 4. Authoritative Administrative Facility Block Check
    SELECT EXISTS (
        SELECT 1 FROM facility_blocks
        WHERE facility_id = p_facility_id
          AND active = true
          AND NOT (end_time <= p_slot_start OR start_time >= p_slot_end)
    ) INTO v_is_blocked;

    IF v_is_blocked THEN
        RETURN jsonb_build_object(
            'ok', false,
            'reason', 'facility_blocked',
            'booking_id', NULL,
            'booking', NULL
        );
    END IF;

    -- 5. Calculate Priority & Normal Booking Windows
    v_policy := v_facility.priority_policy;

    IF v_policy ? 'normal_advance_hours' THEN
        v_normal_advance_hours := (v_policy->>'normal_advance_hours')::integer;
    ELSE
        v_normal_advance_hours := 24;
    END IF;

    IF v_policy ? 'priority_advance_hours' THEN
        v_priority_advance_hours := (v_policy->>'priority_advance_hours')::integer;
    ELSIF v_policy ? 'team_early_access_hours' THEN
        v_priority_advance_hours := v_normal_advance_hours + (v_policy->>'team_early_access_hours')::integer;
    ELSE
        v_priority_advance_hours := 72;
    END IF;

    v_normal_cutoff := p_slot_start - (v_normal_advance_hours || ' hours')::interval;
    v_priority_cutoff := p_slot_start - (v_priority_advance_hours || ' hours')::interval;

    -- 6. Window Eligibility Checks
    IF v_now < v_priority_cutoff THEN
        RETURN jsonb_build_object(
            'ok', false,
            'reason', 'booking_window_not_open',
            'window_start', v_priority_cutoff
        );
    END IF;

    IF v_now < v_normal_cutoff THEN
        SELECT EXISTS (
            SELECT 1 FROM priority_eligibilities
            WHERE user_id = p_user_id
              AND active = true
              AND (facility_id IS NULL OR facility_id = p_facility_id)
              AND valid_from <= v_now
              AND (valid_until IS NULL OR valid_until >= v_now)
        ) INTO v_has_priority_eligibility;

        IF NOT v_has_priority_eligibility THEN
            RETURN jsonb_build_object(
                'ok', false,
                'reason', 'booking_window_not_open',
                'window_start', v_normal_cutoff
            );
        END IF;
    END IF;

    -- 7. Serialize Facility Attempts & Insert Booking under Constraints
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
