from app.routers import (
    admin,
    campaigns,
    commands,
    devices,
    gps_fix_test,
    health,
    heartbeat,
    latency,
    measurements,
    runs,
    testing,
)
from app.routers.auth import router as auth_router
from app.routers.health import router as health_router

__all__ = [
    "auth_router",
    "health_router",
    "admin",
    "campaigns",
    "commands",
    "devices",
    "gps_fix_test",
    "health",
    "heartbeat",
    "latency",
    "measurements",
    "runs",
    "testing",
]
