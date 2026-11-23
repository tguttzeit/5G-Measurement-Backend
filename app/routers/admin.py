"""Super-user admin endpoints for user management.

Account creation here is intentionally superuser-JWT-gated over the network.
`scripts/create_user.py` remains the host-access path, e.g. for the first superuser.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi_users import exceptions
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import UserManager, current_superuser, get_user_manager
from app.db import get_async_db
from app.models.user import User as UserModel
from app.schemas.user import User, UserCreate, UserListResponse

router = APIRouter(
    prefix="/admin/users", tags=["admin"], dependencies=[Depends(current_superuser)]
)


@router.get(
    "",
    response_model=UserListResponse,
    summary="List users",
    description=(
        "Superuser only. Paginated user list ordered by id: `{\"users\", \"total\", \"page\", "
        "\"page_size\"}`. `page` starts at 1, `page_size` is 1 to 200 (default 50). Users carry "
        "`id`, `email` (the username), `is_active`, `is_superuser` and `is_verified`; the "
        "password hash is never returned."
    ),
)
async def list_users(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Users per page"),
    session: AsyncSession = Depends(get_async_db),
) -> UserListResponse:
    """List users, paginated, ordered by id. Superuser only."""
    total = await session.scalar(select(func.count()).select_from(UserModel))

    offset = (page - 1) * page_size
    result = await session.scalars(
        select(UserModel).order_by(UserModel.id).offset(offset).limit(page_size)
    )

    return UserListResponse(
        users=[User.model_validate(user) for user in result.all()],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=User,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user",
    description=(
        "Superuser only. Creates an account from `{\"email\", \"password\", \"is_active\", "
        "\"is_superuser\", \"is_verified\"}`, where `email` is the username (any non-empty "
        "string). The flags are honored and default to `true`, `false` and `false`. Passwords "
        "must be at least 8 characters. 400 if the username exists or the password is too "
        "short. There is no public registration route."
    ),
)
async def create_user(
    user_create: UserCreate,
    user_manager: UserManager = Depends(get_user_manager),
) -> User:
    """Create a user. Superuser only.

    `safe=False`: the requester is already confirmed superuser (router-level dependency), so
    `is_superuser`/`is_active`/`is_verified` on the payload are honored rather than stripped.
    """
    try:
        created = await user_manager.create(user_create, safe=False)
    except exceptions.UserAlreadyExists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this username already exists.",
        )
    except exceptions.InvalidPasswordException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"reason": e.reason},
        )

    return User.model_validate(created)
