-- Lockin Phase 5.3: Group & Team Booking Migration

-- 1. Alter booking_members to support group booking state
ALTER TABLE booking_members
ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'invited';

ALTER TABLE booking_members
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- Index for user invitation lookups
CREATE INDEX IF NOT EXISTS idx_booking_members_user_status
ON booking_members (user_id, status);
-------------------------------------------------------------------
-- 2. ADD BOOKING MEMBERS RPC (Row-locked for capacity safety)
-------------------------------------------------------------------
CREATE OR REPLACE FUNCTION add_booking_members(
    p_booking_id UUID,
    p_host_id UUID,
    p_member_user_ids UUID[]
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_booking RECORD;
    v_facility RECORD;
    v_current_count INTEGER;
    v_max_size INTEGER := 10;
    v_uid UUID;
    v_added_count INTEGER := 0;
BEGIN
    -- Verify booking exists and host owns it (FOR UPDATE locks booking for capacity calculation)
    SELECT id, facility_id, user_id, status
    INTO v_booking
    FROM bookings
    WHERE id = p_booking_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'booking_not_found');
    END IF;

    IF v_booking.user_id != p_host_id THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'unauthorized');
    END IF;

    IF v_booking.status NOT IN ('confirmed', 'checked_in') THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'booking_not_active');
    END IF;

    -- Fetch facility max group size from priority_policy if present
    SELECT priority_policy INTO v_facility FROM facilities WHERE id = v_booking.facility_id;
    IF v_facility.priority_policy ? 'max_group_size' THEN
        v_max_size := (v_facility.priority_policy->>'max_group_size')::integer;
    END IF;

    -- Count current active members
    SELECT COUNT(*) INTO v_current_count FROM booking_members WHERE booking_id = p_booking_id AND status != 'declined';

    IF v_current_count + array_length(p_member_user_ids, 1) > v_max_size THEN
        RETURN jsonb_build_object(
            'ok', false,
            'reason', 'group_size_exceeded',
            'max_allowed', v_max_size,
            'current_count', v_current_count
        );
    END IF;

    -- Add members
    FOREACH v_uid IN ARRAY p_member_user_ids
    LOOP
        IF v_uid != p_host_id THEN
            BEGIN
                INSERT INTO booking_members (booking_id, user_id, status)
                VALUES (p_booking_id, v_uid, 'invited');
                v_added_count := v_added_count + 1;
            EXCEPTION
                WHEN unique_violation THEN
                    -- Skip if already invited/confirmed
                    NULL;
            END;
        END IF;
    END LOOP;

    RETURN jsonb_build_object(
        'ok', true,
        'reason', 'members_added',
        'added_count', v_added_count,
        'booking_id', p_booking_id
    );
END;
$$;


-------------------------------------------------------------------
-- 3. RESPOND TO INVITATION RPC
-------------------------------------------------------------------
CREATE OR REPLACE FUNCTION respond_booking_invitation(
    p_member_id UUID,
    p_user_id UUID,
    p_response TEXT -- 'confirmed' or 'declined'
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_member RECORD;
    v_booking RECORD;
BEGIN
    IF p_response NOT IN ('confirmed', 'declined') THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'invalid_response');
    END IF;

    SELECT id, booking_id, user_id, status
    INTO v_member
    FROM booking_members
    WHERE id = p_member_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'invitation_not_found');
    END IF;

    IF v_member.user_id != p_user_id THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'unauthorized');
    END IF;

    -- Verify booking is still active
    SELECT status INTO v_booking FROM bookings WHERE id = v_member.booking_id;
    IF v_booking.status NOT IN ('confirmed', 'checked_in') THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'booking_not_active');
    END IF;

    UPDATE booking_members
    SET status = p_response,
        updated_at = now()
    WHERE id = p_member_id;

    RETURN jsonb_build_object(
        'ok', true,
        'reason', 'invitation_updated',
        'member_id', p_member_id,
        'status', p_response
    );
END;
$$;
