from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_required_text(value: str | None, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} cannot be null")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be blank")
    return normalized


class TicketStatus(StrEnum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"


class TicketPriority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class TicketCreate(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=3, max_length=2000)
    requester: str = Field(min_length=2, max_length=80)
    priority: TicketPriority = TicketPriority.medium

    @field_validator("title", "description", "requester", mode="before")
    @classmethod
    def normalize_text(cls, value: str | None, info) -> str:
        return _normalize_required_text(value, info.field_name)


class TicketUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, min_length=3, max_length=2000)
    requester: str | None = Field(default=None, min_length=2, max_length=80)
    priority: TicketPriority | None = None
    status: TicketStatus | None = None

    @field_validator("title", "description", "requester", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None, info) -> str:
        return _normalize_required_text(value, info.field_name)

    @field_validator("priority", "status", mode="before")
    @classmethod
    def reject_null_enum_updates(cls, value, info):
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value


class Ticket(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    requester: str
    priority: TicketPriority
    status: TicketStatus
    created_at: datetime
    updated_at: datetime


class TicketFilters(BaseModel):
    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    search: str | None = None

    @field_validator("search", mode="before")
    @classmethod
    def normalize_search(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
