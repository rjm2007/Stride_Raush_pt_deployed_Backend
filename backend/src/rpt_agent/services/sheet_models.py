"""Validated shape of one Google Sheet row as the backend accepts it.

`sheet_direct` builds these from the row cells; `lead_actions` executes them.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..parsing import parse_flexible_date


class SheetLeadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, max_length=200)
    phone: str = Field(min_length=7, max_length=32)
    email: str | None = Field(
        default=None,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    date_of_birth: date | None = None
    location: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=200)
    lead_type: str | None = Field(
        default=None,
        max_length=200,
        description="Alias of title; either name may be sent with any non-empty value.",
    )
    @field_validator("full_name", "location", "title", "lead_type")
    @classmethod
    def optional_text_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value.strip() if value is not None else None

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def parse_date_of_birth(cls, value: date | datetime | str | None) -> date | None:
        return parse_flexible_date(value)

    @field_validator("date_of_birth")
    @classmethod
    def date_of_birth_not_future(cls, value: date | None) -> date | None:
        if value and value > datetime.now(UTC).date():
            raise ValueError("date_of_birth cannot be in the future")
        return value

    @model_validator(mode="after")
    def title_and_lead_type_are_aliases(self):
        if self.title and self.lead_type and self.title != self.lead_type:
            raise ValueError("title and lead_type must match when both are provided")
        resolved = self.title or self.lead_type
        if resolved:
            self.title = resolved
            self.lead_type = resolved
        return self


class LeadActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["start_cadence", "restart_cadence", "do_not_contact", "booked"]
    lead_id: UUID | None = None
    lead: SheetLeadInput

    @model_validator(mode="after")
    def fields_for_action(self):
        if self.action == "start_cadence":
            required = {
                "full_name": self.lead.full_name,
                "date_of_birth": self.lead.date_of_birth,
                "location": self.lead.location,
                "title": self.lead.title or self.lead.lead_type,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError(f"start_cadence requires: {', '.join(missing)}")
        elif self.lead_id is None:
            raise ValueError(f"{self.action} requires lead_id")
        return self
