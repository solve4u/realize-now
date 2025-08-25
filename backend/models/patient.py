from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from uuid import UUID
from enum import Enum

class AssignmentStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"

class ComplianceStatus(str, Enum):
    COMPLIANT = "compliant"
    AT_RISK = "at_risk"
    NON_COMPLIANT = "non_compliant"
    UNASSIGNED = "unassigned"

# Program Models
class ProgramBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    level_of_care: Optional[str] = Field(None, max_length=100)
    hours_per_week: float = Field(..., ge=0, le=168)
    status: str = "active"

class ProgramCreate(ProgramBase):
    organization_id: UUID

class ProgramUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    level_of_care: Optional[str] = Field(None, max_length=100)
    hours_per_week: Optional[float] = Field(None, ge=0, le=168)
    status: Optional[str] = None

class ProgramResponse(ProgramBase):
    program_id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Risk Tier Models
class RiskTierBase(BaseModel):
    tier_label: str = Field(..., max_length=50)
    tier_description: str
    recommended_actions: str
    risk_level_range_low: float = Field(..., ge=0)
    risk_level_range_high: float = Field(..., ge=0)
    color: str = Field(..., max_length=50)
    sort_order: int = Field(default=0)
    auto_flag_for_followup: bool = Field(default=False)
    status: str = "active"

class RiskTierCreate(RiskTierBase):
    organization_id: UUID

class RiskTierResponse(RiskTierBase):
    tier_id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Patient Models
class PatientBase(BaseModel):
    mr: str = Field(..., max_length=100)
    full_name: str = Field(..., max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    primary_therapist: Optional[str] = Field(None, max_length=255)
    current_ur_loc: Optional[str] = Field(None, max_length=100)
    admission_date: Optional[date] = None
    discharge_date: Optional[date] = None
    program: Optional[str] = Field(None, max_length=100)  # Original SFTP program string
    status: str = "active"

class PatientCreate(PatientBase):
    organization_id: Optional[UUID] = None  # Optional for system admins
    location_id: Optional[UUID] = None
    program_id: Optional[UUID] = None

class PatientUpdate(BaseModel):
    mr: Optional[str] = Field(None, max_length=100)
    full_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    admission_date: Optional[date] = None
    discharge_date: Optional[date] = None
    program_id: Optional[UUID] = None
    location_id: Optional[UUID] = None
    status: Optional[str] = None

class PatientResponse(PatientBase):
    patient_id: UUID
    organization_id: UUID
    location_id: Optional[UUID] = None
    program_id: Optional[UUID] = None
    assignment_status: AssignmentStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class PatientAssignmentOverview(BaseModel):
    patient_id: UUID
    organization_id: UUID
    location_id: Optional[UUID] = None
    program_id: Optional[UUID] = None
    mr: str
    full_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    primary_therapist: Optional[str] = None
    admission_date: Optional[date] = None
    discharge_date: Optional[date] = None
    assignment_status: AssignmentStatus
    status: str
    
    # Age and basic info
    age: Optional[int] = None
    
    # Program and location info
    program_name: Optional[str] = None
    program_hours_per_week: Optional[float] = None
    location_name: Optional[str] = None
    level_of_care: Optional[str] = None
    
    # Current week engagement metrics
    current_week_start: Optional[datetime] = None
    current_week_end: Optional[datetime] = None
    sessions_completed_this_week: Optional[int] = None
    hours_completed: Optional[float] = None
    total_sessions_completed: Optional[int] = None
    total_hours_completed: Optional[float] = None
    hours_required: Optional[float] = None
    hours_remaining: Optional[float] = None
    completion_percentage: Optional[float] = None
    
    # Risk assessment
    risk_ratio: Optional[float] = None
    risk_level: Optional[str] = None
    tier_description: Optional[str] = None
    recommended_actions: Optional[str] = None
    color: Optional[str] = None
    auto_flag_for_followup: Optional[bool] = None
    engagement_status: Optional[str] = None
    engagement_category: Optional[str] = None
    risk_category: Optional[str] = None
    assigned_program_name: Optional[str] = None
    
    # Service completion counts
    services_completed: Optional[int] = None
    total_sessions: Optional[int] = None
    total_evaluations: Optional[int] = None
    services_this_week: Optional[int] = None
    
    # Historical engagement metrics
    weeks_enrolled: Optional[int] = None
    weeks_engaged: Optional[int] = None
    weeks_unengaged: Optional[int] = None
    consecutive_weeks: Optional[int] = None
    consecutive_weeks_status: Optional[str] = None
    
    # Timestamps
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Assignment Models
class PatientAssignmentRequest(BaseModel):
    patient_id: UUID
    program_id: UUID
    location_id: UUID

class BulkPatientAssignmentRequest(BaseModel):
    assignments: List[PatientAssignmentRequest]

class AssignmentResponse(BaseModel):
    success: bool
    message: str
    assigned_count: Optional[int] = None
    failed_assignments: Optional[List[dict]] = None

# Risk Models
class PatientCurrentWeekRisk(BaseModel):
    patient_id: UUID
    organization_id: UUID
    location_id: Optional[UUID] = None
    program_id: Optional[UUID] = None
    mr: str
    full_name: str
    assignment_status: AssignmentStatus
    current_week_start: date
    program_name: Optional[str] = None
    hours_required: Optional[float] = None
    level_of_care: Optional[str] = None
    location_name: Optional[str] = None
    location_timezone: Optional[str] = None
    hours_attended: float
    hours_remaining_needed: float
    clinic_hours_remaining: float
    risk_score: float
    tier_id: Optional[UUID] = None
    risk_level: Optional[str] = None
    tier_description: Optional[str] = None
    recommended_actions: Optional[str] = None
    risk_color: Optional[str] = None
    auto_flag_for_followup: Optional[bool] = None
    compliance_status: ComplianceStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Weekly Metrics Models
class PatientWeeklyMetrics(BaseModel):
    metric_id: UUID
    patient_id: UUID
    week_start_date: date
    program_id: UUID
    location_id: UUID
    hours_attended: float
    hours_required: float
    hours_remaining_needed: float
    sessions_attended: int
    sessions_missed: int
    clinic_hours_available_total: float
    clinic_hours_remaining: float
    risk_score: Optional[float] = None
    risk_tier_id: Optional[UUID] = None
    compliance_status: ComplianceStatus
    needs_followup: bool
    calculated_at: datetime
    calculation_source: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class WeeklyCalculationRequest(BaseModel):
    organization_id: Optional[UUID] = None
    week_start_date: Optional[date] = None

class WeeklyCalculationResponse(BaseModel):
    success: bool
    message: str
    calculated_count: int
    skipped_count: int
    error_count: int
    week_calculated: date