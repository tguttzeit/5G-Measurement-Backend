"""Pydantic schemas for the per-user notification settings API."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


class NotificationEvent(StrEnum):
    """The device events a user can be notified about; shared by validation, storage and
    detection."""

    BOX_STARTED = "box_started"
    MEASUREMENT_STARTED = "measurement_started"
    MEASUREMENT_FINISHED = "measurement_finished"
    RUNS_UPLOADED = "runs_uploaded"
    ERROR = "error"


class NotificationSettingsUpdate(BaseModel):
    """Never carries the topic: it only changes through the regenerate-topic action."""

    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool
    events: list[NotificationEvent] = Field(max_length=len(NotificationEvent) * 4)

    @field_validator("events")
    @classmethod
    def _without_duplicates(cls, events: list[NotificationEvent]) -> list[NotificationEvent]:
        return list(dict.fromkeys(events))


class NotificationSettings(BaseModel):
    enabled: bool
    events: list[NotificationEvent]
    topic: str = Field(description="Secret ntfy topic of the caller; subscribe to it in ntfy")
    server_url: str = Field(description="ntfy server the topic lives on")
