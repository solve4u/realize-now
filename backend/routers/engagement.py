from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
import asyncpg
from datetime import date, datetime
from utils.database import get_db_connection
from utils.dependencies import get_admin_user
from models.user import UserResponse, UserRole

router = APIRouter(prefix="/engagement", tags=["engagement"])

@router.get("/dashboard")
async def get_engagement_dashboard(
    current_user: UserResponse = Depends(get_admin_user),
    location_id: Optional[str] = Query(None, description="Filter by location ID"),
    program_id: Optional[str] = Query(None, description="Filter by program ID"),
    location_name: Optional[str] = Query(None, description="Filter by location name"),
    program_name: Optional[str] = Query(None, description="Filter by program name"),
    assignment_status: Optional[str] = Query(None, description="Filter by assignment status (assigned, pending)"),
    engagement_category: Optional[str] = Query(None, description="Filter by engagement category (engaged, partial, unengaged, unassigned, na)"),
    risk_category: Optional[str] = Query(None, description="Filter by risk category (engaged, low, medium, high, critical, na)"),
    start_date: Optional[date] = Query(None, description="Start date for filtering sessions (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date for filtering sessions (YYYY-MM-DD)"),
    limit: Optional[int] = Query(100, description="Maximum number of records to return"),
    offset: Optional[int] = Query(0, description="Number of records to skip")
):
    """
    Get patient engagement dashboard data with filtering and pagination.
    Returns comprehensive patient data including risk levels, hours completed, and engagement status.
    also supports date filtering to show data for specific time periods.
    """
    
    where_conditions = []
    params = []
    param_count = 0
    
    if current_user.role == UserRole.SYSTEM_ADMIN:
        pass
    else:
        param_count += 1
        where_conditions.append(f"organization_id = ${param_count}")
        params.append(current_user.organization_id)
    
    if location_id is not None:
        param_count += 1
        where_conditions.append(f"location_id = ${param_count}")
        params.append(location_id)
    elif location_name is not None:
        param_count += 1
        where_conditions.append(f"location_name = ${param_count}")
        params.append(location_name)
    
    if program_id is not None:
        param_count += 1
        where_conditions.append(f"program_id = ${param_count}")
        params.append(program_id)
    elif program_name is not None:
        param_count += 1
        where_conditions.append(f"program_name = ${param_count}")
        params.append(program_name)
    
    if assignment_status is not None:
        param_count += 1
        where_conditions.append(f"assignment_status = ${param_count}")
        params.append(assignment_status)
    
    if engagement_category is not None:
        param_count += 1
        where_conditions.append(f"engagement_category = ${param_count}")
        params.append(engagement_category)
    
    if risk_category is not None:
        param_count += 1
        where_conditions.append(f"risk_category = ${param_count}")
        params.append(risk_category)
    
    if start_date is None and end_date is None:
        param_count += 1
        limit_param = f"${param_count}"
        params.append(limit)
        
        param_count += 1
        offset_param = f"${param_count}"
        params.append(offset)
        where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
        
        query = f"""
        SELECT 
            patient_id,
            full_name,
            first_name,
            last_name,
            mr,
            organization_id,
            location_id,
            location_name,
            program_id,
            program_name,
            program_hours_per_week,
            assignment_status,
            status,
            admission_date,
            discharge_date,
            current_week_start,
            current_week_end,
            sessions_completed_this_week,
            total_sessions_completed,
            hours_completed,
            hours_required,
            hours_remaining,
            total_hours_completed,
            completion_percentage,
            risk_ratio,
            risk_level,
            tier_description,
            recommended_actions,
            color,
            auto_flag_for_followup,
            engagement_status,
            engagement_category,
            risk_category
        FROM patient_engagement_dashboard 
        {where_clause}
        ORDER BY 
            CASE assignment_status WHEN 'assigned' THEN 1 ELSE 2 END,
            risk_ratio DESC,
            full_name
        LIMIT {limit_param} OFFSET {offset_param}
        """
    else:
        param_count += 1
        start_date_param = f"${param_count}"
        params.append(start_date)
        
        param_count += 1
        end_date_param = f"${param_count}"
        params.append(end_date)
        
        param_count += 1
        limit_param = f"${param_count}"
        params.append(limit)
        
        param_count += 1
        offset_param = f"${param_count}"
        params.append(offset)
        
        where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
        
        query = f"""
        SELECT 
            patient_id,
            full_name,
            first_name,
            last_name,
            mr,
            organization_id,
            location_id,
            location_name,
            program_id,
            program_name,
            program_hours_per_week,
            assignment_status,
            status,
            admission_date,
            discharge_date,
            filter_week_start as current_week_start,
            filter_week_end as current_week_end,
            sessions_completed_this_week,
            total_sessions_completed,
            hours_completed,
            hours_required,
            hours_remaining,
            total_hours_completed,
            completion_percentage,
            risk_ratio,
            risk_level,
            tier_description,
            recommended_actions,
            color,
            auto_flag_for_followup,
            engagement_status,
            engagement_category,
            risk_category
        FROM get_patient_engagement_dashboard_filtered({start_date_param}::DATE, {end_date_param}::DATE)
        {where_clause}
        ORDER BY 
            CASE assignment_status WHEN 'assigned' THEN 1 ELSE 2 END,
            risk_ratio DESC,
            full_name
        LIMIT {limit_param} OFFSET {offset_param}
        """
    
    try:
        async with get_db_connection() as db:
            # Set RLS context
            await db.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
            if current_user.organization_id:
                await db.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))
            
            rows = await db.fetch(query, *params)
            
            if start_date is None and end_date is None:
                count_query = f"""
                SELECT COUNT(*) as total 
                FROM patient_engagement_dashboard 
                {where_clause}
                """
            else:
                count_query = f"""
                SELECT COUNT(*) as total 
                FROM get_patient_engagement_dashboard_filtered({start_date_param}::DATE, {end_date_param}::DATE)
                {where_clause}
                """
            
            count_params = params[:-2]  
            count_result = await db.fetchrow(count_query, *count_params)
            total_count = count_result["total"]
        
        results = []
        for row in rows:
            patient_data = {
                "patient_id": str(row["patient_id"]),
                "full_name": row["full_name"],
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "mr": row["mr"],
                "organization_id": row["organization_id"],
                "location": {
                    "id": row["location_id"],
                    "name": row["location_name"]
                },
                "program": {
                    "id": row["program_id"],
                    "name": row["program_name"],
                    "hours_per_week": float(row["program_hours_per_week"]) if row["program_hours_per_week"] else None
                },
                "assignment_status": row["assignment_status"],
                "status": row["status"],
                "admission_date": row["admission_date"].isoformat() if row["admission_date"] else None,
                "discharge_date": row["discharge_date"].isoformat() if row["discharge_date"] else None,
                "current_week": {
                    "start": row["current_week_start"].isoformat(),
                    "end": row["current_week_end"].isoformat()
                },
                "sessions": {
                    "completed_this_week": row["sessions_completed_this_week"],
                    "hours_completed": float(row["hours_completed"]) if row["hours_completed"] else 0.0,
                    "total_hours_completed_this_week": float(row["total_hours_completed"]) if row["total_hours_completed"] else 0.0,
                    "hours_required": float(row["hours_required"]) if row["hours_required"] else None,
                    "hours_remaining": float(row["hours_remaining"]) if row["hours_remaining"] else 0.0,
                    "completion_percentage": float(row["completion_percentage"]) if row["completion_percentage"] else 0.0,
                    "total_sessions": row["total_sessions_completed"],
                },
                "risk": {
                    "ratio": float(row["risk_ratio"]) if row["risk_ratio"] else 0.0,
                    "level": row["risk_level"],
                    "category": row["risk_category"],
                    "description": row["tier_description"],
                    "recommended_actions": row["recommended_actions"],
                    "color": row["color"],
                    "auto_flag_for_followup": row["auto_flag_for_followup"]
                },
                "engagement": {
                    "status": row["engagement_status"],
                    "category": row["engagement_category"]
                }
            }
            results.append(patient_data)
        
        return {
            "data": results,
            "pagination": {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": offset + len(results) < total_count
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.get("/dashboard/summary")
async def get_engagement_summary(
    current_user: UserResponse = Depends(get_admin_user),
    location_id: Optional[str] = Query(None, description="Filter by location ID"),
    program_id: Optional[str] = Query(None, description="Filter by program ID"),
    location_name: Optional[str] = Query(None, description="Filter by location name"),
    program_name: Optional[str] = Query(None, description="Filter by program name"),
    start_date: Optional[date] = Query(None, description="Start date for filtering sessions (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date for filtering sessions (YYYY-MM-DD)")
):
    """
    Get summary statistics for the engagement dashboard.
    """
    
    where_conditions = []
    params = []
    param_count = 0
    
    if current_user.role == UserRole.SYSTEM_ADMIN:
        pass
    else:
        param_count += 1
        where_conditions.append(f"organization_id = ${param_count}")
        params.append(current_user.organization_id)
    
    if location_id is not None:
        param_count += 1
        where_conditions.append(f"location_id = ${param_count}")
        params.append(location_id)
    elif location_name is not None:
        param_count += 1
        where_conditions.append(f"location_name = ${param_count}")
        params.append(location_name)
    
    if program_id is not None:
        param_count += 1
        where_conditions.append(f"program_id = ${param_count}")
        params.append(program_id)
    elif program_name is not None:
        param_count += 1
        where_conditions.append(f"program_name = ${param_count}")
        params.append(program_name)
    
    if start_date is None and end_date is None:
        where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
        
        query = f"""
        SELECT 
            COUNT(*) as total_patients,
            COUNT(CASE WHEN assignment_status = 'assigned' THEN 1 END) as assigned_patients,
            COUNT(CASE WHEN assignment_status = 'pending' THEN 1 END) as pending_patients,
            COUNT(CASE WHEN engagement_category = 'engaged' THEN 1 END) as engaged_patients,
            COUNT(CASE WHEN engagement_category = 'partial' THEN 1 END) as partial_patients,
            COUNT(CASE WHEN engagement_category = 'unengaged' THEN 1 END) as unengaged_patients,
            COUNT(CASE WHEN risk_category = 'engaged' THEN 1 END) as low_risk_patients,
            COUNT(CASE WHEN risk_category = 'low' THEN 1 END) as low_risk_patients_alt,
            COUNT(CASE WHEN risk_category = 'medium' THEN 1 END) as medium_risk_patients,
            COUNT(CASE WHEN risk_category = 'high' THEN 1 END) as high_risk_patients,
            COUNT(CASE WHEN risk_category = 'critical' THEN 1 END) as critical_risk_patients,
            COUNT(CASE WHEN auto_flag_for_followup = true THEN 1 END) as flagged_for_followup,
            AVG(CASE WHEN assignment_status = 'assigned' AND completion_percentage IS NOT NULL THEN completion_percentage END) as avg_completion_percentage,
            SUM(CASE WHEN assignment_status = 'assigned' THEN hours_completed ELSE 0 END) as total_hours_completed,
            SUM(CASE WHEN assignment_status = 'assigned' THEN sessions_completed_this_week ELSE 0 END) as total_sessions_completed
        FROM patient_engagement_dashboard 
        {where_clause}
        """
    else:
        param_count += 1
        start_date_param = f"${param_count}"
        params.append(start_date)
        
        param_count += 1
        end_date_param = f"${param_count}"
        params.append(end_date)
        
        where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
        
        query = f"""
        SELECT 
            COUNT(*) as total_patients,
            COUNT(CASE WHEN assignment_status = 'assigned' THEN 1 END) as assigned_patients,
            COUNT(CASE WHEN assignment_status = 'pending' THEN 1 END) as pending_patients,
            COUNT(CASE WHEN engagement_category = 'engaged' THEN 1 END) as engaged_patients,
            COUNT(CASE WHEN engagement_category = 'partial' THEN 1 END) as partial_patients,
            COUNT(CASE WHEN engagement_category = 'unengaged' THEN 1 END) as unengaged_patients,
            COUNT(CASE WHEN risk_category = 'engaged' THEN 1 END) as low_risk_patients,
            COUNT(CASE WHEN risk_category = 'low' THEN 1 END) as low_risk_patients_alt,
            COUNT(CASE WHEN risk_category = 'medium' THEN 1 END) as medium_risk_patients,
            COUNT(CASE WHEN risk_category = 'high' THEN 1 END) as high_risk_patients,
            COUNT(CASE WHEN risk_category = 'critical' THEN 1 END) as critical_risk_patients,
            COUNT(CASE WHEN auto_flag_for_followup = true THEN 1 END) as flagged_for_followup,
            AVG(CASE WHEN assignment_status = 'assigned' AND completion_percentage IS NOT NULL THEN completion_percentage END) as avg_completion_percentage,
            SUM(CASE WHEN assignment_status = 'assigned' THEN hours_completed ELSE 0 END) as total_hours_completed,
            SUM(CASE WHEN assignment_status = 'assigned' THEN sessions_completed_this_week ELSE 0 END) as total_sessions_completed
        FROM get_patient_engagement_dashboard_filtered({start_date_param}::date, {end_date_param}::date) 
        {where_clause}
        """
    
    try:
        async with get_db_connection() as db:
            # Set RLS context
            await db.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
            if current_user.organization_id:
                await db.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))
            
            result = await db.fetchrow(query, *params)
        
        return {
            "total_patients": result["total_patients"],
            "assignment_status": {
                "assigned": result["assigned_patients"],
                "pending": result["pending_patients"]
            },
            "engagement": {
                "engaged": result["engaged_patients"],
                "partial": result["partial_patients"],
                "unengaged": result["unengaged_patients"]
            },
            "risk": {
                "engaged": result["low_risk_patients"],
                "low": result["low_risk_patients_alt"],
                "medium": result["medium_risk_patients"],
                "high": result["high_risk_patients"],
                "critical": result["critical_risk_patients"]
            },
            "follow_up": {
                "flagged_count": result["flagged_for_followup"]
            },
            "metrics": {
                "avg_completion_percentage": float(result["avg_completion_percentage"]) if result["avg_completion_percentage"] else 0.0,
                "total_hours_completed": float(result["total_hours_completed"]) if result["total_hours_completed"] else 0.0,
                "total_sessions_completed": result["total_sessions_completed"]
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
