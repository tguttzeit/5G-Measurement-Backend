"""Pydantic schemas for testing data visualization API."""
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TestTypeStr(StrEnum):
    """String enum for test types (for API compatibility)."""
    MODEM = "modem"
    GPS = "gps"
    COLLECTOR = "collector"
    UPLOADER = "uploader"
    HEARTBEAT = "heartbeat"


class TestStatusStr(StrEnum):
    """String enum for test status (for API compatibility)."""
    PASSED = "passed"
    FAILED = "failed"
    RUNNING = "running"
    SKIPPED = "skipped"


class TestResultCreate(BaseModel):
    """Schema for creating a new test result."""
    
    device_id: str = Field(..., description="ID of the device that executed the test")
    test_type: TestTypeStr = Field(..., description="Type of test executed")
    status: TestStatusStr = Field(..., description="Status of the test execution")
    executed_at: datetime | None = Field(
        default=None, 
        description="When the test was executed (defaults to now)"
    )
    is_testing: bool = Field(
        default=True, 
        description="Flag to distinguish test data from production data"
    )
    duration_ms: int | None = Field(
        default=None, 
        description="Duration of the test in milliseconds"
    )
    error_message: str | None = Field(
        default=None, 
        description="Error message if test failed"
    )
    details: dict | None = Field(
        default=None, 
        description="Additional test details as key-value pairs"
    )


class TestResultResponse(BaseModel):
    """Response schema for a single test result."""
    
    id: int = Field(description="Id of the test result")
    device_id: str = Field(description="Device that executed the test")
    test_type: TestTypeStr = Field(description="Type of test executed")
    status: TestStatusStr = Field(description="Status of the test execution")
    executed_at: str = Field(description="When the test was executed")
    is_testing: bool = Field(description="True for test data, false for production data")
    duration_ms: int | None = Field(description="Duration of the test in milliseconds")
    error_message: str | None = Field(description="Error message if the test failed")
    details: dict | None = Field(description="Additional test details as key-value pairs")
    created_at: str = Field(description="When the record was created")


class TestResultSummary(BaseModel):
    """Summary schema for test results (used in listings)."""

    id: int = Field(description="Id of the test result")
    device_id: str = Field(description="Device that executed the test")
    test_type: TestTypeStr = Field(description="Type of test executed")
    status: TestStatusStr = Field(description="Status of the test execution")
    executed_at: str = Field(description="When the test was executed")
    is_testing: bool = Field(description="True for test data, false for production data")
    duration_ms: int | None = Field(description="Duration of the test in milliseconds")
    error_message: str | None = Field(description="Error message if the test failed")


class TestResultsListResponse(BaseModel):
    """Response schema for listing test results."""
    
    results: list[TestResultSummary]
    total: int = Field(description="Number of results matching the filters, across all pages")
    page: int = Field(description="Page number, from 1")
    page_size: int = Field(description="Results per page")


class FailureBreakdownEntry(BaseModel):
    """A group of failed test results sharing the same test type and error message."""

    test_type: TestTypeStr
    error_message: str | None
    count: int


class TestSummaryResponse(BaseModel):
    """Summary statistics for test results."""

    total_tests: int
    passed: int
    failed: int
    running: int
    skipped: int
    by_test_type: dict[TestTypeStr, dict[str, int]]
    recent_executions: list[dict[str, str | int | None]]
    failures_by_type_and_message: list[FailureBreakdownEntry]


class ApiResponse(BaseModel):
    """Generic API response wrapper."""
    
    status: str = Field(description="`ok` on success")
    message: str | None = Field(default=None, description="Human-readable outcome")


__all__ = [
    "TestResultCreate",
    "TestResultResponse",
    "TestResultSummary",
    "TestResultsListResponse",
    "FailureBreakdownEntry",
    "TestSummaryResponse",
    "TestTypeStr",
    "TestStatusStr",
    "ApiResponse",
]
