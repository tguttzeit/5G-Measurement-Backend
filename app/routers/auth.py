from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi_users import exceptions

from app.auth import (
    MAX_FAILED_PASSWORD_ATTEMPTS,
    UserManager,
    auth_backend,
    current_active_user,
    fastapi_users,
    get_user_manager,
)
from app.models.user import User as UserModel
from app.schemas.user import ChangePasswordRequest, User, UserUpdate, UserUpdateMe

router = APIRouter(tags=["auth"])


def _describe_routes(api_router: APIRouter, texts: dict[str, tuple[str, str]]) -> APIRouter:
    """Sets the summary and description of fastapi-users' generated routes, by route name."""
    for route in api_router.routes:
        if route.name in texts:
            route.summary, route.description = texts[route.name]
    return api_router


_USER_OBJECT = (
    "Users carry `id`, `email` (the username), `is_active`, `is_superuser` and `is_verified`; "
    "the password hash is never returned."
)

# Include the fastapi-users routers
# Note: fastapi-users routers already have their own paths, so we include them
# with empty prefix and rely on the parent router's prefix
router.include_router(
    _describe_routes(
        fastapi_users.get_auth_router(auth_backend),
        {
            "auth:jwt.login": (
                "Log in and get an access token",
                "Dashboard accounts log in with a username (any non-empty string, stored in the "
                "`email` field) and a password, sent as a form body with the fields `username` "
                "and `password`. The response is `{\"access_token\", \"token_type\": "
                "\"bearer\"}`; send the token as `Authorization: Bearer <token>`. Tokens expire "
                "after a configurable lifetime (30 minutes by default). Wrong credentials give "
                "400. A successful login clears a change-password lockout. There is no public "
                "registration: accounts are created by a superuser.",
            ),
            "auth:jwt.logout": (
                "Log out",
                "Tokens are stateless and the server keeps no session, so this only validates "
                "the token; the client logs out by discarding it.",
            ),
        },
    ),
    prefix="",
)

# No public register route: accounts are created by a superuser (POST /admin/users) or from the
# host with scripts/create_user.py.


@router.patch(
    "/me",
    response_model=User,
    name="users:patch_current_user_safe",
    summary="Update my username",
    description=(
        "Changes the caller's own username (the `email` field). The body has no `password` "
        "field; passwords change through `POST /auth/change-password`. 400 if the username is "
        "already taken. " + _USER_OBJECT
    ),
)
async def update_me(
    request: Request,
    user_update: UserUpdateMe,
    user: UserModel = Depends(current_active_user),
    user_manager: UserManager = Depends(get_user_manager),
) -> User:
    """PATCH /auth/me, minus the ability to change the password with no re-auth.

    Registered before `users_router` below: fastapi-users' `PATCH /{id}` route would otherwise
    also match "PATCH /me" (treating "me" as `id`) and shadow this one, since Starlette matches
    routes in registration order.
    """
    try:
        updated_user = await user_manager.update(user_update, user, safe=True, request=request)
    except exceptions.UserAlreadyExists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this username already exists.",
        )
    return User.model_validate(updated_user)


users_router = _describe_routes(
    fastapi_users.get_users_router(User, UserUpdate),
    {
        "users:current_user": ("Get my user", "The caller's own user. " + _USER_OBJECT),
        "users:user": (
            "Get a user (superuser)",
            "Reads one user by id. Superuser only; 404 for an unknown id. " + _USER_OBJECT,
        ),
        "users:patch_user": (
            "Update a user (superuser)",
            "Superuser only. Updates a user, including `password`, `is_active` and "
            "`is_superuser`; a password reset clears the user's change-password lockout. 404 "
            "for an unknown id, 400 if the username is taken. " + _USER_OBJECT,
        ),
        "users:delete_user": (
            "Delete a user (superuser)",
            "Superuser only. Deletes the user and answers 204 without a body; 404 for an "
            "unknown id.",
        ),
    },
)
# fastapi-users' generated PATCH /me accepts UserUpdate as-is, which includes a `password`
# field with no re-authentication check -- a stolen/leaked token could otherwise silently
# rotate the account's password. Drop it in favor of the stripped route defined above.
users_router.routes = [
    route
    for route in users_router.routes
    if getattr(route, "name", None) != "users:patch_current_user"
]
router.include_router(users_router, prefix="")


@router.post(
    "/change-password",
    response_model=User,
    summary="Change my password",
    description=(
        "Self-service password change, gated on re-entering the current password. Passwords "
        "must be at least 8 characters. 400 if the current password is wrong (the body then "
        "carries `attempts_remaining`), if the new password is too short, or if the account is "
        "locked. After 5 consecutive wrong `current_password` submissions further attempts are "
        "refused until the user logs in successfully or a superuser resets the password. "
        + _USER_OBJECT
    ),
)
async def change_password(
    payload: ChangePasswordRequest,
    user: UserModel = Depends(current_active_user),
    user_manager: UserManager = Depends(get_user_manager),
) -> User:
    """Self-service password change, gated on re-entering the current password.

    Locks out further attempts after MAX_FAILED_PASSWORD_ATTEMPTS consecutive wrong
    `current_password` submissions.
    """
    if user.failed_password_attempts >= MAX_FAILED_PASSWORD_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account locked after too many failed attempts. Contact an administrator.",
        )

    verified, _ = user_manager.password_helper.verify_and_update(
        payload.current_password, user.hashed_password
    )
    if not verified:
        user = await user_manager.user_db.update(
            user, {"failed_password_attempts": user.failed_password_attempts + 1}
        )
        attempts_remaining = max(0, MAX_FAILED_PASSWORD_ATTEMPTS - user.failed_password_attempts)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "detail": "Current password is incorrect.",
                "attempts_remaining": attempts_remaining,
            },
        )

    try:
        await user_manager.validate_password(payload.new_password, user)
    except exceptions.InvalidPasswordException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"reason": e.reason},
        )

    updated_user = await user_manager.user_db.update(
        user,
        {
            "hashed_password": user_manager.password_helper.hash(payload.new_password),
            "failed_password_attempts": 0,
        },
    )
    return User.model_validate(updated_user)
