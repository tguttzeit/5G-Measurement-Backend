"""Testing data ingestion and retrieval endpoints.

This router provides RESTful endpoints for submitting and retrieving test results
from manual integration testing.

The dashboard-facing endpoints (GET/DELETE/summary) require an authenticated
superuser - these are an admin-only ops tool, not a self-service feature.
POST /results additionally accepts per-device API key auth (X-Device-ID /
X-Device-Key), so an unattended device script can submit its own results without
a superuser JWT. Test data is distinguished from production
data using the is_testing flag.
"""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy import delete as sql_delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import current_superuser, fastapi_users
from app.db import get_db
from app.device_auth import verify_device_auth
from app.models import Device, TestResult, TestStatus, TestType
from app.models.user import User
from app.schemas.testing import (
    ApiResponse,
    FailureBreakdownEntry,
    TestResultCreate,
    TestResultResponse,
    TestResultsListResponse,
    TestResultSummary,
    TestStatusStr,
    TestSummaryResponse,
    TestTypeStr,
)

router = APIRouter(prefix="/testing", tags=["testing"])

# Returns None instead of raising when there's no valid superuser JWT, so it can be
# combined with device-key auth below rather than rejecting the request outright.
_optional_superuser = fastapi_users.current_user(active=True, superuser=True, optional=True)


async def verify_testing_submission_auth(
    x_device_id: str | None = Header(None, alias="X-Device-ID"),
    x_device_key: str | None = Header(None, alias="X-Device-Key"),
    user: User | None = Depends(_optional_superuser),
    db: Session = Depends(get_db),
) -> User | Device:
    """Accept either a superuser JWT or a per-device API key for submitting test results.

    Only POST /testing/results uses this - every other route in this router stays
    behind plain `current_superuser`, since device keys must not extend to the
    dashboard-facing GET/DELETE/summary endpoints.
    """
    if user is not None:
        return user
    return verify_device_auth(x_device_id, x_device_key, db)


def convert_test_type(test_type: TestType | str) -> TestTypeStr:
    """Convert database TestType enum to API TestTypeStr."""
    if isinstance(test_type, TestType):
        return TestTypeStr(test_type.value)
    return TestTypeStr(test_type)


def convert_test_status(status: TestStatus | str) -> TestStatusStr:
    """Convert database TestStatus enum to API TestStatusStr."""
    if isinstance(status, TestStatus):
        return TestStatusStr(status.value)
    return TestStatusStr(status)


@router.post(
    "/results",
    response_model=ApiResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit test result",
    description=(
        "Submits a test result from manual integration testing. `device_id` must be a "
        "registered device (400 otherwise, as for an invalid `test_type` or `status`). "
        "Accepts either a superuser token or that device's own `X-Device-ID` and "
        "`X-Device-Key` headers; with a device key, `device_id` must match the authenticated "
        "device. `executed_at` defaults to now. `is_testing` defaults to `true` and "
        "distinguishes test data from production data: test data does not appear in "
        "production dashboards or analytics, and the read endpoints show only test data "
        "unless `is_testing=false` is passed. `details` holds arbitrary key-value pairs. "
        "`test_type` is one of `modem`, `gps`, `collector`, `uploader`, `heartbeat`; `status` "
        "is one of `passed`, `failed`, `running`, `skipped`. Answers 201 with `{\"status\": "
        "\"ok\", \"message\": ...}` naming the new id; 401 without valid credentials, 403 for a "
        "valid non-superuser token."
    ),
)
async def submit_test_result(
    payload: TestResultCreate,
    db: Session = Depends(get_db),
    submitter: User | Device = Depends(verify_testing_submission_auth),
) -> ApiResponse:
    """Submit a new test result."""
    if isinstance(submitter, Device) and payload.device_id != submitter.device_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"payload device_id '{payload.device_id}' does not match "
                f"authenticated device '{submitter.device_id}'"
            ),
        )

    # Convert enum strings to database enums
    try:
        db_test_type = TestType(payload.test_type.value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid test_type: {payload.test_type}. "
                f"Must be one of: {[t.value for t in TestType]}"
            ),
        )
    
    try:
        db_test_status = TestStatus(payload.status.value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid status: {payload.status}. "
                f"Must be one of: {[s.value for s in TestStatus]}"
            ),
        )

    # Create test result record
    test_result = TestResult(
        device_id=payload.device_id,
        test_type=db_test_type,
        status=db_test_status,
        executed_at=payload.executed_at or datetime.now(UTC),
        is_testing=payload.is_testing,
        duration_ms=payload.duration_ms,
        error_message=payload.error_message,
        details=payload.details,
    )

    db.add(test_result)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"device_id '{payload.device_id}' is not a registered device",
        )
    db.refresh(test_result)

    return ApiResponse(
        status="ok",
        message=f"Test result submitted successfully with ID: {test_result.id}"
    )


@router.get(
    "/results",
    response_model=TestResultsListResponse,
    summary="Get test results",
    description=(
        "Superuser only. A paginated list of test results, newest first, filtered by "
        "`test_type`, `status`, `device_id`, the `is_testing` flag and a date range. Without "
        "`is_testing` only test data is returned, so production records need "
        "`is_testing=false`. `start_date` is inclusive and `end_date` includes the whole day "
        "it falls on. `page` starts at 1 and `page_size` is 1 to 1000 (default 50). Each "
        "listed result has `id`, `device_id`, `test_type`, `status`, `executed_at`, "
        "`is_testing`, `duration_ms` and `error_message`; `details` is only in the single "
        "result. 401 without a valid token, 403 for a non-superuser."
    ),
)
async def get_test_results(
    test_type: TestTypeStr | None = Query(None, description="Filter by test type"),
    status_filter: TestStatusStr | None = Query(
        None, alias="status", description="Filter by test status"
    ),
    device_id: str | None = Query(None, description="Filter by device ID"),
    is_testing: bool | None = Query(
        None, description="Filter by testing flag; test data only when omitted"
    ),
    start_date: datetime | None = Query(None, description="Only results executed at or after this"),
    end_date: datetime | None = Query(
        None, description="Only results executed up to the end of this day"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=1000, description="Results per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(current_superuser),
) -> TestResultsListResponse:
    """Get a paginated list of test results with optional filtering."""
    # Build filter conditions
    conditions = []
    
    if test_type:
        conditions.append(TestResult.test_type == TestType(test_type.value))
    
    if status_filter:
        conditions.append(TestResult.status == TestStatus(status_filter.value))
    
    if device_id:
        conditions.append(TestResult.device_id == device_id)
    
    if is_testing is not None:
        conditions.append(TestResult.is_testing == is_testing)
    
    if start_date:
        conditions.append(TestResult.executed_at >= start_date)
    
    if end_date:
        # Include the entire end_date day
        end_of_day = datetime(
            end_date.year, end_date.month, end_date.day, 
            23, 59, 59, 999999, tzinfo=end_date.tzinfo or UTC
        )
        conditions.append(TestResult.executed_at <= end_of_day)
    
    # Default: only show testing data (is_testing=True) unless explicitly filtered
    # This ensures test data is separated from production data by default
    if is_testing is None:
        conditions.append(TestResult.is_testing)

    # Build query
    query = select(TestResult).where(and_(*conditions))
    
    # Get total count for pagination
    total_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(total_query)
    
    # Apply pagination
    offset = (page - 1) * page_size
    query = query.order_by(TestResult.executed_at.desc()).offset(offset).limit(page_size)
    
    results = db.scalars(query).all()
    
    # Convert to response format
    summaries = [
        TestResultSummary(
            id=result.id,
            device_id=result.device_id,
            test_type=convert_test_type(result.test_type),
            status=convert_test_status(result.status),
            executed_at=result.executed_at.isoformat() if result.executed_at else "",
            is_testing=result.is_testing,
            duration_ms=result.duration_ms,
            error_message=result.error_message,
        )
        for result in results
    ]

    return TestResultsListResponse(
        results=summaries,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/results/{result_id}",
    response_model=TestResultResponse,
    summary="Get specific test result",
    description=(
        "Superuser only. One test result by id, including `error_message`, `details` and "
        "`created_at`. By default only testing data (`is_testing=true`) is visible; pass "
        "`is_testing=false` to look up a production record. 404 if the id does not exist or "
        "does not match the requested `is_testing` flag; 401 without a valid token, 403 for a "
        "non-superuser."
    ),
)
async def get_test_result(
    result_id: int,
    is_testing: bool = Query(
        True, description="Only return the result if it matches this testing flag"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(current_superuser),
) -> TestResultResponse:
    """Get a specific test result by ID."""
    result = db.get(TestResult, result_id)

    if not result or result.is_testing != is_testing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test result with ID {result_id} not found",
        )

    return TestResultResponse(
        id=result.id,
        device_id=result.device_id,
        test_type=convert_test_type(result.test_type),
        status=convert_test_status(result.status),
        executed_at=result.executed_at.isoformat() if result.executed_at else "",
        is_testing=result.is_testing,
        duration_ms=result.duration_ms,
        error_message=result.error_message,
        details=result.details,
        created_at=result.created_at.isoformat() if result.created_at else "",
    )


@router.get(
    "/summary",
    response_model=TestSummaryResponse,
    summary="Get test summary statistics",
    description=(
        "Superuser only. Summary statistics: `total_tests` and the counts `passed`, `failed`, "
        "`running` and `skipped`; the same counts per test type in `by_test_type`; the most "
        "recent executions in `recent_executions`; and `failures_by_type_and_message`, the "
        "failed results grouped by test type and error message with a `count`. By default "
        "only testing data is included (`is_testing=true`). `start_date` and `end_date` "
        "restrict the period, and `end_date` includes the whole day it falls on. 401 without "
        "a valid token, 403 for a non-superuser."
    ),
)
async def get_test_summary(
    is_testing: bool = Query(True, description="Include only testing data"),
    start_date: datetime | None = Query(None, description="Filter by start date"),
    end_date: datetime | None = Query(None, description="Filter by end date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(current_superuser),
) -> TestSummaryResponse:
    """Get summary statistics for test results."""
    # Build filter conditions
    conditions = [TestResult.is_testing == is_testing]
    
    if start_date:
        conditions.append(TestResult.executed_at >= start_date)
    
    if end_date:
        end_of_day = datetime(
            end_date.year, end_date.month, end_date.day,
            23, 59, 59, 999999, tzinfo=end_date.tzinfo or UTC
        )
        conditions.append(TestResult.executed_at <= end_of_day)

    # Get counts by status
    status_counts = db.query(
        TestResult.status,
        func.count(TestResult.id)
    ).filter(and_(*conditions)).group_by(TestResult.status).all()
    
    # Initialize counts
    counts = {
        TestStatus.PASSED: 0,
        TestStatus.FAILED: 0,
        TestStatus.RUNNING: 0,
        TestStatus.SKIPPED: 0,
    }
    
    for status_value, count in status_counts:
        counts[status_value] = count
    
    # Get counts by test type
    type_counts = db.query(
        TestResult.test_type,
        TestResult.status,
        func.count(TestResult.id)
    ).filter(and_(*conditions)).group_by(TestResult.test_type, TestResult.status).all()
    
    by_test_type: dict[TestTypeStr, dict[str, int]] = {}
    for test_type, status_value, count in type_counts:
        type_key = TestTypeStr(test_type.value)
        status_key = TestStatusStr(status_value.value)
        
        if type_key not in by_test_type:
            by_test_type[type_key] = {
                "passed": 0,
                "failed": 0,
                "running": 0,
                "skipped": 0,
                "total": 0,
            }
        
        by_test_type[type_key][status_key.value] = count
        by_test_type[type_key]["total"] += count
    
    # Get recent executions (last 10)
    recent_query = (
        select(TestResult)
        .where(and_(*conditions))
        .order_by(TestResult.executed_at.desc())
        .limit(10)
    )
    recent = db.scalars(recent_query).all()
    
    recent_executions = [
        {
            "id": r.id,
            "device_id": r.device_id,
            "test_type": convert_test_type(r.test_type).value,
            "status": convert_test_status(r.status).value,
            "executed_at": r.executed_at.isoformat() if r.executed_at else "",
            "duration_ms": r.duration_ms,
            "error_message": r.error_message,
        }
        for r in recent
    ]

    # Breakdown of failures by exact (test_type, error_message) match, so multiple
    # failures sharing the same recorded error surface together instead of only as
    # a single "failed" count. Deliberately exact-string matching,
    # not fuzzy root-cause clustering across differently-worded messages.
    failure_conditions = [*conditions, TestResult.status == TestStatus.FAILED]
    failure_counts = (
        db.query(
            TestResult.test_type,
            TestResult.error_message,
            func.count(TestResult.id),
        )
        .filter(and_(*failure_conditions))
        .group_by(TestResult.test_type, TestResult.error_message)
        .order_by(func.count(TestResult.id).desc())
        .all()
    )

    failures_by_type_and_message = [
        FailureBreakdownEntry(
            test_type=convert_test_type(test_type),
            error_message=error_message,
            count=count,
        )
        for test_type, error_message, count in failure_counts
    ]

    return TestSummaryResponse(
        total_tests=sum(counts.values()),
        passed=counts[TestStatus.PASSED],
        failed=counts[TestStatus.FAILED],
        running=counts[TestStatus.RUNNING],
        skipped=counts[TestStatus.SKIPPED],
        by_test_type=by_test_type,
        recent_executions=recent_executions,
        failures_by_type_and_message=failures_by_type_and_message,
    )


@router.delete(
    "/results/{result_id}",
    response_model=ApiResponse,
    summary="Delete test result",
    description=(
        "Superuser only. Deletes one test result by id. By default only testing data "
        "(`is_testing=true`) can be deleted this way; pass `is_testing=false` to delete a "
        "production record. 404 if the id does not exist or does not match the requested "
        "`is_testing` flag; 401 without a valid token, 403 for a non-superuser."
    ),
)
async def delete_test_result(
    result_id: int,
    is_testing: bool = Query(
        True, description="Only delete the result if it matches this testing flag"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(current_superuser),
) -> ApiResponse:
    """Delete a test result by ID."""
    result = db.get(TestResult, result_id)

    if not result or result.is_testing != is_testing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test result with ID {result_id} not found",
        )

    db.delete(result)
    db.commit()

    return ApiResponse(
        status="ok",
        message=f"Test result with ID {result_id} deleted successfully"
    )


@router.delete(
    "/results",
    response_model=ApiResponse,
    summary="Delete all test results",
    description=(
        "Superuser only. Deletes every test result matching the `is_testing` flag; it "
        "defaults to `true` (all testing data), and `is_testing=false` deletes all "
        "production data instead. It is not scoped to any other filter (test type, status, "
        "device, date range): every row matching the flag is deleted, whatever filter a "
        "client currently shows. This cannot be undone. Answers with the number of deleted "
        "results; 401 without a valid token, 403 for a non-superuser."
    ),
)
async def delete_all_test_results(
    is_testing: bool = Query(
        True, description="Delete every result matching this testing flag"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(current_superuser),
) -> ApiResponse:
    """Delete every test result matching the is_testing flag."""
    result = db.execute(sql_delete(TestResult).where(TestResult.is_testing == is_testing))
    db.commit()

    return ApiResponse(
        status="ok",
        message=f"Deleted {result.rowcount} test result(s)",
    )
