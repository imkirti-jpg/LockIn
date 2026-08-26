from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel


class JoinWaitlistRequest(BaseModel):
    slot_start: datetime
    slot_end: datetime


class ClaimWaitlistRequest(BaseModel):
    idempotency_key: UUID


class WaitlistEntryModel(BaseModel):
    id: UUID
    facility_id: UUID
    slot_start: datetime
    slot_end: datetime
    user_id: UUID
    position: int
    status: str
    claim_started_at: Optional[datetime] = None
    claim_expires_at: Optional[datetime] = None
    created_at: datetime
