"""Tests for the self-service password change, with brute-force lockout.

Needs a real Postgres (fastapi-users' async user DB isn't worth faking), so this lives under
tests/integration rather than tests/unit -- the test_client/db_session
fixtures used here are in tests/integration/conftest.py.
"""
from fastapi.testclient import TestClient
from fastapi_users.password import PasswordHelper
from sqlalchemy.orm import Session

from app.auth import MAX_FAILED_PASSWORD_ATTEMPTS
from app.models.user import User

password_helper = PasswordHelper()


def _create_user(
    db_session: Session,
    username: str,
    password: str,
    is_superuser: bool = False,
    failed_password_attempts: int = 0,
) -> User:
    user = User(
        email=username,
        hashed_password=password_helper.hash(password),
        is_active=True,
        is_superuser=is_superuser,
        is_verified=False,
        failed_password_attempts=failed_password_attempts,
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


# --- POST /auth/change-password -----------------------------------------


def test_change_password_requires_auth(test_client):
    response = test_client.post(
        "/auth/change-password",
        json={"current_password": "old", "new_password": "new-correct-horse"},
    )

    assert response.status_code == 401


def test_change_password_success(test_client, db_session):
    _create_user(db_session, "user-one", "old-correct-horse")
    token = _login(test_client, "user-one", "old-correct-horse")

    response = test_client.post(
        "/auth/change-password",
        json={"current_password": "old-correct-horse", "new_password": "new-correct-horse"},
        headers=auth_headers(token),
    )

    assert response.status_code == 200, response.text
    assert "hashed_password" not in response.json()
    assert "new_password" not in response.text
    assert "current_password" not in response.text

    # Old password no longer works, new one does.
    old_login = test_client.post(
        "/auth/login", data={"username": "user-one", "password": "old-correct-horse"}
    )
    assert old_login.status_code == 400

    new_login = test_client.post(
        "/auth/login", data={"username": "user-one", "password": "new-correct-horse"}
    )
    assert new_login.status_code == 200


def test_change_password_wrong_current_password_rejected(test_client, db_session):
    _create_user(db_session, "user-two", "correct-horse-battery")
    token = _login(test_client, "user-two", "correct-horse-battery")

    response = test_client.post(
        "/auth/change-password",
        json={"current_password": "wrong-password", "new_password": "new-correct-horse"},
        headers=auth_headers(token),
    )

    assert response.status_code == 400
    body = response.json()["detail"]
    assert body["detail"] == "Current password is incorrect."
    assert body["attempts_remaining"] == MAX_FAILED_PASSWORD_ATTEMPTS - 1

    # Original password still works -- nothing was changed.
    login = test_client.post(
        "/auth/login", data={"username": "user-two", "password": "correct-horse-battery"}
    )
    assert login.status_code == 200


def test_change_password_weak_new_password_rejected(test_client, db_session):
    _create_user(db_session, "user-three", "correct-horse-battery")
    token = _login(test_client, "user-three", "correct-horse-battery")

    response = test_client.post(
        "/auth/change-password",
        json={"current_password": "correct-horse-battery", "new_password": "short"},
        headers=auth_headers(token),
    )

    assert response.status_code == 400
    login = test_client.post(
        "/auth/login", data={"username": "user-three", "password": "correct-horse-battery"}
    )
    assert login.status_code == 200


def test_change_password_locks_out_after_max_failed_attempts(test_client, db_session):
    _create_user(db_session, "user-four", "correct-horse-battery")
    token = _login(test_client, "user-four", "correct-horse-battery")

    for expected_remaining in range(MAX_FAILED_PASSWORD_ATTEMPTS - 1, -1, -1):
        wrong_attempt = test_client.post(
            "/auth/change-password",
            json={"current_password": "wrong-password", "new_password": "new-correct-horse"},
            headers=auth_headers(token),
        )
        assert wrong_attempt.status_code == 400
        assert wrong_attempt.json()["detail"]["attempts_remaining"] == expected_remaining

    # Even the correct password is now rejected outright -- the account is locked.
    locked_out = test_client.post(
        "/auth/change-password",
        json={"current_password": "correct-horse-battery", "new_password": "new-correct-horse"},
        headers=auth_headers(token),
    )

    assert locked_out.status_code == 400
    assert "locked" in locked_out.json()["detail"].lower()


def test_successful_login_clears_lockout(test_client, db_session):
    _create_user(
        db_session,
        "user-five",
        "correct-horse-battery",
        failed_password_attempts=MAX_FAILED_PASSWORD_ATTEMPTS,
    )

    token = _login(test_client, "user-five", "correct-horse-battery")

    response = test_client.post(
        "/auth/change-password",
        json={"current_password": "correct-horse-battery", "new_password": "new-correct-horse"},
        headers=auth_headers(token),
    )

    assert response.status_code == 200, response.text


def test_superuser_password_reset_clears_lockout(test_client, db_session):
    _create_user(db_session, "admin-user", "correct-horse-battery", is_superuser=True)
    admin_token = _login(test_client, "admin-user", "correct-horse-battery")
    locked_user = _create_user(
        db_session,
        "user-six",
        "correct-horse-battery",
        failed_password_attempts=MAX_FAILED_PASSWORD_ATTEMPTS,
    )

    response = test_client.patch(
        f"/auth/{locked_user.id}",
        json={"password": "admin-reset-correct-horse"},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 200, response.text

    db_session.refresh(locked_user)
    assert locked_user.failed_password_attempts == 0

    login = test_client.post(
        "/auth/login", data={"username": "user-six", "password": "admin-reset-correct-horse"}
    )
    assert login.status_code == 200


# --- PATCH /auth/me no longer accepts `password` -------------------------


def test_patch_me_ignores_password_field(test_client, db_session):
    _create_user(db_session, "user-seven", "correct-horse-battery")
    token = _login(test_client, "user-seven", "correct-horse-battery")

    response = test_client.patch(
        "/auth/me",
        json={"password": "attacker-supplied-new-password"},
        headers=auth_headers(token),
    )

    # No `password` field on the schema -- unknown fields are ignored, not an error.
    assert response.status_code == 200, response.text

    # Original password still works: PATCH /me could not rotate it.
    login = test_client.post(
        "/auth/login", data={"username": "user-seven", "password": "correct-horse-battery"}
    )
    assert login.status_code == 200
