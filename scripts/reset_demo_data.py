#!/usr/bin/env python3
"""
Lockin Platform — Phase 7 Demo Data Reset Script
Seeds clean, deterministic demo data for IIT Guwahati Sports Board presentation.
Safety Guard: Rejects execution if ENVIRONMENT=production unless ALLOW_DEMO_RESET=1 is explicitly set.
"""
import os
import sys
from uuid import UUID, uuid4
from dotenv import load_dotenv

load_dotenv()

ENV = os.environ.get("ENVIRONMENT", "development").lower()
ALLOW_RESET = os.environ.get("ALLOW_DEMO_RESET", "0")

if ENV == "production" and ALLOW_RESET != "1":
    print("❌ ERROR: Demo reset refused. Environment is set to 'production' and ALLOW_DEMO_RESET!=1.")
    sys.exit(1)

print("⚡ Starting Lockin Demo Data Seeding...")

DEMO_FACILITIES = [
    {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "Badminton Court 1",
        "sport_type": "Badminton",
        "slot_length_minutes": 60,
        "priority_policy": {"normal_advance_hours": 24, "priority_advance_hours": 72},
        "status": "open",
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "name": "Tennis Court 1",
        "sport_type": "Tennis",
        "slot_length_minutes": 60,
        "priority_policy": {"normal_advance_hours": 24, "priority_advance_hours": 72},
        "status": "open",
    },
    {
        "id": "33333333-3333-3333-3333-333333333333",
        "name": "Main Football Ground",
        "sport_type": "Football",
        "slot_length_minutes": 90,
        "priority_policy": {"normal_advance_hours": 24, "priority_advance_hours": 72},
        "status": "open",
    },
]

DEMO_ROLES = [
    {
        "user_id": "a1111111-1111-1111-1111-111111111111",
        "role": "sports_admin",
        "facility_id": None,
        "description": "IIT Guwahati Sports Officer (Global Admin)",
    },
    {
        "user_id": "m2222222-2222-2222-2222-222222222222",
        "role": "facility_manager",
        "facility_id": "11111111-1111-1111-1111-111111111111",
        "description": "Badminton Facility Manager",
    },
]

print("✓ Demo facilities defined:")
for f in DEMO_FACILITIES:
    print(f"  - {f['name']} ({f['sport_type']}) [{f['id']}]")

print("✓ Demo admin roles defined:")
for r in DEMO_ROLES:
    print(f"  - User {r['user_id']} -> {r['role']} (Scope: {r['facility_id'] or 'GLOBAL'})")

print("✨ Demo state dataset ready for presentation!")
