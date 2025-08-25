from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from datetime import datetime, date

from models.data_import import (
    SFTPRawDataResponse, ImportSummary, ImportStatsResponse, 
    DataImportOverview, ImportStatus, ServiceType
)
from models.user import UserResponse, UserRole
from utils.database import get_db_connection
from utils.dependencies import get_current_user, get_admin_user

router = APIRouter(prefix="/data-import", tags=["Data Import"])

@router.get("/stats", response_model=ImportStatsResponse)
async def get_import_stats(
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get overall import statistics for the organization."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # Get summary stats
        summary_stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total_records,
                COUNT(*) FILTER (WHERE status = 'pending') as pending,
                COUNT(*) FILTER (WHERE status = 'processing') as processing,
                COUNT(*) FILTER (WHERE status = 'processed') as processed,
                COUNT(*) FILTER (WHERE status = 'error') as error,
                COUNT(*) FILTER (WHERE status = 'skipped') as skipped,
                MAX(imported_at) as latest_import
            FROM sftp_services_raw_data
        """)
        
        # Get recent files
        recent_files = await conn.fetch("""
            SELECT DISTINCT file_name 
            FROM sftp_services_raw_data 
            WHERE file_name IS NOT NULL
            ORDER BY file_name DESC 
            LIMIT 10
        """)
        
        # Get organization info (if org admin)
        org_info = None
        if current_user.role == UserRole.ORGANIZATION_ADMIN:
            org_info = await conn.fetchrow("""
                SELECT organization_id, name 
                FROM organizations 
                WHERE organization_id = $1
            """, current_user.organization_id)
        
        summary = ImportSummary(**dict(summary_stats))
        file_list = [row['file_name'] for row in recent_files if row['file_name']]
        
        return ImportStatsResponse(
            organization_id=org_info['organization_id'] if org_info else None,
            organization_name=org_info['name'] if org_info else None,
            summary=summary,
            recent_files=file_list
        )

@router.get("/overview", response_model=List[DataImportOverview])
async def get_import_overview(
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get import overview broken down by organization and location."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        overview_data = await conn.fetch("""
            SELECT 
                srd.organization_id,
                o.name as organization_name,
                srd.location_id,
                l.name as location_name,
                COUNT(*) as total_records,
                MAX(srd.imported_at) as latest_import,
                -- Status breakdown as JSON
                json_object_agg(srd.status, status_count) as status_breakdown
            FROM sftp_services_raw_data srd
            JOIN organizations o ON srd.organization_id = o.organization_id
            JOIN locations l ON srd.location_id = l.location_id
            JOIN (
                -- Subquery to get status counts
                SELECT 
                    organization_id, location_id, status, COUNT(*) as status_count
                FROM sftp_services_raw_data
                GROUP BY organization_id, location_id, status
            ) status_stats ON (
                srd.organization_id = status_stats.organization_id 
                AND srd.location_id = status_stats.location_id 
                AND srd.status = status_stats.status
            )
            GROUP BY srd.organization_id, o.name, srd.location_id, l.name
            ORDER BY o.name, l.name
        """)
        
        # Get recent files for each org/location
        result = []
        for row in overview_data:
            recent_files = await conn.fetch("""
                SELECT DISTINCT file_name 
                FROM sftp_services_raw_data 
                WHERE organization_id = $1 AND location_id = $2 AND file_name IS NOT NULL
                ORDER BY file_name DESC 
                LIMIT 5
            """, row['organization_id'], row['location_id'])
            
            # Get recent errors
            recent_errors = await conn.fetch("""
                SELECT error_message, COUNT(*) as count, MAX(imported_at) as last_seen
                FROM sftp_services_raw_data 
                WHERE organization_id = $1 AND location_id = $2 AND status = 'error'
                  AND error_message IS NOT NULL
                GROUP BY error_message
                ORDER BY last_seen DESC
                LIMIT 3
            """, row['organization_id'], row['location_id'])
            
            result.append(DataImportOverview(
                organization_id=row['organization_id'],
                organization_name=row['organization_name'],
                location_id=row['location_id'],
                location_name=row['location_name'],
                total_records=row['total_records'],
                status_breakdown=dict(row['status_breakdown']) if row['status_breakdown'] else {},
                recent_files=[f['file_name'] for f in recent_files if f['file_name']],
                latest_import=row['latest_import'],
                processing_errors=[{
                    'error': err['error_message'],
                    'count': err['count'],
                    'last_seen': err['last_seen']
                } for err in recent_errors]
            ))
        
        return result

@router.get("/records", response_model=List[SFTPRawDataResponse])
async def get_import_records(
    status: Optional[ImportStatus] = Query(None, description="Filter by import status"),
    service_type: Optional[ServiceType] = Query(None, description="Filter by service type"),
    file_name: Optional[str] = Query(None, description="Filter by file name"),
    limit: int = Query(default=100, le=200, description="Number of records to return"),
    offset: int = Query(default=0, description="Number of records to skip"),
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get SFTP raw data records with filtering and pagination."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # Build dynamic query
        where_conditions = []
        params = []
        param_count = 0
        
        if status:
            param_count += 1
            where_conditions.append(f"status = ${param_count}")
            params.append(status.value)
        
        if service_type:
            param_count += 1
            where_conditions.append(f"service_type = ${param_count}")
            params.append(service_type.value)
        
        if file_name:
            param_count += 1
            where_conditions.append(f"file_name ILIKE ${param_count}")
            params.append(f"%{file_name}%")
        
        where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
        
        # Add pagination params
        param_count += 1
        limit_param = f"${param_count}"
        params.append(limit)
        
        param_count += 1
        offset_param = f"${param_count}"
        params.append(offset)
        
        query = f"""
            SELECT * FROM sftp_services_raw_data 
            {where_clause}
            ORDER BY imported_at DESC, created_at DESC
            LIMIT {limit_param} OFFSET {offset_param}
        """
        
        records = await conn.fetch(query, *params)
        
        return [SFTPRawDataResponse(**dict(record)) for record in records]

@router.get("/records/{record_id}", response_model=SFTPRawDataResponse)
async def get_import_record(
    record_id: str,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get a specific SFTP raw data record."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        record = await conn.fetchrow("""
            SELECT * FROM sftp_services_raw_data 
            WHERE record_id = $1
        """, record_id)
        
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Record not found or access denied"
            )
        
        return SFTPRawDataResponse(**dict(record))

@router.get("/files", response_model=List[str])
async def get_import_files(
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get list of imported file names."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        files = await conn.fetch("""
            SELECT DISTINCT file_name, MAX(imported_at) as latest_import
            FROM sftp_services_raw_data 
            WHERE file_name IS NOT NULL
            GROUP BY file_name
            ORDER BY latest_import DESC
            LIMIT 50
        """)
        
        return [file['file_name'] for file in files]

@router.post("/reprocess/{record_id}")
async def reprocess_record(
    record_id: str,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Reprocess a failed SFTP record."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # Check if record exists and has error status
        record = await conn.fetchrow("""
            SELECT record_id, status, error_message 
            FROM sftp_services_raw_data 
            WHERE record_id = $1
        """, record_id)
        
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Record not found or access denied"
            )
        
        if record['status'] not in ['error', 'skipped']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Record is in '{record['status']}' status and cannot be reprocessed"
            )
        
        try:
            # Reset record status to pending for reprocessing
            await conn.execute("""
                UPDATE sftp_services_raw_data 
                SET status = 'pending', error_message = NULL, processed_at = NULL, updated_at = NOW()
                WHERE record_id = $1
            """, record_id)
            
            return {"message": "Record marked for reprocessing", "record_id": record_id}
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to reprocess record: {str(e)}"
            )

@router.get("/errors", response_model=List[dict])
async def get_import_errors(
    limit: int = Query(default=20, le=100),
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get recent import errors with details."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        errors = await conn.fetch("""
            SELECT 
                srd.record_id,
                srd.file_name,
                srd.error_message,
                srd.full_name,
                srd.mr,
                srd.service_type,
                srd.imported_at,
                o.name as organization_name,
                l.name as location_name
            FROM sftp_services_raw_data srd
            JOIN organizations o ON srd.organization_id = o.organization_id
            JOIN locations l ON srd.location_id = l.location_id
            WHERE srd.status = 'error' AND srd.error_message IS NOT NULL
            ORDER BY srd.imported_at DESC
            LIMIT $1
        """, limit)
        
        return [dict(error) for error in errors]