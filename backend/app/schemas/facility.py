from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID
from pydantic import BaseModel


class FacilityModel(BaseModel):
    id: UUID
    name: str
    sport_type: str
    slot_length_minutes: int
    priority_policy: Dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime


class FacilityListResponse(BaseModel):
    ok: bool
    count: int
    facilities: list[FacilityModel]


class FacilityDetailResponse(BaseModel):
    ok: bool
    facility: FacilityModel
