from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from .auth import verify_token
from .database import get_db_connection
from models.user import UserResponse, UserRole

security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> UserResponse:
    """Get current authenticated user and set RLS context."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    token = credentials.credentials
    email = verify_token(token)
    
    if email is None:
        raise credentials_exception
    
    async with get_db_connection() as conn:
        user_data = await conn.fetchrow("""
            SELECT user_id, username, email, role, organization_id, location_id, 
                   is_active, created_at, updated_at, last_login
            FROM users 
            WHERE email = $1 AND is_active = true
        """, email)
        
        if user_data is None:
            raise credentials_exception
        
        # Set RLS context variables for Row Level Security
        await conn.execute("SELECT set_config('app.current_user_role', $1, true)", user_data['role'])
        if user_data['organization_id']:
            await conn.execute("SELECT set_config('app.current_user_org_id', $1, true)", str(user_data['organization_id']))
        else:
            await conn.execute("SELECT set_config('app.current_user_org_id', '', true)")
        
        return UserResponse(**dict(user_data))

async def get_system_admin(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    """Dependency to ensure user is system admin."""
    if current_user.role != UserRole.SYSTEM_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System admin access required"
        )
    return current_user

async def get_organization_admin(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    """Dependency to ensure user is organization admin."""
    if current_user.role != UserRole.ORGANIZATION_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization admin access required"
        )
    return current_user

async def get_admin_user(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    """Dependency to ensure user is either system admin or organization admin."""
    if current_user.role not in [UserRole.SYSTEM_ADMIN, UserRole.ORGANIZATION_ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user
