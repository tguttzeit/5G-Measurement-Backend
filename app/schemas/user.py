from fastapi_users.schemas import BaseUser, BaseUserUpdate, CreateUpdateDictModel
from pydantic import BaseModel, Field


class UserCreate(CreateUpdateDictModel):
    """User creation schema using username instead of email."""
    email: str = Field(min_length=1, description="Username (stored in email field)")
    password: str
    is_active: bool | None = True
    is_superuser: bool | None = False
    is_verified: bool | None = False


class UserUpdate(BaseUserUpdate):
    """User update schema for the superuser-gated PATCH /auth/{id} route."""
    pass


class UserUpdateMe(CreateUpdateDictModel):
    """Body of `PATCH /auth/me`. It has no `password` field: passwords change through
    `POST /auth/change-password`, which requires the current password."""
    email: str | None = Field(default=None, description="Username (stored in email field)")


class ChangePasswordRequest(BaseModel):
    """Request body for `POST /auth/change-password`."""
    current_password: str = Field(description="The account's current password")
    new_password: str = Field(description="The new password, at least 8 characters")


class User(BaseUser):
    """A dashboard account. `email` holds the username, not an email address."""
    # Override email to accept any string (not just email addresses)
    email: str = Field(description="Username (stored in email field)")


class UserListResponse(BaseModel):
    """Paginated list of users, for the admin user management page."""
    users: list[User]
    total: int = Field(description="Number of users in total, across all pages")
    page: int = Field(description="Page number, from 1")
    page_size: int = Field(description="Users per page")
