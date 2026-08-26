-- Lockin Indexes & Row-Level Security Policies

---------------------------------------------------------
-- INDEXES FOR READ OPTIMIZATION & CONCURRENCY
---------------------------------------------------------

-- Facilities lookup index
CREATE INDEX IF NOT EXISTS idx_facilities_status ON facilities(status);

-- Bookings indexes for facility queries, date range lookups, and user histories
CREATE INDEX IF NOT EXISTS idx_bookings_facility ON bookings(facility_id);
CREATE INDEX IF NOT EXISTS idx_bookings_facility_time ON bookings(facility_id, slot_start, slot_end);
CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id);

-- Time slots query performance
CREATE INDEX IF NOT EXISTS idx_time_slots_facility_start ON time_slots(facility_id, start_time);

-- Waitlist queue position & claim expiration lookups
CREATE INDEX IF NOT EXISTS idx_waitlist_facility_slot ON waitlist_entries(facility_id, slot_start, position);
CREATE INDEX IF NOT EXISTS idx_waitlist_claim_expiry ON waitlist_entries(claim_expires_at) WHERE claim_expires_at IS NOT NULL;

-- Penalties active strikes lookup
CREATE INDEX IF NOT EXISTS idx_penalties_user_expiry ON penalties(user_id, expires_at);

-- User notifications inbox sorted by recency
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, created_at DESC);


---------------------------------------------------------
-- ROW-LEVEL SECURITY (RLS) POLICIES
---------------------------------------------------------

-- 1. Enable RLS on all tables
ALTER TABLE facilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE time_slots ENABLE ROW LEVEL SECURITY;
ALTER TABLE bookings ENABLE ROW LEVEL SECURITY;
ALTER TABLE booking_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE waitlist_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE penalties ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;


-- 2. Facilities Policies (Public read, admin write via service role)
CREATE POLICY "Facilities are viewable by everyone"
ON facilities FOR SELECT
TO authenticated, anon
USING (true);


-- 3. Time Slots Policies (Public read)
CREATE POLICY "Time slots are viewable by everyone"
ON time_slots FOR SELECT
TO authenticated, anon
USING (true);


-- 4. Bookings Policies (Scoped to booking owner & participants)
CREATE POLICY "Users can view their own bookings"
ON bookings FOR SELECT
TO authenticated
USING (auth.uid() = user_id);

CREATE POLICY "Users can create their own bookings"
ON bookings FOR INSERT
TO authenticated
WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own bookings"
ON bookings FOR UPDATE
TO authenticated
USING (auth.uid() = user_id)
WITH CHECK (auth.uid() = user_id);


-- 5. Booking Members Policies
CREATE POLICY "Members viewable by booking participants"
ON booking_members FOR SELECT
TO authenticated
USING (
    auth.uid() = user_id OR
    EXISTS (
        SELECT 1 FROM bookings b
        WHERE b.id = booking_members.booking_id AND b.user_id = auth.uid()
    )
);

CREATE POLICY "Users can add members to their bookings"
ON booking_members FOR INSERT
TO authenticated
WITH CHECK (
    EXISTS (
        SELECT 1 FROM bookings b
        WHERE b.id = booking_members.booking_id AND b.user_id = auth.uid()
    )
);


-- 6. Waitlist Entries Policies
CREATE POLICY "Users can view waitlist entries"
ON waitlist_entries FOR SELECT
TO authenticated
USING (auth.uid() = user_id);

CREATE POLICY "Users can join waitlist"
ON waitlist_entries FOR INSERT
TO authenticated
WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can cancel waitlist entry"
ON waitlist_entries FOR DELETE
TO authenticated
USING (auth.uid() = user_id);


-- 7. Penalties Policies
CREATE POLICY "Users can view their own penalties"
ON penalties FOR SELECT
TO authenticated
USING (auth.uid() = user_id);


-- 8. Notifications Policies
CREATE POLICY "Users can view their own notifications"
ON notifications FOR SELECT
TO authenticated
USING (auth.uid() = user_id);
