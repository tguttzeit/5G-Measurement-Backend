"""Database models for testing data visualization."""
from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, String, Text, func, true
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TestType(StrEnum):
    """Types of tests that can be performed."""
    MODEM = "modem"
    GPS = "gps"
    COLLECTOR = "collector"
    UPLOADER = "uploader"
    HEARTBEAT = "heartbeat"


class TestStatus(StrEnum):
    """Status of a test execution."""
    PASSED = "passed"
    FAILED = "failed"
    RUNNING = "running"
    SKIPPED = "skipped"


class TestResult(Base):
    """Represents a test result from manual integration testing.
    
    This model stores test results with a testing flag to distinguish them
    from production data.
    """

    __tablename__ = "test_results"
    __test__ = False  # not a pytest test class despite the name

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(
        String, ForeignKey("devices.device_id", ondelete="CASCADE"), index=True, nullable=False
    )
    test_type: Mapped[TestType] = mapped_column(
        SQLEnum(TestType, values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        index=True,
        nullable=False,
    )
    status: Mapped[TestStatus] = mapped_column(
        SQLEnum(TestStatus, values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Flag to distinguish test data from production data. Indexed and given a
    # server_default (rather than relying solely on the app-layer default)
    # because both the default list view and the summary endpoint filter on
    # this column on every request.
    is_testing: Mapped[bool] = mapped_column(
        Boolean, server_default=true(), nullable=False, index=True
    )
    
    # Test details
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )
    
    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        {
            "comment": "Stores test results from manual integration testing. "
                       "Test data is marked with is_testing=True to separate from production data."
        },
    )


__all__ = ["TestResult", "TestType", "TestStatus"]
