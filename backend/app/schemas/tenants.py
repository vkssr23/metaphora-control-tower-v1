from typing import Optional

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
    # Metaphora Secure's org_id, as a string. Set only for tenants
    # bootstrapped via the cross-product SSO handoff — None for every
    # tenant created through ordinary public signup.
    metaphora_org_id: Optional[str] = None

    _canonical_id = field_validator("id")(validate_tenant_id)
