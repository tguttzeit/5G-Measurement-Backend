"""Metadata endpoint describing the remotely overridable config fields.

Superuser-only, like the override queue it describes. The content is static and derived from
`app/config_override_spec.py`, the same registry that validates queued overrides.
"""
from fastapi import APIRouter, Depends

from app.auth import current_superuser
from app.config_override_spec import GROUP_ORDER, FieldSpec, specs_in_display_order
from app.models.user import User
from app.schemas.commands import ConfigSchemaField, ConfigSchemaGroup, ConfigSchemaResponse

router = APIRouter(tags=["commands"])


def _field(spec: FieldSpec) -> ConfigSchemaField:
    return ConfigSchemaField(
        key=spec.key,
        type=spec.kind,
        min=spec.minimum,
        max=spec.maximum,
        values=list(spec.choices) if spec.choices else None,
        nullable=spec.nullable,
        unit=spec.unit,
        requires_confirmation=spec.requires_confirmation,
        no_effect_yet=spec.no_effect_yet,
    )


@router.get(
    "/config-schema",
    response_model=ConfigSchemaResponse,
    summary="Describe the remotely overridable config fields",
    description=(
        "Superuser only. Describes the overridable fields for the Remote Configuration form, "
        "statically and from the same registry that validates `POST /devices/{device_id}/"
        "config-overrides`, so validation and form metadata cannot drift. Groups and fields "
        "come in display order; the group ids, in order, are `measurement_cycle`, "
        "`movement_detection`, `latency_tests`, `backend_operation`, `pipeline_monitoring` and "
        "`risky`. A field has `key`, `type` (`float`, `int`, `enum` or `bool`), `min` and `max` "
        "(for `float` and `int`), `values` (for `enum`), `nullable` (an explicit `null` resets "
        "the override), `unit`, `requires_confirmation` (the frontend must confirm before "
        "saving) and `no_effect_yet` (the device accepts the field but does not act on it "
        "yet). Descriptions and translations are not part of it; the frontend owns them. 401 "
        "without a valid token, 403 for a non-superuser."
    ),
)
async def get_config_schema(_: User = Depends(current_superuser)) -> ConfigSchemaResponse:
    fields = specs_in_display_order()
    return ConfigSchemaResponse(
        groups=[
            ConfigSchemaGroup(
                id=group,
                fields=[_field(spec) for spec in fields if spec.group == group],
            )
            for group in GROUP_ORDER
        ]
    )
