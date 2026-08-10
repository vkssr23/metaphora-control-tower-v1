"""Secret-free, deterministic controlled-staging readiness evaluation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from app.config import parse_cors_origins, validate_jwt_secret

PASS = "pass"
BLOCKED = "blocked"
CONDITIONAL = "conditional"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Gate:
    gate: str
    status: str
    code: str
    reason: str
    next_step: str
    severity: str = "P1"


def _flag(values: Mapping[str, str], name: str) -> bool:
    return str(values.get(name, "")).strip().lower() in {"1", "true", "yes", "verified", "pass"}


def evaluate_pilot_readiness(values: Mapping[str, str]) -> dict:
    """Evaluate observable configuration plus explicit, non-secret evidence flags."""
    gates: list[Gate] = []
    app_env = str(values.get("APP_ENV", "")).strip().lower()
    if app_env in {"test", "staging", "pilot"}:
        gates.append(Gate("environment", PASS, "APP_ENV_SAFE", "Explicit non-production pilot environment.", "Keep environment isolation enforced."))
    else:
        gates.append(Gate("environment", BLOCKED, "APP_ENV_UNSAFE", "APP_ENV is missing or not an approved pilot environment.", "Set APP_ENV to staging/pilot/test.", "P0"))

    try:
        validate_jwt_secret(values.get("JWT_SECRET"))
        gates.append(Gate("jwt", PASS, "JWT_SECRET_STRONG", "JWT signing configuration meets the current minimum policy.", "Rotate under the staging secret procedure."))
    except RuntimeError:
        gates.append(Gate("jwt", BLOCKED, "JWT_SECRET_UNSAFE", "JWT signing configuration is missing, weak, or default.", "Provision a unique secret of at least 32 characters.", "P0"))

    try:
        origins = parse_cors_origins(values.get("CORS_ORIGINS"))
        if not origins:
            raise RuntimeError("empty")
        gates.append(Gate("cors", PASS, "CORS_EXPLICIT", "CORS uses explicit HTTP(S) origins.", "Keep staging origins narrowly scoped."))
    except RuntimeError:
        gates.append(Gate("cors", BLOCKED, "CORS_UNSAFE", "CORS is missing, malformed, or non-explicit.", "Configure explicit staging origins.", "P0"))

    seed = _flag(values, "ALLOW_SEED_ENDPOINT")
    gates.append(Gate("seed", BLOCKED if seed else PASS, "SEED_EXPOSED" if seed else "SEED_DISABLED",
        "Seed endpoint is enabled in a pilot environment." if seed else "Seed endpoint is disabled.",
        "Disable ALLOW_SEED_ENDPOINT before staging." if seed else "Keep disabled.", "P0" if seed else "P1"))

    backend = str(values.get("DOCUMENT_STORAGE_BACKEND", "local")).strip().lower()
    if backend == "local":
        gates.append(Gate("document_storage", CONDITIONAL, "LOCAL_PILOT_ONLY", "Local immutable storage is supported but is single-host pilot infrastructure.", "Bind durable restricted storage and include it in backup/restore.", "P2"))
    else:
        gates.append(Gate("document_storage", BLOCKED, "DOCUMENT_BACKEND_UNSUPPORTED", "Configured document backend is unsupported by this release.", "Use the supported controlled local backend.", "P0"))

    evidence = (
        ("offline_regression", "OFFLINE_REGRESSION_VERIFIED", "Run the approved offline regression."),
        ("golden_flow", "GOLDEN_FLOW_VERIFIED", "Run the Phase 2G Golden Freight Flow."),
        ("security_suite", "SECURITY_SUITE_VERIFIED", "Run the Phase 2G adversarial suite."),
        ("real_mongo", "REAL_MONGO_VERIFIED", "Execute the disposable real-Mongo harness."),
        ("indexes", "INDEXES_VERIFIED", "Verify manifest indexes on disposable/staging Mongo."),
        ("transactions", "TRANSACTIONS_VERIFIED", "Record the staging topology transaction probe."),
        ("backup_restore", "BACKUP_RESTORE_VERIFIED", "Execute and validate a staging restore drill."),
    )
    for gate, key, step in evidence:
        ok = _flag(values, key)
        gates.append(Gate(gate, PASS if ok else UNKNOWN, f"{gate.upper()}_{'VERIFIED' if ok else 'NOT_VERIFIED'}",
                          "Evidence verified." if ok else "Mandatory staging evidence has not been verified.", step))

    blockers = [g for g in gates if g.status in {BLOCKED, UNKNOWN}]
    overall = "ready" if not blockers else "blocked"
    by_name = {g.gate: g for g in gates}
    code_names = {"environment", "jwt", "cors", "seed", "document_storage", "offline_regression", "golden_flow", "security_suite"}
    code_ready = not any(by_name[name].status in {BLOCKED, UNKNOWN} for name in code_names)
    staging_ready = not blockers
    return {
        "scope": "controlled_staging_carrier_pilot",
        "status": overall,
        "verdict": "PILOT READY FOR CONTROLLED STAGING" if overall == "ready" else "NOT PILOT READY — BLOCKERS REMAIN",
        "gates": [asdict(g) for g in gates],
        "blocker_codes": [g.code for g in blockers],
        "limitations": [g.code for g in gates if g.status == CONDITIONAL],
        "certification_levels": {
            "code_pilot_candidate": "pass" if code_ready else "blocked",
            "controlled_staging_ready": "pass" if staging_ready else "blocked",
            "customer_pilot_ready": "not_evaluated" if not staging_ready else "requires_operational_acceptance",
        },
        "secrets_included": False,
    }
