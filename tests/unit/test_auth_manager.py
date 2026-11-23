"""Unit tests for app.auth.UserManager.

`validate_password` is the one piece of custom logic `UserManager` adds on top of
fastapi-users' base behavior, and it's the app's only password-strength gate (see
`app/routers/admin.py`, which relies on `UserManager.create` raising
`InvalidPasswordException` to reject weak passwords). Exercised directly against the
method rather than through an endpoint, since it needs no database access at all.
"""
import asyncio

import pytest
from fastapi_users import exceptions

from app.auth import MIN_PASSWORD_LENGTH, UserManager


@pytest.fixture
def user_manager() -> UserManager:
    # `UserManager.__init__` only stores `user_db` for later DB calls; `validate_password`
    # never touches it, so a real SQLAlchemyUserDatabase isn't needed here.
    return UserManager(user_db=None)


def test_password_shorter_than_minimum_is_rejected(user_manager: UserManager):
    short_password = "a" * (MIN_PASSWORD_LENGTH - 1)

    with pytest.raises(exceptions.InvalidPasswordException):
        asyncio.run(user_manager.validate_password(short_password, user=None))


def test_password_at_minimum_length_is_accepted(user_manager: UserManager):
    asyncio.run(user_manager.validate_password("a" * MIN_PASSWORD_LENGTH, user=None))


def test_password_longer_than_minimum_is_accepted(user_manager: UserManager):
    asyncio.run(user_manager.validate_password("correct-horse-battery-staple", user=None))


def test_empty_password_is_rejected(user_manager: UserManager):
    with pytest.raises(exceptions.InvalidPasswordException):
        asyncio.run(user_manager.validate_password("", user=None))


def test_rejection_reason_mentions_minimum_length(user_manager: UserManager):
    with pytest.raises(exceptions.InvalidPasswordException) as exc_info:
        asyncio.run(user_manager.validate_password("short", user=None))

    assert str(MIN_PASSWORD_LENGTH) in exc_info.value.reason
