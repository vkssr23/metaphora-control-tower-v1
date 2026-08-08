"""Phase 2C classification of legacy and modern invoice authority."""
from enum import StrEnum


class InvoiceAuthority(StrEnum):
    LEGACY = "legacy"
    MODERN = "modern"
    MODERN_INCOMPLETE = "modern_incomplete"
    AMBIGUOUS = "ambiguous"
    UNVERIFIABLE = "unverifiable"


def is_modern_invoice(invoice):
    return bool(invoice and invoice.get("readiness_case_id") and invoice.get("package_id"))


def has_modern_binding(invoice):
    """Any Phase 1G binding is modern evidence, even when malformed."""
    return bool(invoice and (invoice.get("readiness_case_id") or invoice.get("package_id")))


def classify_invoice_authority(invoices=(), readiness_cases=(), lifecycle_records=()):
    invoices=tuple(invoices);readiness_cases=tuple(readiness_cases);lifecycle_records=tuple(lifecycle_records)
    complete=any(is_modern_invoice(item) for item in invoices)
    incomplete=any(has_modern_binding(item) and not is_modern_invoice(item) for item in invoices)
    modern_context=complete or incomplete or bool(readiness_cases) or bool(lifecycle_records)
    legacy=any(not has_modern_binding(item) for item in invoices)
    if legacy and modern_context:
        return InvoiceAuthority.AMBIGUOUS
    if incomplete:
        return InvoiceAuthority.MODERN_INCOMPLETE
    if modern_context:
        return InvoiceAuthority.MODERN
    if legacy:
        return InvoiceAuthority.LEGACY
    # No evidence is not proof of historical legacy provenance. New writes fail closed.
    return InvoiceAuthority.UNVERIFIABLE


def legacy_write_allowed(authority):
    return InvoiceAuthority(authority) == InvoiceAuthority.LEGACY
