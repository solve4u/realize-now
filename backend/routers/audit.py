from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from datetime import datetime, timedelta
from uuid import UUID

from models.audit import AuditLogResponse, AuditLogFilter, AuditActionType, AuditResourceType
from models.user import UserResponse, UserRole
from utils.database import get_db_connection
from utils.dependencies import get_current_user, get_system_admin

router = APIRouter(prefix="/audit", tags=["Audit Logs"])

@router.get("/logs", response_model=List[AuditLogResponse])
async def get_audit_logs(
    limit: int = Query(100, le=1000, description="Maximum number of logs to return"),
    offset: int = Query(0, ge=0, description="Number of logs to skip"),
    user_id: Optional[UUID] = Query(None, description="Filter by user ID"),
    user_email: Optional[str] = Query(None, description="Filter by user email"),
    action_type: Optional[AuditActionType] = Query(None, description="Filter by action type"),
    resource_type: Optional[AuditResourceType] = Query(None, description="Filter by resource type"),
    phi_accessed: Optional[bool] = Query(None, description="Filter by PHI access"),
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    ip_address: Optional[str] = Query(None, description="Filter by IP address"),
    current_user: UserResponse = Depends(get_system_admin)
):
    """
    Get audit logs. Only accessible by system administrators.
    Supports filtering and pagination for compliance reporting.
    """
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # Build WHERE clause
        where_conditions = []
        params = []
        param_count = 0

        if user_id:
            param_count += 1
            where_conditions.append(f"user_id = ${param_count}")
            params.append(user_id)

        if user_email:
            param_count += 1
            where_conditions.append(f"user_email ILIKE ${param_count}")
            params.append(f"%{user_email}%")

        if action_type:
            param_count += 1
            where_conditions.append(f"action_type = ${param_count}")
            params.append(action_type.value)

        if resource_type:
            param_count += 1
            where_conditions.append(f"resource_type = ${param_count}")
            params.append(resource_type.value)

        if phi_accessed is not None:
            param_count += 1
            where_conditions.append(f"phi_accessed = ${param_count}")
            params.append(phi_accessed)

        if start_date:
            param_count += 1
            where_conditions.append(f"timestamp >= ${param_count}")
            params.append(start_date)

        if end_date:
            param_count += 1
            where_conditions.append(f"timestamp <= ${param_count}")
            params.append(end_date)

        if ip_address:
            param_count += 1
            where_conditions.append(f"ip_address = ${param_count}")
            params.append(ip_address)

        # Add pagination
        param_count += 1
        limit_param = f"${param_count}"
        params.append(limit)

        param_count += 1
        offset_param = f"${param_count}"
        params.append(offset)

        # Build query
        where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
        
        query = f"""
            SELECT * FROM audit_logs 
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT {limit_param} OFFSET {offset_param}
        """

        logs = await conn.fetch(query, *params)
        return [AuditLogResponse(**dict(log)) for log in logs]

@router.get("/logs/phi", response_model=List[AuditLogResponse])
async def get_phi_access_logs(
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    patient_id: Optional[UUID] = Query(None, description="Filter by specific patient"),
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    current_user: UserResponse = Depends(get_system_admin)
):
    """
    Get audit logs specifically for PHI (Protected Health Information) access.
    Critical for HIPAA compliance reporting.
    """
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)

        where_conditions = ["phi_accessed = true"]
        params = []
        param_count = 0

        if patient_id:
            param_count += 1
            where_conditions.append(f"patient_id = ${param_count}")
            params.append(patient_id)

        if start_date:
            param_count += 1
            where_conditions.append(f"timestamp >= ${param_count}")
            params.append(start_date)

        if end_date:
            param_count += 1
            where_conditions.append(f"timestamp <= ${param_count}")
            params.append(end_date)

        # Add pagination
        param_count += 1
        limit_param = f"${param_count}"
        params.append(limit)

        param_count += 1
        offset_param = f"${param_count}"
        params.append(offset)

        query = f"""
            SELECT * FROM audit_logs 
            WHERE {' AND '.join(where_conditions)}
            ORDER BY timestamp DESC
            LIMIT {limit_param} OFFSET {offset_param}
        """

        logs = await conn.fetch(query, *params)
        return [AuditLogResponse(**dict(log)) for log in logs]

@router.get("/logs/failed-access", response_model=List[AuditLogResponse])
async def get_failed_access_logs(
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    hours: int = Query(24, description="Look back this many hours"),
    current_user: UserResponse = Depends(get_system_admin)
):
    """
    Get failed access attempts (401, 403 status codes).
    Important for security monitoring.
    """
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)

        since_time = datetime.utcnow() - timedelta(hours=hours)
        
        query = """
            SELECT * FROM audit_logs 
            WHERE status_code IN (401, 403) 
            AND timestamp >= $1
            ORDER BY timestamp DESC
            LIMIT $2 OFFSET $3
        """

        logs = await conn.fetch(query, since_time, limit, offset)
        return [AuditLogResponse(**dict(log)) for log in logs]

@router.get("/stats/summary")
async def get_audit_summary(
    hours: int = Query(24, description="Look back this many hours"),
    current_user: UserResponse = Depends(get_system_admin)
):
    """
    Get audit statistics summary for monitoring dashboard.
    """
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)

        since_time = datetime.utcnow() - timedelta(hours=hours)
        
        summary = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total_requests,
                COUNT(CASE WHEN phi_accessed = true THEN 1 END) as phi_access_count,
                COUNT(CASE WHEN data_exported = true THEN 1 END) as data_export_count,
                COUNT(CASE WHEN status_code >= 400 THEN 1 END) as failed_requests,
                COUNT(CASE WHEN status_code IN (401, 403) THEN 1 END) as access_denied_count,
                COUNT(DISTINCT user_id) as unique_users,
                COUNT(DISTINCT ip_address) as unique_ips,
                AVG(response_time_ms) as avg_response_time
            FROM audit_logs 
            WHERE timestamp >= $1
        """, since_time)

        return {
            "period_hours": hours,
            "total_requests": summary['total_requests'],
            "phi_access_count": summary['phi_access_count'],
            "data_export_count": summary['data_export_count'],
            "failed_requests": summary['failed_requests'],
            "access_denied_count": summary['access_denied_count'],
            "unique_users": summary['unique_users'],
            "unique_ips": summary['unique_ips'],
            "avg_response_time_ms": float(summary['avg_response_time']) if summary['avg_response_time'] else 0
        }

@router.post("/cleanup")
async def cleanup_old_logs(
    retention_months: int = Query(84, description="Retention period in months (default: 84 = 7 years)"),
    current_user: UserResponse = Depends(get_system_admin)
):
    """
    Clean up old audit logs based on retention policy.
    Default is 7 years for HIPAA compliance.
    """
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)

        # Call the cleanup function
        deleted_count = await conn.fetchval("""
            SELECT cleanup_old_audit_logs($1)
        """, retention_months)

        return {
            "message": f"Cleanup completed successfully",
            "deleted_count": deleted_count,
            "retention_months": retention_months
        }
