"""Fixtures for integration tests: a real Postgres instance via testcontainers.

No integration tests are added here - this file only provides the fixtures those tests
will use.
"""

import os
from collections.abc import AsyncGenerator, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.community.postgres import PostgresContainer

from app.db import Base, get_async_db, get_db
from app.main import app

# Throwaway credentials for a container that only ever exists for the lifetime of a test
# run - overridable via env vars (e.g. from a gitignored .env.test) rather than hardcoded
# elsewhere, so no credential lives in the code.
TEST_DB_USER = os.environ.get("TEST_DB_USER", "test_user")
TEST_DB_PASSWORD = os.environ.get("TEST_DB_PASSWORD", "test_password")
TEST_DB_NAME = os.environ.get("TEST_DB_NAME", "test_db")


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """A Postgres 15 container, started once and shared by the whole test session."""
    with PostgresContainer(
        "postgres:15",
        username=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
        dbname=TEST_DB_NAME,
        driver="psycopg",
    ) as container:
        yield container


@pytest.fixture(scope="session")
def _engine(postgres_container: PostgresContainer) -> Generator[Engine, None, None]:
    engine = create_engine(postgres_container.get_connection_url())
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def _async_engine(postgres_container: PostgresContainer) -> Generator[AsyncEngine, None, None]:
    engine = create_async_engine(postgres_container.get_connection_url())
    yield engine


@pytest.fixture
def db_session(_engine: Engine) -> Generator[Session, None, None]:
    """A SQLAlchemy session for direct DB setup/assertions in a test."""
    session_factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_client(_engine: Engine, _async_engine: AsyncEngine) -> Generator[TestClient, None, None]:
    """A FastAPI TestClient wired up to the test Postgres container instead of the real DB."""
    session_factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    async_session_factory = async_sessionmaker(
        bind=_async_engine, autoflush=False, expire_on_commit=False
    )

    def override_get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    async def override_get_async_db() -> AsyncGenerator[None, None]:
        async with async_session_factory() as session:
            try:
                yield session
            finally:
                await session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_async_db] = override_get_async_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_async_db, None)


@pytest.fixture(autouse=True)
def cleanup(_engine: Engine) -> Generator[None, None, None]:
    """Truncate every table after each test so state doesn't leak between tests."""
    yield
    table_names = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    if table_names:
        with _engine.begin() as conn:
            conn.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))
