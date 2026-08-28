# Supabase Migration & Verification Guide for Lockin

This folder contains the complete SQL migrations and database correctness verification scripts for **Lockin**.

---

## 📜 Migration Order

Apply the SQL migration files in `supabase/migrations/` sequentially in the Supabase SQL Editor or via Supabase CLI:

1. **`001_extensions.sql`**: Enables `btree_gist` and `uuid-ossp` extensions.
2. **`002_core_tables.sql`**: Scaffolds 7 core PostgreSQL tables (`facilities`, `time_slots`, `bookings`, `booking_members`, `waitlist_entries`, `penalties`, `notifications`).
3. **`003_booking_constraints.sql`**: Applies idempotency key uniqueness, partial unique index for exact-slot confirmed bookings, and GiST exclusion constraint for overlapping time ranges.
4. **`004_indexes_and_rls.sql`**: Applies performance indexes and least-privilege Row-Level Security policies.
5. **`005_seed_data.sql`**: Seeds 5 realistic IIT Guwahati sports facilities.

---

## 🧪 Phase 1 Real Database Verification Instructions

To execute and verify the database correctness guarantees against your real Supabase PostgreSQL database:

### Steps to Run Verification:

1. Open your [Supabase Dashboard](https://supabase.com/dashboard).
2. Select your project (**yuwawjbqwpsxutxvovai**).
3. Navigate to **SQL Editor** in the left sidebar.
4. Click **New query** and copy-paste the entire contents of [`supabase/verify_constraints.sql`](file:///c:/Users/kirti/OneDrive/Documents/LockIn/supabase/verify_constraints.sql).
5. Click **Run** (or press `Ctrl+Enter`).

---

### Expected Output & Success Indicators:

In the SQL Editor **Notices** / **Messages** tab, you will see output confirming each test pass:

```
=======================================================
   LOCKIN PHASE 1 CONSTRAINTS VERIFICATION STARTING    
=======================================================
[TEST A] Testing exact-slot confirmed collision...
 -> Booking 1 created (ID: ...).
 -> SUCCESS: Second exact-slot confirmed booking was correctly REJECTED by Postgres.
[TEST B] Testing overlapping range (10:30 -> 11:30 vs 10:00 -> 11:00)...
 -> SUCCESS: Overlapping booking range was correctly REJECTED by GiST constraint.
[TEST C] Testing slot release upon cancellation...
 -> Booking 1 marked as cancelled.
 -> SUCCESS: New confirmed booking created after cancellation (ID: ...).
[TEST D] Testing duplicate idempotency_key rejection...
 -> SUCCESS: Duplicate idempotency key was correctly REJECTED.
=======================================================
   ALL 4 DATABASE CONSTRAINTS VERIFIED SUCCESSFULLY!   
=======================================================
```

---

### Cleanup Behavior & Safety:

- The script executes inside an explicit `BEGIN; ... ROLLBACK;` transaction block.
- **Zero Cleanup Required**: The transaction automatically rolls back upon completion, leaving **no test facilities or test bookings** in your real database.
- If any constraint fails, PostgreSQL raises an explicit `[FAIL]` exception and halts execution.
