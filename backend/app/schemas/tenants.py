from pydantic import Field, field_validator

from .common import StrictMutationModel, StringEnum
from app.tenant import validate_tenant_id


class TenantStatus(StringEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


class TenantRecord(StrictMutationModel):
    id: str
    name: str = Field(min_length=1, max_length=200)
    status: TenantStatus
    created_at: str
    updated_at: str

    _canonical_id = field_validator("id")(validate_tenant_id)
