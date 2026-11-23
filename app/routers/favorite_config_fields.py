"""Superuser-only per-user favorites of the Remote Configuration fields.

The user comes from the session, never from the request, so a caller can only ever read or
replace their own favorites.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import current_superuser
from app.config_override_spec import specs_in_display_order
from app.db import get_db
from app.models.favorite_config_field import UserFavoriteConfigField
from app.models.user import User
from app.routers.field_only_validation import FieldOnlyValidationErrorRoute
from app.schemas.favorite_config_fields import FavoriteConfigFields, FavoriteConfigFieldsUpdate

router = APIRouter(
    prefix="/favorite-config-fields",
    tags=["commands"],
    dependencies=[Depends(current_superuser)],
    route_class=FieldOnlyValidationErrorRoute,
)


def _favorites_of(db: Session, user_id: int) -> FavoriteConfigFields:
    stored = set(
        db.scalars(
            select(UserFavoriteConfigField.field_key).where(
                UserFavoriteConfigField.user_id == user_id
            )
        )
    )
    # Walking the registry drops keys of fields removed since, and gives a stable order.
    return FavoriteConfigFields(
        field_keys=[spec.key for spec in specs_in_display_order() if spec.key in stored]
    )


@router.get(
    "",
    response_model=FavoriteConfigFields,
    summary="The calling user's favorite config fields",
    description=(
        "Superuser only. Per-user favorites of the Remote Configuration fields, which the form "
        "groups in a \"Favorites\" section: `{\"field_keys\": [...]}` in form display order. "
        "Keys of fields that no longer exist are left out. The user is always the caller; there "
        "is no way to read or change another user's favorites."
    ),
)
def get_favorite_config_fields(
    db: Session = Depends(get_db), user: User = Depends(current_superuser)
) -> FavoriteConfigFields:
    return _favorites_of(db, user.id)


@router.put(
    "",
    response_model=FavoriteConfigFields,
    summary="Replace the calling user's favorite config fields",
    description=(
        "Superuser only. Body `{\"field_keys\": [...]}` replaces the stored list and returns it "
        "in the same shape. Valid keys are the `key` values of `GET /config-schema`. 422 for an "
        "unknown or duplicate key, a non-string key, a key longer than 100 characters, more "
        "keys than there are config fields, or extra body properties."
    ),
)
def put_favorite_config_fields(
    payload: FavoriteConfigFieldsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_superuser),
) -> FavoriteConfigFields:
    db.execute(
        delete(UserFavoriteConfigField).where(UserFavoriteConfigField.user_id == user.id)
    )
    db.add_all(
        UserFavoriteConfigField(user_id=user.id, field_key=key) for key in payload.field_keys
    )
    db.commit()
    return _favorites_of(db, user.id)
