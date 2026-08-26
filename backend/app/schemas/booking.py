from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class CreateBookingRequest(BaseModel):
    facility_id: UUID
    slot_start: datetime
    slot_end: datetime
    idempotency_key: UUID

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "facility_id": "11111111-1111-1111-1111-111111111111",
                "slot_start": "2026-09-01T10:00:00Z",
                "slot_end": "2026-09-01T11:00:00Z",
                "idempotency_key": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
            }
        }
    )


class BookingModel(BaseModel):
    id: UUID
    facility_id: UUID
    slot_start: datetime
    slot_end: datetime
    user_id: UUID
    status: str
    idempotency_key: UUID
    created_at: datetime


class BookingResponse(BaseModel):
    ok: bool
    reason: str
    booking_id: Optional[UUID] = None
    booking: Optional[BookingModel] = None
