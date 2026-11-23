"""Unit tests for app/routers/admin.py: GET/POST /admin/users.

Isolated: the DB session, user manager, and
`current_superuser` dependency are all replaced with mocks/fakes via FastAPI's
`dependency_overrides`, so these run against no real database (integration coverage of
the same endpoints against a real Postgres already exists in
`tests/integration/test_api/test_admin_users.py`).
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from fastapi_users import exceptions

from app.auth import current_superuser, get_user_manager
from app.db import get_async_db
from app.main import app

client = TestClient(app)

FAKE_SUPERUSER = SimpleNamespace(
    id=1, email="admin", is_active=True, is_superuser=True, is_verified=True
)


def _fake_user(user_id: int, email: str, is_superuser: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id, email=email, is_active=True, is_superuser=is_superuser, is_verified=False
    )


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


# --- GET /admin/users -----------------------------------------------------


def test_list_users_requires_auth():
    """No token at all: fastapi-users' bearer transport rejects before touching the DB."""
    response = client.get("/admin/users")

    assert response.status_code == 401


def test_list_users_returns_users_from_db():
    session = AsyncMock()
    session.scalar.return_value = 2
    session.scalars.return_value.all = Mock(
        return_value=[
            _fake_user(1, "admin-user", is_superuser=True),
            _fake_user(2, "listed-user"),
        ]
    )

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_async_db] = lambda: session

    response = client.get("/admin/users")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {u["email"] for u in body["users"]} == {"admin-user", "listed-user"}
    assert all("hashed_password" not in u for u in body["users"])


def test_list_users_default_pagination():
    session = AsyncMock()
    session.scalar.return_value = 0
    session.scalars.return_value.all = Mock(return_value=[])

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_async_db] = lambda: session

    response = client.get("/admin/users")

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 50


def test_list_users_page_size_rejects_out_of_range_value():
    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_async_db] = lambda: AsyncMock()

    response = client.get("/admin/users", params={"page_size": 1000})

    assert response.status_code == 422


def test_list_users_zero_total_returns_zero_not_none():
    """`session.scalar(count(...))` returning None (empty table) must not surface as null."""
    session = AsyncMock()
    session.scalar.return_value = None
    session.scalars.return_value.all = Mock(return_value=[])

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_async_db] = lambda: session

    response = client.get("/admin/users")

    assert response.status_code == 200
    assert response.json()["total"] == 0


# --- POST /admin/users -----------------------------------------------------


def test_create_user_requires_auth():
    response = client.post("/admin/users", json={"email": "nope", "password": "correct-horse"})

    assert response.status_code == 401


def test_create_user_success():
    user_manager = AsyncMock()
    user_manager.create.return_value = _fake_user(3, "created-user", is_superuser=True)

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_user_manager] = lambda: user_manager

    response = client.post(
        "/admin/users",
        json={
            "email": "created-user",
            "password": "correct-horse-battery-staple",
            "is_superuser": True,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "created-user"
    assert body["is_superuser"] is True
    assert "hashed_password" not in body

    # safe=False: the router trusts an already-confirmed superuser's payload as-is.
    _, kwargs = user_manager.create.call_args
    assert kwargs["safe"] is False


def test_create_user_duplicate_returns_400():
    user_manager = AsyncMock()
    user_manager.create.side_effect = exceptions.UserAlreadyExists()

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_user_manager] = lambda: user_manager

    response = client.post(
        "/admin/users",
        json={"email": "dupe-user", "password": "correct-horse-battery-staple"},
    )

    assert response.status_code == 400


def test_create_user_weak_password_returns_400_with_reason():
    user_manager = AsyncMock()
    user_manager.create.side_effect = exceptions.InvalidPasswordException(
        reason="Password must be at least 8 characters long."
    )

    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_user_manager] = lambda: user_manager

    response = client.post(
        "/admin/users",
        json={"email": "weakpw-user", "password": "short"},
    )

    assert response.status_code == 400
    assert "8 characters" in response.json()["detail"]["reason"]


def test_create_user_missing_email_returns_422_not_500():
    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_user_manager] = lambda: AsyncMock()

    response = client.post("/admin/users", json={"password": "correct-horse-battery-staple"})

    assert response.status_code == 422


def test_create_user_empty_email_returns_422():
    app.dependency_overrides[current_superuser] = lambda: FAKE_SUPERUSER
    app.dependency_overrides[get_user_manager] = lambda: AsyncMock()

    response = client.post(
        "/admin/users", json={"email": "", "password": "correct-horse-battery-staple"}
    )

    assert response.status_code == 422
