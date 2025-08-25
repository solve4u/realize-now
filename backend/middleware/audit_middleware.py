import time
import hashlib
import json
import uuid
from typing import Optional, Dict, Any
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse
import os
from utils.database import get_db_connection
from models.audit import AuditActionType, AuditResourceType
from utils.auth import verify_token

class AuditMiddleware(BaseHTTPMiddleware):
    """
    HIPAA Compliant Audit Middleware
    Only runs in production environment to avoid corrupting dev/test data
    """
    
    def __init__(self, app, enable_audit: bool = None):
        super().__init__(app)
        # Only enable in production unless explicitly overridden
        self.enabled = enable_audit if enable_audit is not None else (os.getenv('ENVIRONMENT') == 'production')
        
        # Endpoints that should not be audited (health checks, static files, etc.)
        self.excluded_paths = {
            '/health',
            '/docs',
            '/redoc',
            '/openapi.json',
            '/favicon.ico',
            '/static',
        }
        
        # PHI endpoints - these access Protected Health Information
        self.phi_endpoints = {
            '/patients',
            '/engagement',
            '/risk'
        }
        
        # Export endpoints - these allow data download
        self.export_endpoints = {
            '/export',
            '/download'
        }

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip audit logging if disabled or excluded path
        if not self.enabled or self._should_exclude_path(request.url.path):
            return await call_next(request)
        
        # Start timing
        start_time = time.time()
        
        # Generate session ID for this request
        session_id = str(uuid.uuid4())
        
        # Extract user information from token
        user_info = await self._extract_user_info(request)
        
        # Get client IP
        client_ip = self._get_client_ip(request)
        
        # Process the request first
        response = await call_next(request)
        
        # Hash request body for integrity (if present) - do this after processing
        request_body_hash = None  # Disable for now to prevent body consumption issues
        
        # Calculate response time
        response_time_ms = (time.time() - start_time) * 1000
        
        # Determine audit classification
        action_type, resource_type, resource_id = self._classify_request(request, response)
        
        # Check if PHI was accessed
        phi_accessed = self._is_phi_endpoint(request.url.path)
        
        # Check if data was exported
        data_exported = self._is_export_endpoint(request.url.path) and response.status_code == 200
        
        # Extract patient ID if applicable
        patient_id = self._extract_patient_id(request, user_info)
        
        # Log the audit entry asynchronously
        await self._log_audit_entry(
            user_info=user_info,
            session_id=session_id,
            request=request,
            response=response,
            client_ip=client_ip,
            response_time_ms=response_time_ms,
            action_type=action_type,
            resource_type=resource_type,
            resource_id=resource_id,
            phi_accessed=phi_accessed,
            data_exported=data_exported,
            patient_id=patient_id,
            request_body_hash=request_body_hash
        )
        
        return response

    def _should_exclude_path(self, path: str) -> bool:
        """Check if path should be excluded from audit logging"""
        return any(path.startswith(excluded) for excluded in self.excluded_paths)

    async def _extract_user_info(self, request: Request) -> Dict[str, Any]:
        """Extract user information from JWT token"""
        user_info = {
            'user_id': None,
            'user_email': None,
            'user_role': None,
            'organization_id': None
        }
        
        try:
            # Get Authorization header
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
                email = verify_token(token)
                
                if email:
                    # Get user details from database
                    async with get_db_connection() as conn:
                        user_data = await conn.fetchrow("""
                            SELECT user_id, email, role, organization_id
                            FROM users 
                            WHERE email = $1 AND is_active = true
                        """, email)
                        
                        if user_data:
                            user_info.update({
                                'user_id': user_data['user_id'],
                                'user_email': user_data['email'],
                                'user_role': user_data['role'],
                                'organization_id': user_data['organization_id']
                            })
        except Exception:
            # If user extraction fails, continue with anonymous audit
            pass
        
        return user_info

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address, considering proxy headers"""
        # Check for forwarded IP headers (common in production behind load balancers)
        forwarded_for = request.headers.get('X-Forwarded-For')
        if forwarded_for:
            # Take the first IP in the chain
            return forwarded_for.split(',')[0].strip()
        
        real_ip = request.headers.get('X-Real-IP')
        if real_ip:
            return real_ip
        
        # Fallback to direct client IP
        return request.client.host if request.client else '127.0.0.1'

    async def _hash_request_body(self, request: Request) -> Optional[str]:
        """Create SHA256 hash of request body for integrity verification"""
        try:
            # Only hash for POST, PUT, PATCH requests
            if request.method in ['POST', 'PUT', 'PATCH']:
                body = await request.body()
                if body:
                    return hashlib.sha256(body).hexdigest()
        except Exception:
            pass
        return None

    def _classify_request(self, request: Request, response: Response) -> tuple:
        """Classify the request for audit purposes"""
        method = request.method
        path = request.url.path
        status_code = response.status_code
        
        # Determine action type
        if path.startswith('/auth/login'):
            action_type = AuditActionType.LOGIN
        elif path.startswith('/auth/logout'):
            action_type = AuditActionType.LOGOUT
        elif status_code == 403:
            action_type = AuditActionType.ACCESS_DENIED
        elif '/export' in path or '/download' in path:
            action_type = AuditActionType.EXPORT
        elif method == 'POST':
            action_type = AuditActionType.CREATE
        elif method in ['GET', 'HEAD']:
            action_type = AuditActionType.READ
        elif method in ['PUT', 'PATCH']:
            action_type = AuditActionType.UPDATE
        elif method == 'DELETE':
            action_type = AuditActionType.DELETE
        else:
            action_type = AuditActionType.READ
        
        # Determine resource type and ID
        resource_type = None
        resource_id = None
        
        if '/auth' in path:
            resource_type = AuditResourceType.AUTH
        elif '/patients' in path:
            resource_type = AuditResourceType.PATIENT
            resource_id = self._extract_resource_id(path, 'patients')
        elif '/users' in path:
            resource_type = AuditResourceType.USER
            resource_id = self._extract_resource_id(path, 'users')
        elif '/organizations' in path:
            resource_type = AuditResourceType.ORGANIZATION
            resource_id = self._extract_resource_id(path, 'organizations')
        elif '/locations' in path:
            resource_type = AuditResourceType.LOCATION
            resource_id = self._extract_resource_id(path, 'locations')
        elif '/programs' in path:
            resource_type = AuditResourceType.PROGRAM
            resource_id = self._extract_resource_id(path, 'programs')
        elif '/engagement' in path:
            resource_type = AuditResourceType.ENGAGEMENT
        elif '/risk' in path:
            resource_type = AuditResourceType.WEEKLY_METRICS
        else:
            resource_type = AuditResourceType.SYSTEM
        
        return action_type, resource_type, resource_id

    def _extract_resource_id(self, path: str, resource_name: str) -> Optional[str]:
        """Extract resource ID from URL path"""
        try:
            parts = path.split('/')
            if resource_name in parts:
                idx = parts.index(resource_name)
                if idx + 1 < len(parts) and parts[idx + 1]:
                    # Check if it's a UUID-like string
                    resource_id = parts[idx + 1]
                    if len(resource_id) == 36 and resource_id.count('-') == 4:
                        return resource_id
        except Exception:
            pass
        return None

    def _is_phi_endpoint(self, path: str) -> bool:
        """Check if endpoint accesses Protected Health Information"""
        return any(phi_path in path for phi_path in self.phi_endpoints)

    def _is_export_endpoint(self, path: str) -> bool:
        """Check if endpoint exports/downloads data"""
        return any(export_path in path for export_path in self.export_endpoints)

    def _extract_patient_id(self, request: Request, user_info: Dict[str, Any]) -> Optional[str]:
        """Extract patient ID from request if patient data is being accessed"""
        try:
            path = request.url.path
            
            # Direct patient endpoint
            if '/patients/' in path:
                return self._extract_resource_id(path, 'patients')
            
            # Check query parameters for patient_id
            if 'patient_id' in request.query_params:
                return request.query_params['patient_id']
            
        except Exception:
            pass
        return None

    async def _log_audit_entry(self, **kwargs):
        """Log audit entry to database"""
        try:
            async with get_db_connection() as conn:
                await conn.execute("""
                    INSERT INTO audit_logs (
                        user_id, user_email, user_role, organization_id, session_id,
                        method, endpoint, full_url, user_agent, ip_address,
                        status_code, response_time_ms, action_type, resource_type, resource_id,
                        phi_accessed, patient_id, data_exported, request_body_hash,
                        query_parameters, additional_context
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21
                    )
                """,
                    kwargs['user_info']['user_id'],
                    kwargs['user_info']['user_email'],
                    kwargs['user_info']['user_role'],
                    kwargs['user_info']['organization_id'],
                    kwargs['session_id'],
                    kwargs['request'].method,
                    kwargs['request'].url.path,
                    str(kwargs['request'].url),
                    kwargs['request'].headers.get('User-Agent'),
                    kwargs['client_ip'],
                    kwargs['response'].status_code,
                    kwargs['response_time_ms'],
                    kwargs['action_type'].value,
                    kwargs['resource_type'].value if kwargs['resource_type'] else None,
                    kwargs['resource_id'],
                    kwargs['phi_accessed'],
                    kwargs['patient_id'],
                    kwargs['data_exported'],
                    kwargs['request_body_hash'],
                    json.dumps(dict(kwargs['request'].query_params)) if kwargs['request'].query_params else None,
                    None  
                )
        except Exception as e:
            # Log audit failures to application logs
            print(f"Audit logging failed: {str(e)}")
