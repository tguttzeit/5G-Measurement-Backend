#!/usr/bin/env python3
"""CLI script to create a new user.

Note: The 'email' field in the database is used to store usernames,
not actual email addresses.

There is no public registration endpoint. This script works from the host or container without a
token, which is how the first superuser is created; later accounts can also be created by a
superuser through `POST /admin/users`.

Usage:
    uv run python scripts/create_user.py username password [--superuser]
"""

import argparse
import asyncio
import os
import sys

# Add the project root to the path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from fastapi_users.db import SQLAlchemyUserDatabase  # noqa: E402
from fastapi_users.exceptions import UserAlreadyExists  # noqa: E402

from app.auth import UserManager  # noqa: E402
from app.db import AsyncSessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.user import UserCreate  # noqa: E402


async def create_user(email: str, password: str, is_superuser: bool = False) -> bool:
    """Create a new user directly via UserManager.

    Args:
        email: The username (stored in the email field)
        password: The user's password
        is_superuser: Whether to grant superuser privileges
    """
    async with AsyncSessionLocal() as session:
        user_db = SQLAlchemyUserDatabase(session, User)
        user_manager = UserManager(user_db)

        try:
            await user_manager.create(
                UserCreate(email=email, password=password, is_superuser=is_superuser),
                safe=False,
            )
        except UserAlreadyExists:
            print(f"User '{email}' already exists.")
            return True

        if is_superuser:
            print(f"User '{email}' created with superuser privileges.")
        else:
            print(f"User '{email}' created successfully.")

        return True


def main():
    parser = argparse.ArgumentParser(
        description="Create a new user (email field is used for username)"
    )
    parser.add_argument("email", help="Username for the new user (stored as email)")
    parser.add_argument("password", help="Password for the new user")
    parser.add_argument("--superuser", "-s", action="store_true", help="Make the user a superuser")

    args = parser.parse_args()

    success = asyncio.run(create_user(args.email, args.password, args.superuser))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
