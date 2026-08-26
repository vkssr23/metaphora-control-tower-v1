"""Proves the corrected uq_tenants_metaphora_org_id partial filter excludes
missing/null/empty values and includes real linked-org strings.

MongoDB partial filter expressions only support a small allowlist of
operators (equality, $exists, $gt/$gte/$lt/$lte, $type — no $regex), so
this test evaluates the manifest's actual filter dict against representative
documents using the same operator semantics MongoDB itself applies, rather
than re-deriving the filter by hand.
"""
from app.infrastructure.index_manifest import expected_indexes

FILTER = next(x.partial_filter for x in expected_indexes() if x.name == "uq_tenants_metaphora_org_id")


def _matches(doc: dict, filt: dict) -> bool:
    for field, predicate in filt.items():
        value = doc.get(field, "__MISSING__")
        for op, expected in predicate.items():
            if op == "$type":
                if expected == "string":
                    if value == "__MISSING__" or not isinstance(value, str):
                        return False
                else:
                    raise NotImplementedError(op)
            elif op == "$gt":
                if value == "__MISSING__" or not isinstance(value, str) or not value > expected:
                    return False
            else:
                raise NotImplementedError(op)
    return True


def test_filter_definition_uses_type_and_gt_not_bare_exists():
    assert FILTER == {"metaphora_org_id": {"$type": "string", "$gt": ""}}


def test_filter_excludes_missing_field():
    assert _matches({"id": "t1"}, FILTER) is False


def test_filter_excludes_explicit_null():
    assert _matches({"id": "t1", "metaphora_org_id": None}, FILTER) is False


def test_filter_excludes_empty_string():
    assert _matches({"id": "t1", "metaphora_org_id": ""}, FILTER) is False


def test_filter_includes_valid_id():
    assert _matches({"id": "t1", "metaphora_org_id": "42"}, FILTER) is True


def test_filter_cannot_express_whitespace_exclusion():
    """Documented limitation: $regex is not allowed in partial filter
    expressions, so "   " still matches $type:"string" + $gt:"". Whitespace
    is excluded at the write boundary (auth_routes.py strips + validates
    verify_org_id before insert), not by the index itself."""
    assert _matches({"id": "t1", "metaphora_org_id": "   "}, FILTER) is True
