-- Lockin Phase 5.1: Waitlist & Claim Windows Migration

-- 1. Alter waitlist_entries table to support full lifecycle
ALTER TABLE waitlist_entries
ADD COLUMN IF NOT EXISTS slot_end TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'waiting' CHECK (status IN ('waiting', 'offered', 'claimed', 'expired', 'cancelled')),
ADD COLUMN IF NOT EXISTS claim_started_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- 2. Partial unique index for active waitlist entries
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_active_waitlist
ON waitlist_entries (facility_id, slot_start, user_id)
WHERE status IN ('waiting', 'offered');

-- 3. Index for queue performance & claim expiration scanning
CREATE INDEX IF NOT EXISTS idx_waitlist_queue ON waitlist_entries (facility_id, slot_start, status, created_at, id);
CREATE INDEX IF NOT EXISTS idx_waitlist_expired ON waitlist_entries (status, claim_expires_at) WHERE status = 'offered';


-------------------------------------------------------------------
-- 4. JOIN WAITLIST RPC
-------------------------------------------------------------------
CREATE OR REPLACE FUNCTION join_waitlist(
    p_facility_id UUID,
    p_slot_start TIMESTAMPTZ,
    p_slot_end TIMESTAMPTZ,
    p_user_id UUID
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_booking_count INTEGER;
    v_existing_entry RECORD;
    v_next_pos INTEGER;
    v_new_entry RECORD;
BEGIN
    -- A. Verify if slot is occupied by a confirmed booking
    SELECT COUNT(*) INTO v_booking_count
    FROM bookings
    WHERE facility_id = p_facility_id
      AND slot_start = p_slot_start
      AND status = 'confirmed';

    IF v_booking_count = 0 THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'slot_available');
    END IF;

    -- B. Check if user is already active on this waitlist
    SELECT id, facility_id, slot_start, slot_end, user_id, position, status, claim_expires_at, created_at
    INTO v_existing_entry
    FROM waitlist_entries
    WHERE facility_id = p_facility_id
      AND slot_start = p_slot_start
      AND user_id = p_user_id
      AND status IN ('waiting', 'offered');

    IF FOUND THEN
        RETURN jsonb_build_object(
            'ok', true,
            'reason', 'already_joined',
            'waitlist_entry', row_to_json(v_existing_entry)
        );
    END IF;

    -- C. Lock facility & calculate next queue position
    PERFORM 1 FROM facilities WHERE id = p_facility_id FOR UPDATE;

    SELECT COALESCE(MAX(position), 0) + 1 INTO v_next_pos
    FROM waitlist_entries
    WHERE facility_id = p_facility_id
      AND slot_start = p_slot_start
      AND status IN ('waiting', 'offered');

    -- D. Insert waitlist entry
    BEGIN
        INSERT INTO waitlist_entries (
            facility_id,
            slot_start,
            slot_end,
            user_id,
            position,
            status
        )
        VALUES (
            p_facility_id,
            p_slot_start,
            p_slot_end,
            p_user_id,
            v_next_pos,
            'waiting'
        )
        RETURNING id, facility_id, slot_start, slot_end, user_id, position, status, created_at
        INTO v_new_entry;

        RETURN jsonb_build_object(
            'ok', true,
            'reason', 'joined',
            'waitlist_entry', row_to_json(v_new_entry)
        );
    EXCEPTION
        WHEN unique_violation THEN
            SELECT id, facility_id, slot_start, slot_end, user_id, position, status, claim_expires_at, created_at
            INTO v_existing_entry
            FROM waitlist_entries
            WHERE facility_id = p_facility_id
              AND slot_start = p_slot_start
              AND user_id = p_user_id
              AND status IN ('waiting', 'offered');

            RETURN jsonb_build_object(
                'ok', true,
                'reason', 'already_joined',
                'waitlist_entry', row_to_json(v_existing_entry)
            );
    END;
END;
$$;


-------------------------------------------------------------------
-- 5. PROMOTE WAITLIST ON CANCELLATION RPC
-------------------------------------------------------------------
CREATE OR REPLACE FUNCTION promote_waitlist_on_cancel(
    p_facility_id UUID,
    p_slot_start TIMESTAMPTZ,
    p_claim_minutes INTEGER DEFAULT 10
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_candidate RECORD;
    v_offered_count INTEGER;
BEGIN
    -- Check if there is already an active offered claim for this slot
    SELECT COUNT(*) INTO v_offered_count
    FROM waitlist_entries
    WHERE facility_id = p_facility_id
      AND slot_start = p_slot_start
      AND status = 'offered';

    IF v_offered_count > 0 THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'already_offered');
    END IF;

    -- Select next eligible student using FOR UPDATE SKIP LOCKED for multi-process safety
    SELECT id, user_id, facility_id, slot_start, slot_end
    INTO v_candidate
    FROM waitlist_entries
    WHERE facility_id = p_facility_id
      AND slot_start = p_slot_start
      AND status = 'waiting'
    ORDER BY created_at ASC, id ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'no_waitlist_candidates');
    END IF;

    -- Promote to offered with claim window
    UPDATE waitlist_entries
    SET status = 'offered',
        claim_started_at = now(),
        claim_expires_at = now() + (p_claim_minutes || ' minutes')::interval,
        updated_at = now()
    WHERE id = v_candidate.id;

    RETURN jsonb_build_object(
        'ok', true,
        'reason', 'promoted',
        'entry_id', v_candidate.id,
        'user_id', v_candidate.user_id,
        'facility_id', v_candidate.facility_id,
        'slot_start', v_candidate.slot_start,
        'claim_expires_at', now() + (p_claim_minutes || ' minutes')::interval
    );
END;
$$;


-------------------------------------------------------------------
-- 6. CLAIM WAITLIST SLOT RPC
-------------------------------------------------------------------
CREATE OR REPLACE FUNCTION claim_waitlist_slot(
    p_entry_id UUID,
    p_user_id UUID,
    p_idempotency_key UUID
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_entry RECORD;
    v_book_res JSONB;
BEGIN
    -- A. Fetch & lock waitlist entry
    SELECT id, facility_id, slot_start, slot_end, user_id, status, claim_expires_at
    INTO v_entry
    FROM waitlist_entries
    WHERE id = p_entry_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'entry_not_found');
    END IF;

    IF v_entry.user_id != p_user_id THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'unauthorized');
    END IF;

    IF v_entry.status = 'claimed' THEN
        RETURN jsonb_build_object('ok', true, 'reason', 'already_claimed');
    END IF;

    IF v_entry.status != 'offered' THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'entry_not_offered');
    END IF;

    IF v_entry.claim_expires_at < now() THEN
        UPDATE waitlist_entries SET status = 'expired', updated_at = now() WHERE id = p_entry_id;
        RETURN jsonb_build_object('ok', false, 'reason', 'claim_expired');
    END IF;

    -- B. Atomically execute Phase 2 book_slot RPC
    v_book_res := book_slot(
        v_entry.facility_id,
        v_entry.slot_start,
        COALESCE(v_entry.slot_end, v_entry.slot_start + interval '1 hour'),
        p_user_id,
        p_idempotency_key
    );

    IF (v_book_res->>'ok')::boolean = true THEN
        -- Mark waitlist entry as claimed
        UPDATE waitlist_entries
        SET status = 'claimed',
            updated_at = now()
        WHERE id = p_entry_id;

        RETURN jsonb_build_object(
            'ok', true,
            'reason', 'claimed',
            'booking_id', v_book_res->>'booking_id',
            'booking', v_book_res->'booking'
        );
    ELSE
        RETURN jsonb_build_object(
            'ok', false,
            'reason', v_book_res->>'reason'
        );
    END IF;
END;
$$;


-------------------------------------------------------------------
-- 7. EXPIRE WAITLIST CLAIMS RPC
-------------------------------------------------------------------
CREATE OR REPLACE FUNCTION expire_waitlist_claims()
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_rec RECORD;
    v_count INTEGER := 0;
    v_promoted_res JSONB;
BEGIN
    FOR v_rec IN
        SELECT id, facility_id, slot_start
        FROM waitlist_entries
        WHERE status = 'offered'
          AND claim_expires_at < now()
        FOR UPDATE SKIP LOCKED
    LOOP
        UPDATE waitlist_entries
        SET status = 'expired', updated_at = now()
        WHERE id = v_rec.id;

        v_count := v_count + 1;

        -- Promote next student in queue for this slot
        PERFORM promote_waitlist_on_cancel(v_rec.facility_id, v_rec.slot_start);
    END LOOP;

    RETURN jsonb_build_object('ok', true, 'expired_count', v_count);
END;
$$;
