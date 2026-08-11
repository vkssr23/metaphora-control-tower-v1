"""Focused adversarial invariants complementing route-level Phase 0D–2F suites."""
import pytest

from app.config import parse_cors_origins, validate_jwt_secret
from app.domain.document_evidence import DocumentValidationError, safe_original_filename, validate_content
from app.permissions import can_acknowledge_action


def test_role_escalation_matrix_fails_closed():
    users = {role: {"role": role} for role in ("operations", "safety", "finance", "viewer", "owner", "admin")}
    policies = [
        ({"owner_role": "safety", "category": "fraud_risk"}, {"safety", "owner", "admin"}),
        ({"owner_role": "finance", "category": "finance"}, {"finance", "owner", "admin"}),
        ({"owner_role": "admin", "category": "platform_integrity"}, {"owner", "admin"}),
    ]
    for action, allowed in policies:
        assert {r for r, user in users.items() if can_acknowledge_action(user, action)} == allowed
    assert not can_acknowledge_action(users["operations"], {"owner_role": "operations", "category": "finance"})


@pytest.mark.parametrize("mime,data", [("application/pdf", b"not pdf"), ("image/png", b"%PDF-1.7")])
def test_document_injection_signature_mismatch_is_denied(mime, data):
    with pytest.raises(DocumentValidationError):
        validate_content(mime, data)


def test_path_and_crlf_names_are_neutralized_and_configuration_attacks_denied():
    assert safe_original_filename("../../pod.pdf") == "pod.pdf"
    assert "\r" not in safe_original_filename("pod.pdf\r\nX-Leak: yes")
    for unsafe in ("*", "https://good.example, https://*.evil.example"):
        with pytest.raises(RuntimeError): parse_cors_origins(unsafe)
    for unsafe in (None, "secret", "dev_secret"):
        with pytest.raises(RuntimeError): validate_jwt_secret(unsafe)
