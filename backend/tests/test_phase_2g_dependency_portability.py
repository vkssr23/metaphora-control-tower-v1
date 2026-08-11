"""Phase 2G.2 portable-core and optional legacy AI isolation."""
from pathlib import Path
import os
import subprocess
import sys

os.environ.update({"JWT_SECRET":"isolated-test-only-secret-value-over-32-characters", "MONGO_URL":"mongodb://127.0.0.1:1/no-network-test", "DB_NAME":"isolated", "CORS_ORIGINS":"http://localhost:3000", "APP_ENV":"test", "ALLOW_SEED_ENDPOINT":"false"})

import app.api.demo_routes as demo_routes
import server
from test_mutation_endpoints import api


def test_core_manifest_and_startup_have_no_mandatory_emergent_dependency():
    requirements = (Path(__file__).parents[1] / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "emergentintegrations" not in requirements
    script = """\
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('emergentintegrations'):
            raise ModuleNotFoundError(fullname)
        return None
sys.meta_path.insert(0, Block())
import server
assert server.app is not None
"""
    env = {**os.environ, "JWT_SECRET":"subprocess-test-secret-value-over-32-characters", "MONGO_URL":"mongodb://127.0.0.1:1/no-network-test", "DB_NAME":"isolated", "CORS_ORIGINS":"http://localhost:3000", "APP_ENV":"test"}
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).parents[1], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_core_route_operates_and_legacy_ai_is_controlled_unavailable(api, monkeypatch):
    client, db, role = api
    role("owner")
    db.loads.docs = []
    assert client.get("/api/").status_code == 200
    calls = []
    def unavailable(name):
        calls.append(name)
        raise ModuleNotFoundError(name)
    monkeypatch.setattr(demo_routes, "import_module", unavailable)
    response = client.post("/api/ai/chat", json={"message": "hello"})
    assert response.status_code == 503
    assert response.json() == {"detail": "LEGACY_AI_PROVIDER_UNAVAILABLE"}
    assert calls == ["emergentintegrations.llm.chat"]
    assert db.loads.docs == []


def test_missing_provider_key_is_controlled_and_not_a_pilot_gate(api, monkeypatch):
    client, db, role = api
    role("owner")
    class Provider:
        class LlmChat: pass
        class UserMessage: pass
        class TextDelta: pass
        class StreamDone: pass
    monkeypatch.setattr(demo_routes, "import_module", lambda name: Provider)
    monkeypatch.delenv("EMERGENT_LLM_KEY", raising=False)
    response = client.post("/api/ai/chat", json={"message": "hello"})
    assert response.status_code == 503 and response.json()["detail"] == "LEGACY_AI_PROVIDER_UNAVAILABLE"
    from app.pilot_readiness import evaluate_pilot_readiness
    config = {"APP_ENV":"staging", "JWT_SECRET":"x"*40, "CORS_ORIGINS":"https://staging.example",
              "OFFLINE_REGRESSION_VERIFIED":"true", "GOLDEN_FLOW_VERIFIED":"true", "SECURITY_SUITE_VERIFIED":"true",
              "REAL_MONGO_VERIFIED":"true", "INDEXES_VERIFIED":"true", "GITHUB_CI_VERIFIED":"true",
              "MONGO_TOPOLOGY_VERIFIED":"true", "TRANSACTION_CAPABILITY_VERIFIED":"true", "PILOT_UOW_MODE_VERIFIED":"true",
              "REAL_MONGO_CONCURRENCY_VERIFIED":"true", "STAGING_ISOLATION_VERIFIED":"true", "DOCUMENT_DURABILITY_VERIFIED":"true",
              "STAGING_BACKEND_HEALTH_VERIFIED":"true", "STAGING_FRONTEND_HEALTH_VERIFIED":"true", "STAGING_AUTH_VERIFIED":"true",
              "STAGING_CORS_BEHAVIOR_VERIFIED":"true", "STAGING_GOLDEN_FLOW_VERIFIED":"true", "CROSS_TENANT_DOCUMENT_DENIAL_VERIFIED":"true",
              "NO_EXTERNAL_SUBMISSION_VERIFIED":"true", "BACKUP_RESTORE_VERIFIED":"true", "RESTORED_DOCUMENTS_VERIFIED":"true",
              "RESTORED_AUDIT_VERIFIED":"true", "PRODUCTION_INTEGRITY_VERIFIED":"true", "PERFORMANCE_SMOKE_VERIFIED":"true", "REQUEST_ID_VERIFIED":"true"}
    assert evaluate_pilot_readiness(config)["certification_levels"]["code_pilot_candidate"] == "pass"
