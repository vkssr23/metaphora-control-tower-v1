import json

from app.pilot_readiness import evaluate_pilot_readiness
from scripts.pilot_readiness_report import main


SAFE = {
    "APP_ENV": "staging", "JWT_SECRET": "x" * 40,
    "CORS_ORIGINS": "https://staging.metaphora.example",
    "ALLOW_SEED_ENDPOINT": "false", "DOCUMENT_STORAGE_BACKEND": "local",
    "OFFLINE_REGRESSION_VERIFIED": "true", "GOLDEN_FLOW_VERIFIED": "true",
    "SECURITY_SUITE_VERIFIED": "true", "REAL_MONGO_VERIFIED": "true",
    "INDEXES_VERIFIED": "true", "TRANSACTIONS_VERIFIED": "true",
    "BACKUP_RESTORE_VERIFIED": "true",
}


def test_all_mandatory_evidence_is_ready_with_controlled_local_limitation():
    result = evaluate_pilot_readiness(SAFE)
    assert result["status"] == "ready"
    assert result["verdict"] == "PILOT READY FOR CONTROLLED STAGING"
    assert result["limitations"] == ["LOCAL_PILOT_ONLY"]
    assert result["certification_levels"]["code_pilot_candidate"] == "pass"
    assert result["certification_levels"]["controlled_staging_ready"] == "pass"
    assert not result["secrets_included"]


def test_critical_config_and_unknown_evidence_fail_closed():
    for change, code in [({"JWT_SECRET": "secret"}, "JWT_SECRET_UNSAFE"),
                         ({"CORS_ORIGINS": "*"}, "CORS_UNSAFE"),
                         ({"ALLOW_SEED_ENDPOINT": "true"}, "SEED_EXPOSED"),
                         ({"APP_ENV": "production"}, "APP_ENV_UNSAFE"),
                         ({"DOCUMENT_STORAGE_BACKEND": "s3"}, "DOCUMENT_BACKEND_UNSUPPORTED")]:
        result = evaluate_pilot_readiness({**SAFE, **change})
        assert result["status"] == "blocked" and code in result["blocker_codes"]
    unknown = evaluate_pilot_readiness({**SAFE, "REAL_MONGO_VERIFIED": "false"})
    assert "REAL_MONGO_NOT_VERIFIED" in unknown["blocker_codes"]
    assert unknown["certification_levels"] == {"code_pilot_candidate": "pass", "controlled_staging_ready": "blocked", "customer_pilot_ready": "not_evaluated"}


def test_report_json_is_bounded_and_never_serializes_secret(monkeypatch, capsys):
    for key, value in SAFE.items():
        monkeypatch.setenv(key, value)
    secret = SAFE["JWT_SECRET"]
    assert main(["--json"]) == 0
    output = capsys.readouterr().out
    parsed = json.loads(output)
    assert parsed["status"] == "ready" and secret not in output and "MONGO_URI" not in output
