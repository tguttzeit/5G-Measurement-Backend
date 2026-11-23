from fastapi import APIRouter

router = APIRouter()


@router.get(
    "/health",
    summary="Liveness check",
    description=(
        "Answers `{\"status\": \"ok\"}` while the application is running. Public; it does not "
        "check the database."
    ),
)
def health() -> dict[str, str]:
    return {"status": "ok"}
