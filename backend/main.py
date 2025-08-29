from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from routers import auth
from utils.database import init_db_pool, close_db_pool
from middleware.audit_middleware import AuditMiddleware
import sentry_sdk
import os 

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db_pool()
    yield
    # Shutdown
    await close_db_pool()

is_dev = os.getenv('ENVIRONMENT') == 'dev'


sentry_sdk.init(
    dsn=os.getenv('SENTRY_DSN'),
    environment=os.getenv('ENVIRONMENT'),
    send_default_pii=True,
)

app = FastAPI(
    title="REALIZE Healthcare Management API",
    description="API for healthcare management system with user authentication.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if is_dev else None,
    redoc_url="/redoc" if is_dev else None,
    openapi_url="/openapi.json" if is_dev else None
)


enable_audit = os.getenv('ENABLE_AUDIT_LOGGING', 'false').lower() == 'true'
app.add_middleware(AuditMiddleware, enable_audit=enable_audit)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS").split(",") + ["http://localhost:8000"],   
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
from routers import patient_management, locations, data_import, engagement


#app.include_router(user_management.router)
app.include_router(patient_management.router)
app.include_router(locations.router)
app.include_router(data_import.router)
app.include_router(engagement.router)
#app.include_router(audit.router)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/sentry-debug")
async def trigger_error():
    division_by_zero = 1 / 0