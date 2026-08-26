-- Lockin Seed Data Migration (IIT Guwahati Sports Facilities)

INSERT INTO facilities (id, name, sport_type, slot_length_minutes, priority_policy, status)
VALUES
    (
        '11111111-1111-1111-1111-111111111111',
        'IITG Gymnasium',
        'Gymnastics & Fitness',
        60,
        '{"max_active_bookings_per_user": 2, "team_early_access_hours": 0}'::jsonb,
        'open'
    ),
    (
        '22222222-2222-2222-2222-222222222222',
        'Tennis Court 1',
        'Tennis',
        60,
        '{"max_active_bookings_per_user": 1, "team_early_access_hours": 12}'::jsonb,
        'open'
    ),
    (
        '33333333-3333-3333-3333-333333333333',
        'Badminton Court A',
        'Badminton',
        45,
        '{"max_active_bookings_per_user": 1, "team_early_access_hours": 24}'::jsonb,
        'open'
    ),
    (
        '44444444-4444-4444-4444-444444444444',
        'Football Field',
        'Football',
        90,
        '{"max_active_bookings_per_user": 1, "team_early_access_hours": 48}'::jsonb,
        'open'
    ),
    (
        '55555555-5555-5555-5555-555555555555',
        'Cricket Ground',
        'Cricket',
        120,
        '{"max_active_bookings_per_user": 1, "team_early_access_hours": 48}'::jsonb,
        'maintenance'
    )
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    sport_type = EXCLUDED.sport_type,
    slot_length_minutes = EXCLUDED.slot_length_minutes,
    priority_policy = EXCLUDED.priority_policy,
    status = EXCLUDED.status;
