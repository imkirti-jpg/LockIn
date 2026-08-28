-- ====================================================================
-- LOCKIN PHASE 1 CONSTRAINTS VERIFICATION SCRIPT
-- Tested & Executable in Supabase SQL Editor
--
-- This script runs inside a transaction block (BEGIN ... ROLLBACK) to 
-- verify all database correctness guarantees without polluting data:
--   Test A — Exact-slot collision rejection
--   Test B — Overlapping time-range rejection (GiST Exclusion)
--   Test C — Cancellation releases slot for new confirmed booking
--   Test D — Idempotency key uniqueness rejection
-- ====================================================================

BEGIN;

DO $$
DECLARE
    -- Dedicated Test Facility ID (Will be rolled back automatically)
    v_facility_id UUID := '99999999-9999-9999-9999-999999999999';
    
    -- Test User UUIDs
    v_user_1 UUID := 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11';
    v_user_2 UUID := 'b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a22';
    v_user_3 UUID := 'c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a33';
    
    -- Unique Idempotency Keys
    v_idempotency_1 UUID := gen_random_uuid();
    v_idempotency_2 UUID := gen_random_uuid();
    v_idempotency_3 UUID := gen_random_uuid();

    -- Time Slots for Testing
    v_slot_1_start TIMESTAMPTZ := '2026-09-01 10:00:00+00';
    v_slot_1_end   TIMESTAMPTZ := '2026-09-01 11:00:00+00';

    v_slot_overlap_start TIMESTAMPTZ := '2026-09-01 10:30:00+00';
    v_slot_overlap_end   TIMESTAMPTZ := '2026-09-01 11:30:00+00';

    v_booking_1_id UUID;
    v_booking_3_id UUID;
BEGIN
    RAISE NOTICE '=======================================================';
    RAISE NOTICE '   LOCKIN PHASE 1 CONSTRAINTS VERIFICATION STARTING    ';
    RAISE NOTICE '=======================================================';

    -- 0. Insert isolated test facility
    INSERT INTO facilities (id, name, sport_type, slot_length_minutes, status)
    VALUES (v_facility_id, 'Test Facility (Temporary)', 'Testing', 60, 'open')
    ON CONFLICT (id) DO NOTHING;


    -------------------------------------------------------------------
    -- TEST A: EXACT-SLOT COLLISION REJECTION
    -------------------------------------------------------------------
    RAISE NOTICE '[TEST A] Testing exact-slot confirmed collision...';
    
    -- Insert Booking 1 (User 1, 10:00 -> 11:00, confirmed)
    INSERT INTO bookings (facility_id, slot_start, slot_end, user_id, status, idempotency_key)
    VALUES (v_facility_id, v_slot_1_start, v_slot_1_end, v_user_1, 'confirmed', v_idempotency_1)
    RETURNING id INTO v_booking_1_id;

    RAISE NOTICE ' -> Booking 1 created (ID: %).', v_booking_1_id;

    -- Attempt Duplicate Booking 2 (User 2, exact same slot 10:00 -> 11:00, confirmed)
    BEGIN
        INSERT INTO bookings (facility_id, slot_start, slot_end, user_id, status, idempotency_key)
        VALUES (v_facility_id, v_slot_1_start, v_slot_1_end, v_user_2, 'confirmed', v_idempotency_2);
        
        RAISE EXCEPTION '[FAIL] Exact-slot duplicate booking was NOT rejected!';
    EXCEPTION
        WHEN unique_violation OR exclusion_violation THEN
            RAISE NOTICE ' -> SUCCESS: Second exact-slot confirmed booking was correctly REJECTED by Postgres.';
    END;


    -------------------------------------------------------------------
    -- TEST B: OVERLAPPING RANGE PROTECTION (GiST EXCLUSION)
    -------------------------------------------------------------------
    RAISE NOTICE '[TEST B] Testing overlapping range (10:30 -> 11:30 vs 10:00 -> 11:00)...';
    
    BEGIN
        INSERT INTO bookings (facility_id, slot_start, slot_end, user_id, status, idempotency_key)
        VALUES (v_facility_id, v_slot_overlap_start, v_slot_overlap_end, v_user_2, 'confirmed', v_idempotency_2);

        RAISE EXCEPTION '[FAIL] Overlapping booking range was NOT rejected!';
    EXCEPTION
        WHEN exclusion_violation THEN
            RAISE NOTICE ' -> SUCCESS: Overlapping booking range was correctly REJECTED by GiST constraint.';
    END;


    -------------------------------------------------------------------
    -- TEST C: CANCELLATION FREES SLOT FOR NEW CONFIRMED BOOKING
    -------------------------------------------------------------------
    RAISE NOTICE '[TEST C] Testing slot release upon cancellation...';

    -- Cancel Booking 1
    UPDATE bookings SET status = 'cancelled' WHERE id = v_booking_1_id;
    RAISE NOTICE ' -> Booking 1 marked as cancelled.';

    -- Attempt New Confirmed Booking (User 3, 10:00 -> 11:00)
    INSERT INTO bookings (facility_id, slot_start, slot_end, user_id, status, idempotency_key)
    VALUES (v_facility_id, v_slot_1_start, v_slot_1_end, v_user_3, 'confirmed', v_idempotency_3)
    RETURNING id INTO v_booking_3_id;

    RAISE NOTICE ' -> SUCCESS: New confirmed booking created after cancellation (ID: %).', v_booking_3_id;


    -------------------------------------------------------------------
    -- TEST D: IDEMPOTENCY KEY UNIQUENESS
    -------------------------------------------------------------------
    RAISE NOTICE '[TEST D] Testing duplicate idempotency_key rejection...';

    BEGIN
        -- Attempt booking with duplicate idempotency_key (v_idempotency_3 already used in Test C)
        INSERT INTO bookings (facility_id, slot_start, slot_end, user_id, status, idempotency_key)
        VALUES (v_facility_id, '2026-09-01 14:00:00+00', '2026-09-01 15:00:00+00', v_user_1, 'confirmed', v_idempotency_3);

        RAISE EXCEPTION '[FAIL] Duplicate idempotency key was NOT rejected!';
    EXCEPTION
        WHEN unique_violation THEN
            RAISE NOTICE ' -> SUCCESS: Duplicate idempotency key was correctly REJECTED.';
    END;

    RAISE NOTICE '=======================================================';
    RAISE NOTICE '   ALL 4 DATABASE CONSTRAINTS VERIFIED SUCCESSFULLY!   ';
    RAISE NOTICE '=======================================================';
END $$;

-- Rollback transaction so no test records remain in the database
ROLLBACK;
