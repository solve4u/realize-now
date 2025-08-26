from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from datetime import date
import uuid

from models.patient import (
    PatientResponse, PatientAssignmentOverview, PatientCurrentWeekRisk,
    PatientAssignmentRequest, BulkPatientAssignmentRequest, AssignmentResponse,
    ProgramResponse, ProgramCreate, ProgramUpdate, RiskTierResponse, RiskTierCreate,
    WeeklyCalculationRequest, WeeklyCalculationResponse, PatientWeeklyMetrics,
    PatientCreate, PatientUpdate, AssignmentStatus, ComplianceStatus
)
from models.user import UserResponse, UserRole
from utils.database import get_db_connection
from utils.dependencies import get_current_user, get_admin_user, get_system_admin

router = APIRouter(prefix="/patients", tags=["Patient Management"])


@router.post("/", response_model=PatientResponse)
async def create_patient(
    patient_data: PatientCreate,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Create a new patient."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        try:
            # Determine organization_id based on user role
            if current_user.role == UserRole.SYSTEM_ADMIN:
                if not patient_data.organization_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Organization ID required for system admin"
                    )
                org_id = patient_data.organization_id
            else:
                # Organization admin can only create in their org
                org_id = current_user.organization_id
                if not org_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="User must belong to an organization"
                    )

            # Validate program and location if provided
            if patient_data.program_id:
                program = await conn.fetchrow("""
                    SELECT program_id, organization_id FROM programs 
                    WHERE program_id = $1 AND status = 'active'
                """, patient_data.program_id)
                
                if not program or program['organization_id'] != org_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid program for this organization"
                    )

            if patient_data.location_id:
                location = await conn.fetchrow("""
                    SELECT location_id, organization_id FROM locations 
                    WHERE location_id = $1
                """, patient_data.location_id)
                
                if not location or location['organization_id'] != org_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid location for this organization"
                    )

            # Determine assignment status
            assignment_status = "assigned" if (patient_data.program_id and patient_data.location_id) else "pending"

            # Create the patient
            patient_id = await conn.fetchval("""
                INSERT INTO patients (
                    organization_id, mr, full_name, phone, email, admission_date, 
                    discharge_date, program_id, location_id, assignment_status, status
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING patient_id
            """, org_id, patient_data.mr, patient_data.full_name, patient_data.phone,
                patient_data.email, patient_data.admission_date, patient_data.discharge_date,
                patient_data.program_id, patient_data.location_id, assignment_status, patient_data.status)

            # Get the created patient
            new_patient = await conn.fetchrow("""
                SELECT * FROM patients WHERE patient_id = $1
            """, patient_id)

            return PatientResponse(**dict(new_patient))

        except HTTPException:
            raise
        except Exception as e:
            if "patients_mr_org_unique" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="MRN already exists in this organization"
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create patient: {str(e)}"
            )


@router.put("/{patient_id}", response_model=PatientResponse)
async def update_patient(
    patient_id: uuid.UUID,
    patient_update: PatientUpdate,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Update an existing patient."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        try:
            # Check if patient exists and get current data
            current_patient = await conn.fetchrow("""
                SELECT * FROM patients WHERE patient_id = $1
            """, patient_id)
            
            if not current_patient:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Patient not found or access denied"
                )

            # Validate program and location if being updated
            if patient_update.program_id:
                program = await conn.fetchrow("""
                    SELECT program_id, organization_id FROM programs 
                    WHERE program_id = $1 AND status = 'active'
                """, patient_update.program_id)
                
                if not program or program['organization_id'] != current_patient['organization_id']:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid program for this organization"
                    )

            if patient_update.location_id:
                location = await conn.fetchrow("""
                    SELECT location_id, organization_id FROM locations 
                    WHERE location_id = $1
                """, patient_update.location_id)
                
                if not location or location['organization_id'] != current_patient['organization_id']:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid location for this organization"
                    )

            # Build update query dynamically for non-None fields
            update_fields = []
            update_values = []
            param_count = 1

            for field, value in patient_update.model_dump(exclude_unset=True).items():
                if value is not None:
                    update_fields.append(f"{field} = ${param_count}")
                    update_values.append(value)
                    param_count += 1

            if not update_fields:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No fields to update"
                )

            # Determine new assignment status if program or location changed
            new_program_id = patient_update.program_id if patient_update.program_id is not None else current_patient['program_id']
            new_location_id = patient_update.location_id if patient_update.location_id is not None else current_patient['location_id']
            
            if new_program_id and new_location_id:
                assignment_status = "assigned"
            else:
                assignment_status = "pending"
            
            # Add assignment status to update if it changed
            if assignment_status != current_patient['assignment_status']:
                update_fields.append(f"assignment_status = ${param_count}")
                update_values.append(assignment_status)
                param_count += 1

            # Add updated_at
            update_fields.append(f"updated_at = NOW()")
            
            # Add patient_id for WHERE clause
            update_values.append(patient_id)

            update_query = f"""
                UPDATE patients 
                SET {', '.join(update_fields)}
                WHERE patient_id = ${param_count}
                RETURNING *
            """

            updated_patient = await conn.fetchrow(update_query, *update_values)
            
            return PatientResponse(**dict(updated_patient))

        except HTTPException:
            raise
        except Exception as e:
            if "patients_mr_org_unique" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="MRN already exists in this organization"
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update patient: {str(e)}"
            )

@router.delete("/{patient_id}")
async def delete_patient(
    patient_id: uuid.UUID,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Delete a patient (soft delete by setting status to 'deleted')."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # Check if patient exists
        patient = await conn.fetchrow("""
            SELECT patient_id, full_name FROM patients WHERE patient_id = $1
        """, patient_id)
        
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found or access denied"
            )

        # Soft delete
        await conn.execute("""
            UPDATE patients 
            SET status = 'deleted', updated_at = NOW()
            WHERE patient_id = $1
        """, patient_id)

        return {"message": f"Patient {patient['full_name']} has been deleted successfully"}

# PATIENT ASSIGNMENT ENDPOINTS

@router.get("/unassigned", response_model=List[PatientAssignmentOverview])
async def get_unassigned_patients(
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get patients that need program/location assignment."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        patients = await conn.fetch("""
            SELECT * FROM patient_dashboard_enhanced 
            WHERE assignment_status = 'pending'
            ORDER BY created_at DESC
        """)
        
        return [PatientAssignmentOverview(**dict(patient)) for patient in patients]

@router.get("/assigned", response_model=List[PatientAssignmentOverview])
async def get_assigned_patients(
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get patients that have been assigned to programs/locations."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        patients = await conn.fetch("""
            SELECT * FROM patient_dashboard_enhanced 
            WHERE assignment_status = 'assigned'
            ORDER BY created_at DESC
        """)
        
        return [PatientAssignmentOverview(**dict(patient)) for patient in patients]

@router.get("/all", response_model=List[PatientAssignmentOverview])
async def get_all_patients(
    assignment_status: Optional[AssignmentStatus] = Query(None, description="Filter by assignment status"),
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get all patients with enhanced engagement metrics and service statistics."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        if assignment_status:
            patients = await conn.fetch("""
                SELECT * FROM patient_dashboard_enhanced 
                WHERE assignment_status = $1
                ORDER BY created_at DESC
            """, assignment_status.value)
        else:
            patients = await conn.fetch("""
                SELECT * FROM patient_dashboard_enhanced 
                ORDER BY assignment_status DESC, created_at DESC
            """)
        
        return [PatientAssignmentOverview(**dict(patient)) for patient in patients]

@router.post("/assign", response_model=AssignmentResponse)
async def assign_patient(
    assignment: PatientAssignmentRequest,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Assign a single patient to a program and location."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        try:
            # Verify patient exists and user has access (RLS will handle this)
            patient = await conn.fetchrow("""
                SELECT patient_id, organization_id, full_name 
                FROM patients 
                WHERE patient_id = $1
            """, assignment.patient_id)
            
            if not patient:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Patient not found or access denied"
                )
            
            # Verify program and location belong to same organization
            program = await conn.fetchrow("""
                SELECT program_id, organization_id, name 
                FROM programs 
                WHERE program_id = $1 AND status = 'active'
            """, assignment.program_id)
            
            location = await conn.fetchrow("""
                SELECT location_id, organization_id, name 
                FROM locations 
                WHERE location_id = $1
            """, assignment.location_id)
            
            if not program or not location:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Program or location not found"
                )
            
            if program['organization_id'] != patient['organization_id'] or location['organization_id'] != patient['organization_id']:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Program and location must belong to the same organization as the patient"
                )
            
            # Update patient assignment
            await conn.execute("""
                UPDATE patients 
                SET program_id = $1, location_id = $2, assignment_status = 'assigned', updated_at = NOW()
                WHERE patient_id = $3
            """, assignment.program_id, assignment.location_id, assignment.patient_id)
            
            return AssignmentResponse(
                success=True,
                message=f"Successfully assigned {patient['full_name']} to {program['name']} at {location['name']}",
                assigned_count=1
            )
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to assign patient: {str(e)}"
            )

@router.post("/assign-bulk", response_model=AssignmentResponse)
async def assign_patients_bulk(
    bulk_assignment: BulkPatientAssignmentRequest,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Assign multiple patients to programs and locations."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        assigned_count = 0
        failed_assignments = []
        
        for assignment in bulk_assignment.assignments:
            try:
                # Verify patient, program, and location
                patient = await conn.fetchrow("""
                    SELECT patient_id, organization_id, full_name 
                    FROM patients 
                    WHERE patient_id = $1
                """, assignment.patient_id)
                
                if not patient:
                    failed_assignments.append({
                        "patient_id": str(assignment.patient_id),
                        "error": "Patient not found or access denied"
                    })
                    continue
                
                program = await conn.fetchrow("""
                    SELECT program_id, organization_id, name 
                    FROM programs 
                    WHERE program_id = $1 AND status = 'active'
                """, assignment.program_id)
                
                location = await conn.fetchrow("""
                    SELECT location_id, organization_id, name 
                    FROM locations 
                    WHERE location_id = $1
                """, assignment.location_id)
                
                if not program or not location:
                    failed_assignments.append({
                        "patient_id": str(assignment.patient_id),
                        "error": "Program or location not found"
                    })
                    continue
                
                if (program['organization_id'] != patient['organization_id'] or 
                    location['organization_id'] != patient['organization_id']):
                    failed_assignments.append({
                        "patient_id": str(assignment.patient_id),
                        "error": "Program and location must belong to same organization"
                    })
                    continue
                
                # Update patient assignment
                await conn.execute("""
                    UPDATE patients 
                    SET program_id = $1, location_id = $2, assignment_status = 'assigned', updated_at = NOW()
                    WHERE patient_id = $3
                """, assignment.program_id, assignment.location_id, assignment.patient_id)
                
                assigned_count += 1
                
            except Exception as e:
                failed_assignments.append({
                    "patient_id": str(assignment.patient_id),
                    "error": str(e)
                })
        
        return AssignmentResponse(
            success=assigned_count > 0,
            message=f"Successfully assigned {assigned_count} patients. {len(failed_assignments)} failed.",
            assigned_count=assigned_count,
            failed_assignments=failed_assignments if failed_assignments else None
        )

# RISK CALCULATION ENDPOINTS

@router.get("/risk/current-week", response_model=List[PatientCurrentWeekRisk])
async def get_current_week_risk(
    compliance_status: Optional[ComplianceStatus] = Query(None, description="Filter by compliance status"),
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get real-time risk levels for the current week."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        if compliance_status:
            risk_data = await conn.fetch("""
                SELECT * FROM patient_current_week_risk_with_tiers 
                WHERE compliance_status = $1
                ORDER BY risk_score DESC, full_name ASC
            """, compliance_status.value)
        else:
            risk_data = await conn.fetch("""
                SELECT * FROM patient_current_week_risk_with_tiers 
                ORDER BY assignment_status DESC, risk_score DESC, full_name ASC
            """)
        
        return [PatientCurrentWeekRisk(**dict(row)) for row in risk_data]

@router.get("/risk/week/{week_start_date}", response_model=List[PatientWeeklyMetrics])
async def get_weekly_risk(
    week_start_date: date,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get stored risk levels for a specific week."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        metrics = await conn.fetch("""
            SELECT pwm.* 
            FROM patient_weekly_metrics pwm
            JOIN patients p ON pwm.patient_id = p.patient_id
            WHERE pwm.week_start_date = $1
            ORDER BY pwm.risk_score DESC NULLS LAST, p.full_name ASC
        """, week_start_date)
        
        return [PatientWeeklyMetrics(**dict(metric)) for metric in metrics]

@router.get("/risk/{patient_id}/current", response_model=PatientCurrentWeekRisk)
async def get_patient_current_risk(
    patient_id: uuid.UUID,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get current week risk for a specific patient."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        risk_data = await conn.fetchrow("""
            SELECT * FROM patient_current_week_risk_with_tiers 
            WHERE patient_id = $1
        """, patient_id)
        
        if not risk_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found or access denied"
            )
        
        return PatientCurrentWeekRisk(**dict(risk_data))

@router.get("/export/high-risk")
async def export_high_risk_patients(
    current_user: UserResponse = Depends(get_admin_user)
):
    """Export high-risk patients for follow-up."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        export_data = await conn.fetch("""
            SELECT 
                mr, full_name, program_name, location_name,
                hours_attended, hours_remaining_needed, clinic_hours_remaining,
                risk_level, risk_score, compliance_status, recommended_actions,
                phone, email, primary_therapist
            FROM patient_current_week_risk_with_tiers 
            WHERE (
                compliance_status IN ('at_risk', 'non_compliant') 
                OR auto_flag_for_followup = true
                OR assignment_status = 'pending'
            )
            ORDER BY risk_score DESC, full_name ASC
        """)
        
        return [dict(row) for row in export_data]

# WEEKLY CALCULATION ENDPOINTS

@router.post("/calculate-weekly-metrics", response_model=WeeklyCalculationResponse)
async def calculate_weekly_metrics(
    request: WeeklyCalculationRequest,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Calculate weekly metrics for patients (typically run after week ends)."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        try:
            # Use user's org if not system admin, otherwise use requested org
            target_org_id = request.organization_id if current_user.role == UserRole.SYSTEM_ADMIN else current_user.organization_id
            
            if not target_org_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Organization ID required"
                )
            
            # Calculate metrics for the specified week
            result = await conn.fetchrow("""
                SELECT * FROM calculate_weekly_metrics_for_organization($1, $2)
            """, target_org_id, request.week_start_date)
            
            return WeeklyCalculationResponse(
                success=True,
                message=f"Calculated metrics for {result['calculated_count']} patients",
                calculated_count=result['calculated_count'],
                skipped_count=result['skipped_count'],
                error_count=result['error_count'],
                week_calculated=result['week_calculated']
            )
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to calculate weekly metrics: {str(e)}"
            )

# PROGRAM ENDPOINTS

@router.get("/programs", response_model=List[ProgramResponse])
async def get_programs(
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get programs for assignment dropdown."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # System admin sees all programs, organization admin sees only their organization's programs
        if current_user.role == UserRole.SYSTEM_ADMIN:
            programs = await conn.fetch("""
                SELECT * FROM programs 
                WHERE status = 'active'
                ORDER BY name
            """)
        else:
            # Organization admin - filter by their organization
            if not current_user.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User must belong to an organization"
                )
            
            programs = await conn.fetch("""
                SELECT * FROM programs 
                WHERE status = 'active' AND organization_id = $1
                ORDER BY name
            """, current_user.organization_id)
        
        return [ProgramResponse(**dict(program)) for program in programs]

@router.post("/programs", response_model=ProgramResponse)
async def create_program(
    program: ProgramCreate,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Create a new program."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # Organization admin can only create programs in their org
        if current_user.role == UserRole.ORGANIZATION_ADMIN:
            program.organization_id = current_user.organization_id
        
        try:
            program_id = await conn.fetchval("""
                INSERT INTO programs (organization_id, name, description, level_of_care, hours_per_week)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING program_id
            """, program.organization_id, program.name, program.description, 
                program.level_of_care, program.hours_per_week)
            
            # Get the created program
            new_program = await conn.fetchrow("""
                SELECT * FROM programs WHERE program_id = $1
            """, program_id)
            
            return ProgramResponse(**dict(new_program))
            
        except Exception as e:
            if "programs_name_org_unique" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Program name already exists in this organization"
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create program: {str(e)}"
            )

@router.put("/programs/{program_id}", response_model=ProgramResponse)
async def update_program(
    program_id: uuid.UUID,
    program_update: ProgramUpdate,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Update an existing program."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        try:
            # Check if program exists and get current data
            current_program = await conn.fetchrow("""
                SELECT * FROM programs WHERE program_id = $1
            """, program_id)
            
            if not current_program:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Program not found or access denied"
                )

            # Build update query dynamically for non-None fields
            update_fields = []
            update_values = []
            param_count = 1

            for field, value in program_update.model_dump(exclude_unset=True).items():
                if value is not None:
                    update_fields.append(f"{field} = ${param_count}")
                    update_values.append(value)
                    param_count += 1

            if not update_fields:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No fields to update"
                )

            # Add updated_at
            update_fields.append(f"updated_at = NOW()")
            
            # Add program_id for WHERE clause
            update_values.append(program_id)

            update_query = f"""
                UPDATE programs 
                SET {', '.join(update_fields)}
                WHERE program_id = ${param_count}
                RETURNING *
            """

            updated_program = await conn.fetchrow(update_query, *update_values)
            
            return ProgramResponse(**dict(updated_program))

        except HTTPException:
            raise
        except Exception as e:
            if "programs_name_org_unique" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Program name already exists in this organization"
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update program: {str(e)}"
            )

@router.delete("/programs/{program_id}")
async def delete_program(
    program_id: uuid.UUID,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Delete a program (soft delete by setting status to 'inactive')."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # Check if program exists and user has access
        if current_user.role == UserRole.SYSTEM_ADMIN:
            program = await conn.fetchrow("""
                SELECT program_id, name FROM programs WHERE program_id = $1
            """, program_id)
        else:
            program = await conn.fetchrow("""
                SELECT program_id, name FROM programs 
                WHERE program_id = $1 AND organization_id = $2
            """, program_id, current_user.organization_id)
        
        if not program:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Program not found or access denied"
            )

        # Check if any patients are assigned to this program
        patient_count = await conn.fetchval("""
            SELECT COUNT(*) FROM patients 
            WHERE program_id = $1 AND status != 'deleted'
        """, program_id)

        if patient_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete program: {patient_count} patients are currently assigned to this program"
            )

        # Soft delete - set to inactive since 'deleted' is not allowed by constraint
        await conn.execute("""
            UPDATE programs 
            SET status = 'inactive', updated_at = NOW()
            WHERE program_id = $1
        """, program_id)

        return {"message": f"Program '{program['name']}' has been deleted successfully"}

@router.get("/programs/{program_id}/patient-count")
async def get_program_patient_count(
    program_id: uuid.UUID,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get the count of patients assigned to a specific program."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # Check if program exists and user has access
        if current_user.role == UserRole.SYSTEM_ADMIN:
            program = await conn.fetchrow("""
                SELECT program_id, name FROM programs WHERE program_id = $1
            """, program_id)
        else:
            program = await conn.fetchrow("""
                SELECT program_id, name FROM programs 
                WHERE program_id = $1 AND organization_id = $2
            """, program_id, current_user.organization_id)
        
        if not program:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Program not found or access denied"
            )

        # Get patient count
        patient_count = await conn.fetchval("""
            SELECT COUNT(*) FROM patients 
            WHERE program_id = $1 AND status != 'deleted'
        """, program_id)

        return {"patient_count": patient_count}


# RISK TIER ENDPOINTS

@router.get("/risk-tiers", response_model=List[RiskTierResponse])
async def get_risk_tiers(
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get risk tiers for the organization."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # System admin sees all risk tiers, organization admin sees only their organization's risk tiers
        if current_user.role == UserRole.SYSTEM_ADMIN:
            tiers = await conn.fetch("""
                SELECT * FROM risk_tiers 
                WHERE status = 'active'
                ORDER BY sort_order, tier_label
            """)
        else:
            # Organization admin - filter by their organization
            if not current_user.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User must belong to an organization"
                )
            
            tiers = await conn.fetch("""
                SELECT * FROM risk_tiers 
                WHERE status = 'active' AND organization_id = $1
                ORDER BY sort_order, tier_label
            """, current_user.organization_id)
        
        return [RiskTierResponse(**dict(tier)) for tier in tiers]

@router.post("/risk-tiers", response_model=RiskTierResponse)
async def create_risk_tier(
    tier: RiskTierCreate,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Create a new risk tier."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        # Organization admin can only create tiers in their org
        if current_user.role == UserRole.ORGANIZATION_ADMIN:
            tier.organization_id = current_user.organization_id
        
        try:
            tier_id = await conn.fetchval("""
                INSERT INTO risk_tiers (
                    organization_id, tier_label, tier_description, recommended_actions,
                    risk_level_range_low, risk_level_range_high, color, sort_order, auto_flag_for_followup
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING tier_id
            """, tier.organization_id, tier.tier_label, tier.tier_description,
                tier.recommended_actions, tier.risk_level_range_low, tier.risk_level_range_high,
                tier.color, tier.sort_order, tier.auto_flag_for_followup)
            
            # Get the created tier
            new_tier = await conn.fetchrow("""
                SELECT * FROM risk_tiers WHERE tier_id = $1
            """, tier_id)
            
            return RiskTierResponse(**dict(new_tier))
            
        except Exception as e:
            if "risk_tiers_label_org_unique" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Risk tier label already exists in this organization"
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create risk tier: {str(e)}"
            )

# =====================================================
# INDIVIDUAL PATIENT ENDPOINT (MUST BE LAST)
# =====================================================

@router.get("/{patient_id}", response_model=PatientResponse)
async def get_patient(
    patient_id: uuid.UUID,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Get a specific patient by ID."""
    async with get_db_connection() as conn:
        # Set RLS context
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", current_user.role.value)
        if current_user.organization_id:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(current_user.organization_id))

        patient = await conn.fetchrow("""
            SELECT * FROM patients WHERE patient_id = $1
        """, patient_id)
        
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found or access denied"
            )
        
        return PatientResponse(**dict(patient))