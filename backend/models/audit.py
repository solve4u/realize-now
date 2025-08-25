from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from enum import Enum

class AuditActionType(str, Enum):
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    ACCESS_DENIED = "ACCESS_DENIED"
    EXPORT = "EXPORT"

class AuditResourceType(str, Enum):
    USER = "USER"
    PATIENT = "PATIENT"
    ORGANIZATION = "ORGANIZATION"
    LOCATION = "LOCATION"
    PROGRAM = "PROGRAM"
    ENGAGEMENT = "ENGAGEMENT"
    RISK_TIER = "RISK_TIER"
    WEEKLY_METRICS = "WEEKLY_METRICS"
    AUTH = "AUTH"
    SYSTEM = "SYSTEM"

class AuditLogCreate(BaseModel):
    user_id: Optional[UUID] = None
    user_email: Optional[str] = None
    user_role: Optional[str] = None
    organization_id: Optional[UUID] = None
    session_id: Optional[str] = None
    
    method: str = Field(..., max_length=10)
    endpoint: str = Field(..., max_length=500)
    full_url: str = Field(..., max_length=1000)
    user_agent: Optional[str] = Field(None, max_length=500)
    ip_address: str = Field(..., max_length=45) 
    
    status_code: int
    response_time_ms: float
    
    action_type: AuditActionType
    resource_type: Optional[AuditResourceType] = None
    resource_id: Optional[str] = None  
    
    phi_accessed: bool = False  
    patient_id: Optional[UUID] = None  
    data_exported: bool = False  
    
    request_body_hash: Optional[str] = None 
    query_parameters: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    additional_context: Optional[Dict[str, Any]] = None

class AuditLogResponse(AuditLogCreate):
    audit_id: UUID
    timestamp: datetime
    
    class Config:
        from_attributes = True

class AuditLogFilter(BaseModel):
    user_id: Optional[UUID] = None
    user_email: Optional[str] = None
    organization_id: Optional[UUID] = None
    patient_id: Optional[UUID] = None
    action_type: Optional[AuditActionType] = None
    resource_type: Optional[AuditResourceType] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    ip_address: Optional[str] = None
    phi_accessed: Optional[bool] = None
    status_code_min: Optional[int] = None
    status_code_max: Optional[int] = None
