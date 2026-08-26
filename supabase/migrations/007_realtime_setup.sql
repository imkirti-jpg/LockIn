-- Lockin Phase 4: Supabase Realtime Publication Setup

-- Add bookings table to supabase_realtime publication for Logical Replication CDC events
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime') THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE bookings;
    END IF;
END $$;
