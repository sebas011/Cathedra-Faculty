from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


class QualificationRateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["Academic degree", "Professional credential"]
    qualification: str = Field(min_length=1, max_length=120)
    hourly_addition: Decimal = Field(default=Decimal("0"), ge=0, le=100_000, decimal_places=2)
    effective_from: date
    effective_to: date | None = None
    reference: str = Field(default="", max_length=500)

    @field_validator("qualification", "reference", mode="before")
    @classmethod
    def clean_text(cls, value):
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_serializer("hourly_addition")
    def serialize_amount(self, value: Decimal) -> float:
        return float(value)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("The end date cannot be before the effective start date.")
        return self


class QualificationDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(default=0, ge=0)
    combination_rule: Literal["Unconfirmed", "Combine additions", "Highest addition only"] = (
        "Unconfirmed"
    )
    rates: list[QualificationRateInput] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def no_overlapping_rates(self):
        grouped = {}
        for rate in self.rates:
            key = (rate.category, rate.qualification.casefold())
            grouped.setdefault(key, []).append(rate)
        for rates in grouped.values():
            ordered = sorted(rates, key=lambda rate: rate.effective_from)
            for previous, current in zip(ordered, ordered[1:], strict=False):
                if previous.effective_to is None or previous.effective_to >= current.effective_from:
                    raise ValueError(
                        f"Effective dates overlap for {current.qualification}. End the earlier rate before the next one starts."
                    )
        return self


class QualificationDraftRead(QualificationDraftInput):
    status: Literal["Draft — not applied"] = "Draft — not applied"
    applies_to: Literal["External Part-time"] = "External Part-time"
    updated_by: str | None = None
    updated_at: datetime | None = None
