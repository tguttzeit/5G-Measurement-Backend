from collections.abc import AsyncGenerator

from fastapi import Depends, Request, Response
from fastapi_users import BaseUserManager, FastAPIUsers, IntegerIDMixin, exceptions, schemas
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_async_db
from app.models.user import User

SECRET = get_settings().secret_key


async def get_user_db(session: AsyncSession = Depends(get_async_db)):
    """Get the user database instance."""
    yield SQLAlchemyUserDatabase(session, User)


MIN_PASSWORD_LENGTH = 8

# Consecutive wrong `current_password` submissions to POST /auth/change-password before
# self-service password change is locked out. Cleared only by a successful login or a
# superuser-driven password change.
MAX_FAILED_PASSWORD_ATTEMPTS = 5


class UserManager(IntegerIDMixin, BaseUserManager[User, int]):
    reset_password_token_secret = SECRET
    verification_token_secret = SECRET

    async def validate_password(
        self, password: str, user: schemas.UC | User
    ) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise exceptions.InvalidPasswordException(
                reason=f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
            )

    async def on_after_register(self, user: User, request: Request | None = None):
        print(f"User {user.id} has registered.")

    async def on_after_login(
        self, user: User, request: Request | None = None, response: Response | None = None
    ) -> None:
        # Proven-correct credentials clear a change-password lockout, same as an explicit
        # superuser-driven reset.
        if user.failed_password_attempts != 0:
            await self.user_db.update(user, {"failed_password_attempts": 0})

    async def on_after_update(
        self, user: User, update_dict: dict, request: Request | None = None
    ) -> None:
        # A superuser-driven password reset (PATCH /auth/{id}, safe=False) clears a change-password
        # lockout too, same as a successful login. `update_dict` is the raw payload from
        # `create_update_dict[_superuser]`, keyed by "password" (not yet hashed) at this point.
        if update_dict.get("password") is not None and user.failed_password_attempts != 0:
            await self.user_db.update(user, {"failed_password_attempts": 0})

    async def on_after_forgot_password(
        self, user: User, token: str, request: Request | None = None
    ):
        # TODO: deliver the token via email once outbound mail is wired up.
        # Never log it — it's a live credential.
        print(f"User {user.id} has requested a password reset.")

    async def on_after_request_verify(
        self, user: User, token: str, request: Request | None = None
    ):
        # TODO: deliver the token via email once outbound mail is wired up.
        # Never log it — it's a live credential.
        print(f"Verification requested for user {user.id}.")


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db)


bearer_transport = BearerTransport(tokenUrl="auth/login")


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(
        secret=SECRET,
        lifetime_seconds=get_settings().access_token_expire_minutes * 60,
    )


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, int](
    get_user_manager,
    [auth_backend],
)

current_active_user = fastapi_users.current_user(active=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
optional_active_user = fastapi_users.current_user(active=True, optional=True)
