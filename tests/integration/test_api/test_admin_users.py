"""Tests for the super-user admin user management: list + create users.

Reuses fastapi-users' existing superuser-gated GET/PATCH/DELETE /auth/{id} unchanged (see
app/routers/auth.py); this suite covers the two endpoints of its own: GET /admin/users
(list, paginated) and POST /admin/users (create). Creating users over the network is deliberate.

Needs a real Postgres (fastapi-users' async user DB isn't worth faking), so this lives under
tests/integration rather than tests/unit -- the test_client/db_session
fixtures used here are in tests/integration/conftest.py.
"""
from fastapi.testclient import TestClient
from fastapi_users.password import PasswordHelper
from sqlalchemy.orm import Session

from app.models.user import User

password_helper = PasswordHelper()


def _create_user(
    db_session: Session, username: str, password: str, is_superuser: bool = False
) -> User:
    user = User(
        email=username,
        hashed_password=password_helper.hash(password),
        is_active=True,
        is_superuser=is_superuser,
        is_verified=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _login(test_client: TestClient, username: str, password: str) -> str:
    response = test_client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- GET /admin/users ---------------------------------------------------


def test_list_users_requires_auth(test_client):
    response = test_client.get("/admin/users")

    assert response.status_code == 401


def test_list_users_rejects_non_superuser(test_client, db_session):
    _create_user(db_session, "regular-user", "correct-horse-battery-staple")
    token = _login(test_client, "regular-user", "correct-horse-battery-staple")

    response = test_client.get("/admin/users", headers=auth_headers(token))

    assert response.status_code == 403


def test_list_users_returns_created_users(test_client, db_session):
    _create_user(db_session, "admin-user", "correct-horse-battery-staple", is_superuser=True)
    token = _login(test_client, "admin-user", "correct-horse-battery-staple")
    _create_user(db_session, "listed-user", "correct-horse-battery-staple")

    response = test_client.get(
        "/admin/users", headers=auth_headers(token), params={"page_size": 200}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 200
    assert body["total"] == 2
    emails = {u["email"] for u in body["users"]}
    assert emails == {"admin-user", "listed-user"}
    # Response must never leak password hashes.
    assert all("hashed_password" not in u for u in body["users"])


def test_list_users_pagination_respects_page_size(test_client, db_session):
    _create_user(db_session, "admin-user", "correct-horse-battery-staple", is_superuser=True)
    token = _login(test_client, "admin-user", "correct-horse-battery-staple")
    _create_user(db_session, "other-user", "correct-horse-battery-staple")

    response = test_client.get(
        "/admin/users", headers=auth_headers(token), params={"page": 1, "page_size": 1}
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["users"]) == 1
    assert body["page_size"] == 1
    assert body["total"] == 2


# --- POST /admin/users ---------------------------------------------------


def test_create_user_requires_auth(test_client):
    response = test_client.post(
        "/admin/users",
        json={"email": "nope", "password": "correct-horse-battery"},
    )

    assert response.status_code == 401


def test_create_user_rejects_non_superuser(test_client, db_session):
    _create_user(db_session, "regular-user", "correct-horse-battery-staple")
    token = _login(test_client, "regular-user", "correct-horse-battery-staple")

    response = test_client.post(
        "/admin/users",
        json={"email": "nope", "password": "correct-horse-battery"},
        headers=auth_headers(token),
    )

    assert response.status_code == 403


def test_create_user_success(test_client, db_session):
    _create_user(db_session, "admin-user", "correct-horse-battery-staple", is_superuser=True)
    token = _login(test_client, "admin-user", "correct-horse-battery-staple")

    response = test_client.post(
        "/admin/users",
        json={
            "email": "created-user",
            "password": "correct-horse-battery-staple",
            "is_superuser": True,
        },
        headers=auth_headers(token),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "created-user"
    assert body["is_superuser"] is True
    assert "hashed_password" not in body
    assert "password" not in body

    # New account can actually authenticate.
    login = test_client.post(
        "/auth/login",
        data={"username": "created-user", "password": "correct-horse-battery-staple"},
    )
    assert login.status_code == 200


def test_create_user_duplicate_username_rejected(test_client, db_session):
    _create_user(db_session, "admin-user", "correct-horse-battery-staple", is_superuser=True)
    token = _login(test_client, "admin-user", "correct-horse-battery-staple")
    _create_user(db_session, "dupe-user", "correct-horse-battery-staple")

    response = test_client.post(
        "/admin/users",
        json={"email": "dupe-user", "password": "another-correct-horse"},
        headers=auth_headers(token),
    )

    assert response.status_code == 400


def test_create_user_short_password_rejected(test_client, db_session):
    _create_user(db_session, "admin-user", "correct-horse-battery-staple", is_superuser=True)
    token = _login(test_client, "admin-user", "correct-horse-battery-staple")

    response = test_client.post(
        "/admin/users",
        json={"email": "weakpw-user", "password": "short"},
        headers=auth_headers(token),
    )

    assert response.status_code == 400


def test_create_user_missing_email_returns_422_not_500(test_client, db_session):
    """UserCreate.email previously had `default=None` on a `str` field -- harmless while creation
    only happened via scripts/create_user.py (argparse enforces a required positional arg), but
    once reachable over the network a missing/empty email must be a clean validation error, not an
    unhandled 500 from `email=None` reaching UserManager.create.
    """
    _create_user(db_session, "admin-user", "correct-horse-battery-staple", is_superuser=True)
    token = _login(test_client, "admin-user", "correct-horse-battery-staple")

    response = test_client.post(
        "/admin/users",
        json={"password": "correct-horse-battery-staple"},
        headers=auth_headers(token),
    )

    assert response.status_code == 422


def test_create_user_empty_email_rejected(test_client, db_session):
    _create_user(db_session, "admin-user", "correct-horse-battery-staple", is_superuser=True)
    token = _login(test_client, "admin-user", "correct-horse-battery-staple")

    response = test_client.post(
        "/admin/users",
        json={"email": "", "password": "correct-horse-battery-staple"},
        headers=auth_headers(token),
    )

    assert response.status_code == 422
