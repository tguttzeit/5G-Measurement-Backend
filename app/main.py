"""FastAPI application entry point."""

import logging

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import (
    admin,
    auth_router,
    campaigns,
    commands,
    config_schema,
    devices,
    favorite_config_fields,
    gps_fix_test,
    health,
    heartbeat,
    latency,
    latency_map,
    measurements,
    notification_settings,
    runs,
    testing,
)
from app.routers import settings as settings_router

# Uvicorn's own default logging config only sets up its "uvicorn"/"uvicorn.access"/
# "uvicorn.error" loggers, not the root logger - without this, a plain `logging.getLogger(name)`
# in application code (e.g. app/routers/heartbeat.py's command-ack logging) is silently dropped
# by Python's logging.lastResort handler (WARNING+ only), never reaching `docker logs`.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()

app = FastAPI(
    title="5GM Backend API",
    description=(
        "Backend API for 5GM device measurement data. All paths are served under `/api`.\n\n"
        "Dashboard endpoints authenticate with a bearer token from `POST /auth/login`: "
        "`Authorization: Bearer <token>`. Endpoints marked as device endpoints authenticate "
        "with the device's `X-Device-ID` and `X-Device-Key` headers instead. Public endpoints "
        "need no authentication. Where a description says superuser, a regular account gets "
        "403."
    ),
    version="0.1.0",
    # The API reference is built from app.openapi() into the documentation site; the built-in
    # Swagger UI, ReDoc and schema endpoints are not served.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Configure CORS for development (frontend on different port)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_error_without_input(request: Request, exc: RequestValidationError):
    """422s name the field and the violated constraint, never the submitted value."""
    errors = [{k: v for k, v in error.items() if k != "input"} for error in exc.errors()]
    return await request_validation_exception_handler(request, RequestValidationError(errors))


app.include_router(health.router)
app.include_router(heartbeat.router)
app.include_router(measurements.router)
app.include_router(measurements.public_router)
app.include_router(measurements.authenticated_router)
app.include_router(latency.router)
app.include_router(latency_map.public_router)
app.include_router(latency_map.authenticated_router)
app.include_router(runs.router)
app.include_router(auth_router, prefix="/auth")
app.include_router(testing.router)
app.include_router(admin.router)
app.include_router(campaigns.router)
app.include_router(settings_router.router)
app.include_router(notification_settings.router)
app.include_router(commands.router)
app.include_router(commands.stream_router)
app.include_router(config_schema.router)
app.include_router(favorite_config_fields.router)
app.include_router(devices.router)
app.include_router(gps_fix_test.router)
