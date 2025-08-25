from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from uuid import UUID
from enum import Enum

class ServiceType(str, Enum):
    SESSION = "session"
    EVALUATION = "evaluation"

class ImportStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    ERROR = "error"
    SKIPPED = "skipped"

class SFTPRawDataResponse(BaseModel):
    record_id: UUID
    service_type: ServiceType
    organization_id: UUID
    location_id: UUID
    file_name: Optional[str] = None
    imported_at: datetime
    processed_at: Optional[datetime] = None
    status: ImportStatus
    error_message: Optional[str] = None
    
    # Patient Data
    location: Optional[str] = None  
    full_name: Optional[str] = None
    mr: Optional[str] = None
    admission_date: Optional[date] = None
    discharge_date: Optional[date] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    primary_therapist: Optional[str] = None
    current_ur_loc: Optional[str] = None
    program: Optional[str] = None
    
    # Service Data
    session_name: Optional[str] = None
    service_description: Optional[str] = None
    provider: Optional[str] = None
    signed_by: Optional[str] = None
    started: Optional[datetime] = None
    ended: Optional[datetime] = None
    duration: Optional[float] = None
    attended: Optional[int] = None
    absent: Optional[int] = None
    authorizations: Optional[str] = None
    activity_status: Optional[str] = None
    completed_at: Optional[datetime] = None
    session_id: Optional[str] = None
    session_url: Optional[str] = None
    external_id: Optional[str] = None
    template_id: Optional[str] = None
    
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ImportSummary(BaseModel):
    total_records: int
    pending: int
    processing: int
    processed: int
    error: int
    skipped: int
    latest_import: Optional[datetime] = None
    
class ImportStatsResponse(BaseModel):
    organization_id: Optional[UUID] = None
    organization_name: Optional[str] = None
    summary: ImportSummary
    recent_files: List[str]
    
class DataImportOverview(BaseModel):
    organization_id: UUID
    organization_name: str
    location_id: UUID
    location_name: str
    total_records: int
    status_breakdown: dict  # {status: count}
    recent_files: List[str]
    latest_import: Optional[datetime] = None
    processing_errors: List[dict]  