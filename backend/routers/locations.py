from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
import uuid

from models.location import LocationResponse, LocationCreate, LocationCreateUpdate, LocationWithStats, LocationTimingsUpdate
from models.user import UserResponse, UserRole
from utils.database import get_db_connection
from utils.dependencies import get_current_user, get_admin_user

router = APIRouter(prefix="/locations", tags=["Location Management"])

@router.get("/", response_model=List[LocationResponse])
async def get_locations(
    current_user: UserResponse = Depends(get_current_user)
):
    """Get locations accessible to the current user."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # Filter locations based on user role
        if current_user.role == UserRole.SYSTEM_ADMIN:
            # System admin sees all locations
            locations = await conn.fetch("""
                SELECT * FROM locations 
                ORDER BY name
            """)
        else:
            # Organization admin and other roles see only their org's locations
            locations = await conn.fetch("""
                SELECT * FROM locations 
                WHERE organization_id = $1
                ORDER BY name
            """, current_user.organization_id)
        
        return [LocationResponse(**dict(location)) for location in locations]

@router.get("/with-stats", response_model=List[LocationWithStats])
async def get_locations_with_stats(
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get locations with patient statistics and current week hours remaining."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # Filter locations based on user role
        if current_user.role == UserRole.SYSTEM_ADMIN:
            # System admin sees all locations with stats
            locations_with_stats = await conn.fetch("""
                SELECT 
                    l.*,
                    COALESCE(patient_stats.total_patients, 0) as total_patients,
                    COALESCE(patient_stats.assigned_patients, 0) as assigned_patients,
                    COALESCE(patient_stats.pending_patients, 0) as pending_patients,
                    get_remaining_hours_this_week(l.location_id) as weekly_hours_remaining
                FROM locations l
                LEFT JOIN (
                    SELECT 
                        location_id,
                        COUNT(*) as total_patients,
                        COUNT(*) FILTER (WHERE assignment_status = 'assigned') as assigned_patients,
                        COUNT(*) FILTER (WHERE assignment_status = 'pending') as pending_patients
                    FROM patients 
                    WHERE status = 'active'
                    GROUP BY location_id
                ) patient_stats ON l.location_id = patient_stats.location_id
                ORDER BY l.name
            """)
        else:
            # Organization admin sees only their org's locations with stats
            locations_with_stats = await conn.fetch("""
                SELECT 
                    l.*,
                    COALESCE(patient_stats.total_patients, 0) as total_patients,
                    COALESCE(patient_stats.assigned_patients, 0) as assigned_patients,
                    COALESCE(patient_stats.pending_patients, 0) as pending_patients,
                    get_remaining_hours_this_week(l.location_id) as weekly_hours_remaining
                FROM locations l
                LEFT JOIN (
                    SELECT 
                        location_id,
                        COUNT(*) as total_patients,
                        COUNT(*) FILTER (WHERE assignment_status = 'assigned') as assigned_patients,
                        COUNT(*) FILTER (WHERE assignment_status = 'pending') as pending_patients
                    FROM patients 
                    WHERE status = 'active'
                    GROUP BY location_id
                ) patient_stats ON l.location_id = patient_stats.location_id
                WHERE l.organization_id = $1
                ORDER BY l.name
            """, current_user.organization_id)
        
        return [LocationWithStats(**dict(location)) for location in locations_with_stats]

@router.get("/{location_id}", response_model=LocationWithStats)
async def get_location(
    location_id: uuid.UUID,
    current_user: UserResponse = Depends(get_current_user)
):
    """Get a specific location with statistics."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # Filter location access based on user role
        if current_user.role == UserRole.SYSTEM_ADMIN:
            # System admin can access any location
            location = await conn.fetchrow("""
                SELECT 
                    l.*,
                    COALESCE(patient_stats.total_patients, 0) as total_patients,
                    COALESCE(patient_stats.assigned_patients, 0) as assigned_patients,
                    COALESCE(patient_stats.pending_patients, 0) as pending_patients,
                    get_remaining_hours_this_week(l.location_id) as weekly_hours_remaining
                FROM locations l
                LEFT JOIN (
                    SELECT 
                        location_id,
                        COUNT(*) as total_patients,
                        COUNT(*) FILTER (WHERE assignment_status = 'assigned') as assigned_patients,
                        COUNT(*) FILTER (WHERE assignment_status = 'pending') as pending_patients
                    FROM patients 
                    WHERE status = 'active'
                    GROUP BY location_id
                ) patient_stats ON l.location_id = patient_stats.location_id
                WHERE l.location_id = $1
            """, location_id)
        else:
            # Organization admin can only access locations in their org
            location = await conn.fetchrow("""
                SELECT 
                    l.*,
                    COALESCE(patient_stats.total_patients, 0) as total_patients,
                    COALESCE(patient_stats.assigned_patients, 0) as assigned_patients,
                    COALESCE(patient_stats.pending_patients, 0) as pending_patients,
                    get_remaining_hours_this_week(l.location_id) as weekly_hours_remaining
                FROM locations l
                LEFT JOIN (
                    SELECT 
                        location_id,
                        COUNT(*) as total_patients,
                        COUNT(*) FILTER (WHERE assignment_status = 'assigned') as assigned_patients,
                        COUNT(*) FILTER (WHERE assignment_status = 'pending') as pending_patients
                    FROM patients 
                    WHERE status = 'active'
                    GROUP BY location_id
                ) patient_stats ON l.location_id = patient_stats.location_id
                WHERE l.location_id = $1 AND l.organization_id = $2
            """, location_id, current_user.organization_id)
        
        if not location:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Location not found or access denied"
            )
        
        return LocationWithStats(**dict(location))

@router.post("/", response_model=LocationResponse)
async def create_location(
    location: LocationCreate,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Create a new location."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # Organization admin can only create locations in their org
        if current_user.role == UserRole.ORGANIZATION_ADMIN:
            location.organization_id = current_user.organization_id
        
        try:
            location_id = await conn.fetchval("""
                INSERT INTO locations (
                    organization_id, name, timezone,
                    monday_open, monday_close, tuesday_open, tuesday_close,
                    wednesday_open, wednesday_close, thursday_open, thursday_close,
                    friday_open, friday_close, saturday_open, saturday_close,
                    sunday_open, sunday_close
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
                RETURNING location_id
            """, 
                location.organization_id, location.name, location.timezone,
                location.monday_open, location.monday_close, location.tuesday_open, location.tuesday_close,
                location.wednesday_open, location.wednesday_close, location.thursday_open, location.thursday_close,
                location.friday_open, location.friday_close, location.saturday_open, location.saturday_close,
                location.sunday_open, location.sunday_close
            )
            
            # Get the created location
            new_location = await conn.fetchrow("""
                SELECT * FROM locations WHERE location_id = $1
            """, location_id)
            
            return LocationResponse(**dict(new_location))
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create location: {str(e)}"
            )

@router.put("/{location_id}", response_model=LocationResponse)
async def update_location(
    location_id: uuid.UUID,
    location_update: LocationCreateUpdate,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Update a location."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # Verify location exists and user has access
        if current_user.role == UserRole.SYSTEM_ADMIN:
            existing_location = await conn.fetchrow("""
                SELECT location_id, organization_id FROM locations WHERE location_id = $1
            """, location_id)
        else:
            existing_location = await conn.fetchrow("""
                SELECT location_id, organization_id FROM locations 
                WHERE location_id = $1 AND organization_id = $2
            """, location_id, current_user.organization_id)
        
        if not existing_location:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Location not found or access denied"
            )
        
        try:
            await conn.execute("""
                UPDATE locations SET
                    name = $1, timezone = $2,
                    monday_open = $3, monday_close = $4, tuesday_open = $5, tuesday_close = $6,
                    wednesday_open = $7, wednesday_close = $8, thursday_open = $9, thursday_close = $10,
                    friday_open = $11, friday_close = $12, saturday_open = $13, saturday_close = $14,
                    sunday_open = $15, sunday_close = $16, updated_at = NOW()
                WHERE location_id = $17
            """, 
                location_update.name, location_update.timezone,
                location_update.monday_open, location_update.monday_close, location_update.tuesday_open, location_update.tuesday_close,
                location_update.wednesday_open, location_update.wednesday_close, location_update.thursday_open, location_update.thursday_close,
                location_update.friday_open, location_update.friday_close, location_update.saturday_open, location_update.saturday_close,
                location_update.sunday_open, location_update.sunday_close, location_id
            )
            
            # Get the updated location
            updated_location = await conn.fetchrow("""
                SELECT * FROM locations WHERE location_id = $1
            """, location_id)
            
            return LocationResponse(**dict(updated_location))
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update location: {str(e)}"
            )

@router.patch("/{location_id}/timings", response_model=LocationResponse)
async def update_location_timings(
    location_id: uuid.UUID,
    timings_update: LocationTimingsUpdate,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Update only the timings and timezone for a location."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # Verify location exists and user has access
        if current_user.role == UserRole.SYSTEM_ADMIN:
            existing_location = await conn.fetchrow("""
                SELECT location_id, organization_id FROM locations WHERE location_id = $1
            """, location_id)
        else:
            existing_location = await conn.fetchrow("""
                SELECT location_id, organization_id FROM locations 
                WHERE location_id = $1 AND organization_id = $2
            """, location_id, current_user.organization_id)
        
        if not existing_location:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Location not found or access denied"
            )
        
        # Build dynamic update query based on provided fields
        update_fields = []
        update_values = []
        param_count = 1
        
        for field_name, field_value in timings_update.dict(exclude_unset=True).items():
            if field_value is not None:
                update_fields.append(f"{field_name} = ${param_count}")
                update_values.append(field_value)
                param_count += 1
        
        if not update_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields provided for update"
            )
        
        # Add updated_at field
        update_fields.append(f"updated_at = ${param_count}")
        update_values.append("NOW()")
        param_count += 1
        
        # Add location_id for WHERE clause
        update_values.append(location_id)
        
        try:
            query = f"""
                UPDATE locations SET
                    {', '.join(update_fields)}
                WHERE location_id = ${param_count}
            """
            
            await conn.execute(query, *update_values[:-1], location_id)
            
            # Get the updated location
            updated_location = await conn.fetchrow("""
                SELECT * FROM locations WHERE location_id = $1
            """, location_id)
            
            return LocationResponse(**dict(updated_location))
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update location timings: {str(e)}"
            )

@router.delete("/{location_id}")
async def delete_location(
    location_id: uuid.UUID,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Delete a location if no patients are associated with it."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # Verify location exists and user has access
        if current_user.role == UserRole.SYSTEM_ADMIN:
            existing_location = await conn.fetchrow("""
                SELECT location_id, organization_id, name FROM locations WHERE location_id = $1
            """, location_id)
        else:
            existing_location = await conn.fetchrow("""
                SELECT location_id, organization_id, name FROM locations 
                WHERE location_id = $1 AND organization_id = $2
            """, location_id, current_user.organization_id)
        
        if not existing_location:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Location not found or access denied"
            )
        
        # Check if location has associated patients
        patient_count = await conn.fetchval("""
            SELECT COUNT(*) FROM patients 
            WHERE location_id = $1 AND status = 'active'
        """, location_id)
        
        if patient_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete location. {patient_count} active patients are assigned to this location. Please reassign or deactivate all patients before deleting."
            )
        
        try:
            # Delete the location
            await conn.execute("""
                DELETE FROM locations WHERE location_id = $1
            """, location_id)
            
            return {"message": f"Location '{existing_location['name']}' deleted successfully"}
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete location: {str(e)}"
            )