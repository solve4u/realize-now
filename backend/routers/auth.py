from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from datetime import timedelta
import uuid

from models.user import (
    UserCreate, UserResponse, UserLogin, Token, 
    ForgotPasswordRequest, Organization, UserRole
)
from utils.auth import verify_password, get_password_hash, create_access_token
from utils.database import get_db_connection
from utils.dependencies import get_current_user, get_system_admin, get_organization_admin, get_admin_user

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/login", response_model=Token)
async def login(user_credentials: UserLogin):
    """Login endpoint for all users."""
    async with get_db_connection() as conn:
        # Get user by email (including inactive users for proper error handling)
        user_data = await conn.fetchrow("""
            SELECT user_id, username, email, password_hash, role, organization_id, 
                   location_id, is_active, created_at, updated_at, last_login
            FROM users 
            WHERE email = $1
        """, user_credentials.email)
        
        if not user_data or not verify_password(user_credentials.password, user_data['password_hash']):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password"
            )
        
        if not user_data['is_active']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account has been deactivated. Please contact your administrator for assistance."
            )
        
        await conn.execute("""
            UPDATE users SET last_login = NOW() WHERE user_id = $1
        """, user_data['user_id'])
        
        access_token = create_access_token(
            data={"sub": user_data['email']},
            expires_delta=timedelta(minutes=30)
        )
        
        user_response_data = {k: v for k, v in user_data.items() if k != 'password_hash'}
        user_response = UserResponse(**user_response_data)
        
        return Token(access_token=access_token, user=user_response)

@router.post("/create-user", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    current_user: UserResponse = Depends(get_admin_user)
):
    """Create a new user. System admins can create any role, org admins can only create users in their org."""
    
    # Validate role permissions
    if current_user.role == UserRole.SYSTEM_ADMIN:
        # System admin can create system_admin, organization_admin, or user
        if user_data.role == UserRole.SYSTEM_ADMIN and user_data.organization_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="System admin cannot have organization_id"
            )
        elif user_data.role in [UserRole.ORGANIZATION_ADMIN, UserRole.USER] and user_data.organization_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Organization admin and user must have organization_id"
            )
    
    elif current_user.role == UserRole.ORGANIZATION_ADMIN:
        # Organization admin can only create users in their own organization
        if user_data.role == UserRole.SYSTEM_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization admin cannot create system admin"
            )
        
        if user_data.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization admin can only create users in their own organization"
            )
        
        # Force organization_id to be the same as current user's
        user_data.organization_id = current_user.organization_id
    
    async with get_db_connection() as conn:
        # Check if email already exists
        existing_user = await conn.fetchrow("SELECT email FROM users WHERE email = $1", user_data.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        
        # Check if username already exists
        existing_username = await conn.fetchrow("SELECT username FROM users WHERE username = $1", user_data.username)
        if existing_username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken"
            )
        
        # Validate organization exists if provided
        if user_data.organization_id:
            existing_org = await conn.fetchrow("""
                SELECT organization_id FROM organizations 
                WHERE organization_id = $1 AND status = 'active'
            """, str(user_data.organization_id))
            if not existing_org:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid organization_id"
                )
        
        # Hash password
        hashed_password = get_password_hash(user_data.password)
        
        # Generate user ID
        user_id = str(uuid.uuid4())
        
        # Insert new user
        await conn.execute("""
            INSERT INTO users (user_id, username, email, password_hash, role, organization_id, location_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, 
            user_id,
            user_data.username,
            user_data.email,
            hashed_password,
            user_data.role.value,
            user_data.organization_id,
            user_data.location_id
        )
        
        # Get the created user
        new_user = await conn.fetchrow("""
            SELECT user_id, username, email, role, organization_id, location_id, 
                   is_active, created_at, updated_at, last_login
            FROM users 
            WHERE user_id = $1
        """, user_id)
        
        return UserResponse(**dict(new_user))

@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    """Forgot password endpoint - Not Implemented. Need to use an email client. Currently in progress."""
    
    return {"message": "If the email exists, a password reset link will be sent"}

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: UserResponse = Depends(get_current_user)):
    """Get current user information."""
    return current_user

@router.get("/organizations", response_model=List[Organization])
async def get_organizations(current_user: UserResponse = Depends(get_current_user)):
    """Get organizations. System admin sees all, org admin sees only their org."""
    
    async with get_db_connection() as conn:
        if current_user.role == UserRole.SYSTEM_ADMIN:
            # System admin can see all organizations
            organizations = await conn.fetch("""
                SELECT organization_id, name, description, address, phone, email, 
                       website, status, created_at, updated_at
                FROM organizations 
                WHERE status = 'active'
                ORDER BY name
            """)
        else:
            # Other users can only see their organization
            organizations = await conn.fetch("""
                SELECT organization_id, name, description, address, phone, email, 
                       website, status, created_at, updated_at
                FROM organizations 
                WHERE organization_id = $1 AND status = 'active'
            """, str(current_user.organization_id))
        
        return [Organization(**dict(org)) for org in organizations]

@router.get("/users", response_model=List[UserResponse])
async def get_users(current_user: UserResponse = Depends(get_admin_user)):
    """Get users. System admin sees all, org admin sees only users in their org."""
    
    async with get_db_connection() as conn:
        if current_user.role == UserRole.SYSTEM_ADMIN:
            # System admin can see all users
            users = await conn.fetch("""
                SELECT user_id, username, email, role, organization_id, location_id,
                       is_active, created_at, updated_at, last_login
                FROM users 
                ORDER BY created_at DESC
            """)
        else:
            # Organization admin can only see users in their organization
            users = await conn.fetch("""
                SELECT user_id, username, email, role, organization_id, location_id,
                       is_active, created_at, updated_at, last_login
                FROM users 
                WHERE organization_id = $1
                ORDER BY created_at DESC
            """, str(current_user.organization_id))
        
        return [UserResponse(**dict(user)) for user in users]

@router.patch("/users/{user_id}/toggle-status")
async def toggle_user_status(
    user_id: str,
    current_user: UserResponse = Depends(get_system_admin)
):
    """Toggle user active/inactive status. Only system admin can do this."""
    
    async with get_db_connection() as conn:
        # Get current user status
        user_data = await conn.fetchrow("""
            SELECT user_id, is_active, email, role 
            FROM users 
            WHERE user_id = $1
        """, user_id)
        
        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Prevent deactivating system admin
        if user_data['role'] == 'system_admin' and user_data['is_active']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate system admin"
            )
        
        new_status = not user_data['is_active']
        
        await conn.execute("""
            UPDATE users 
            SET is_active = $1, updated_at = NOW() 
            WHERE user_id = $2
        """, new_status, user_id)
        
        # Get updated user
        updated_user = await conn.fetchrow("""
            SELECT user_id, username, email, role, organization_id, location_id,
                   is_active, created_at, updated_at, last_login
            FROM users 
            WHERE user_id = $1
        """, user_id)
        
        return {
            "message": f"User {'activated' if new_status else 'deactivated'} successfully"
        }
