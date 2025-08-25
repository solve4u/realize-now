from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime, time
from uuid import UUID
from enum import Enum

class LocationBase(BaseModel):
    name: str = Field(..., max_length=255)
    timezone: str = Field(..., max_length=50)
    weekly_open_hours: Optional[float] = Field(default=0.0, ge=0)
    monday_open: Optional[time] = None
    monday_close: Optional[time] = None
    tuesday_open: Optional[time] = None
    tuesday_close: Optional[time] = None
    wednesday_open: Optional[time] = None
    wednesday_close: Optional[time] = None
    thursday_open: Optional[time] = None
    thursday_close: Optional[time] = None
    friday_open: Optional[time] = None
    friday_close: Optional[time] = None
    saturday_open: Optional[time] = None
    saturday_close: Optional[time] = None
    sunday_open: Optional[time] = None
    sunday_close: Optional[time] = None

class LocationCreateUpdate(BaseModel):
    name: str = Field(..., max_length=255)
    timezone: str = Field(..., max_length=50)
    monday_open: Optional[time] = None
    monday_close: Optional[time] = None
    tuesday_open: Optional[time] = None
    tuesday_close: Optional[time] = None
    wednesday_open: Optional[time] = None
    wednesday_close: Optional[time] = None
    thursday_open: Optional[time] = None
    thursday_close: Optional[time] = None
    friday_open: Optional[time] = None
    friday_close: Optional[time] = None
    saturday_open: Optional[time] = None
    saturday_close: Optional[time] = None
    sunday_open: Optional[time] = None
    sunday_close: Optional[time] = None

class LocationCreate(LocationCreateUpdate):
    organization_id: UUID

class LocationResponse(LocationBase):
    location_id: UUID
    organization_id: UUID
    remaining_hours_this_week: Optional[float] = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class LocationTimingsUpdate(BaseModel):
    """Model for updating only location timings and timezone."""
    timezone: Optional[str] = Field(None, max_length=50)
    monday_open: Optional[time] = None
    monday_close: Optional[time] = None
    tuesday_open: Optional[time] = None
    tuesday_close: Optional[time] = None
    wednesday_open: Optional[time] = None
    wednesday_close: Optional[time] = None
    thursday_open: Optional[time] = None
    thursday_close: Optional[time] = None
    friday_open: Optional[time] = None
    friday_close: Optional[time] = None
    saturday_open: Optional[time] = None
    saturday_close: Optional[time] = None
    sunday_open: Optional[time] = None
    sunday_close: Optional[time] = None

class LocationWithStats(LocationResponse):
    """Location with additional statistics."""
    total_patients: Optional[int] = 0
    assigned_patients: Optional[int] = 0
    pending_patients: Optional[int] = 0
    weekly_hours_remaining: Optional[float] = 0  # From get_remaining_hours_this_week function