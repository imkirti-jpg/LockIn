from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel


class SlotModel(BaseModel):
    slot_id: str
    facility_id: UUID
    start_time: datetime
    end_time: datetime
    status: str  # "open", "full", "past", "maintenance"
    booking_id: Optional[UUID] = None


class FacilitySlotsResponse(BaseModel):
    ok: bool
    facility_id: UUID
    date: str
    slot_length_minutes: int
    slots: List[SlotModel]
