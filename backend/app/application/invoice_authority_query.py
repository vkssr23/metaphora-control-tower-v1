"""Tenant-scoped evidence query for canonical invoice authority."""
from app.domain.invoice_authority import classify_invoice_authority
from app.runtime import db
from app.tenant import tenant_filter

MODERN_LIFECYCLE_COLLECTIONS = (
    "load_passports", "execution_eligibility_cases", "pickup_release_cases", "execution_sessions"
)

async def invoice_authority_for_load(user, load_id, invoices=None):
    """Resolve bounded, tenant-scoped evidence for the modern billing boundary."""
    if invoices is None:
        invoice_collection = getattr(db, "invoices", None)
        invoices = await invoice_collection.find(tenant_filter(user, {"load_id": load_id})).to_list(50) if invoice_collection is not None else []
    readiness_collection = getattr(db, "invoice_readiness_cases", None)
    readiness = ([await readiness_collection.find_one(tenant_filter(user, {"load_id": load_id}), {"_id": 0})]
                 if readiness_collection is not None else [])
    readiness = [item for item in readiness if item]
    lifecycle = []
    for name in MODERN_LIFECYCLE_COLLECTIONS:
        collection = getattr(db, name, None)
        if collection is not None:
            item = await collection.find_one(tenant_filter(user, {"load_id": load_id}), {"_id": 0})
            if item:
                lifecycle.append({"domain": name, "id": item.get("id")})
    return classify_invoice_authority(invoices, readiness, lifecycle)
