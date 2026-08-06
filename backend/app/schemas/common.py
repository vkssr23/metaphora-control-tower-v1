from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class StrictMutationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrictUpdateModel(StrictMutationModel):
    nullable_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def reject_empty_update(self):
        if not self.model_fields_set:
            raise ValueError("At least one update field is required")
        invalid_nulls = [name for name in self.model_fields_set if getattr(self, name) is None and name not in self.nullable_fields]
        if invalid_nulls:
            raise ValueError(f"Null is not allowed for: {', '.join(sorted(invalid_nulls))}")
        return self


def validate_date_or_empty(value: str) -> str:
    if value == "":
        return value
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Must be an ISO-8601 date or datetime") from exc
    return value


def finite(value: Any) -> Any:
    if value is not None and isinstance(value, (float, int)) and not isfinite(value):
        raise ValueError("Must be finite")
    return value


class StringEnum(str, Enum):
    pass
