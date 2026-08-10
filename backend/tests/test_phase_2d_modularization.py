import ast
from pathlib import Path

import server


LEGACY_ROUTE_PAIRS = {
    ("POST", "/api/auth/signup"), ("POST", "/api/auth/login"), ("GET", "/api/auth/me"),
    ("GET", "/api/trucks"), ("POST", "/api/trucks"), ("PUT", "/api/trucks/{tid}"),
    ("DELETE", "/api/trucks/{tid}"), ("GET", "/api/drivers"), ("POST", "/api/drivers"),
    ("PUT", "/api/drivers/{did}"), ("DELETE", "/api/drivers/{did}"),
    ("GET", "/api/loads"), ("GET", "/api/loads/{lid}"), ("POST", "/api/loads"),
    ("PUT", "/api/loads/{lid}"), ("DELETE", "/api/loads/{lid}"),
    ("POST", "/api/loads/{lid}/stage"), ("GET", "/api/activity"),
    ("GET", "/api/audit-events/incomplete"), ("GET", "/api/audit-events"),
    ("GET", "/api/documents"), ("POST", "/api/documents"),
    ("GET", "/api/invoices"), ("POST", "/api/invoices"), ("PUT", "/api/invoices/{iid}"),
    ("POST", "/api/routing/calc"), ("POST", "/api/weather/check"),
    ("POST", "/api/roads/check"), ("POST", "/api/samsara/vehicle"),
    ("POST", "/api/fuel/plan"), ("POST", "/api/truckstops/plan"),
    ("POST", "/api/alerts/generate"), ("POST", "/api/ai/chat"),
    ("GET", "/api/dashboard/stats"), ("GET", "/api/dashboard/charts"),
    ("POST", "/api/seed"), ("GET", "/api/assumptions"), ("PUT", "/api/assumptions"),
    ("POST", "/api/loads/analyze"), ("GET", "/api/compliance"),
    ("GET", "/api/"), ("GET", "/api/health/live"), ("GET", "/api/health/ready"),
}


def _route_pairs():
    pairs = []
    for router in (server.public_api, server.api):
        for route in router.routes:
            for method in getattr(route, "methods", set()):
                if method not in {"HEAD", "OPTIONS"}:
                    pairs.append((method, route.path))
    return pairs


def test_route_method_path_parity_and_no_duplicates():
    pairs = _route_pairs()
    assert len(pairs) == 169
    assert len(pairs) == len(set(pairs))
    assert LEGACY_ROUTE_PAIRS <= set(pairs)
    assert {("POST","/api/documents/upload"),("GET","/api/documents/{document_id}/download")} <= set(pairs)


def test_extracted_architecture_does_not_import_server_backwards():
    app_root = Path(__file__).parents[1] / "app"
    inspected = [*sorted((app_root / "api").glob("*_routes.py"))]
    inspected += [app_root / "runtime.py", app_root / "application" / "invoice_authority_query.py"]
    inspected += [app_root / "application" / "document_service.py",
                  app_root / "domain" / "document_evidence.py",
                  app_root / "infrastructure" / "document_storage.py",
                  app_root / "infrastructure" / "local_document_storage.py"]
    for path in inspected:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert "server" not in imports
        assert "backend.server" not in imports


def test_server_is_bootstrap_sized_and_deployment_entrypoint_is_preserved():
    server_path = Path(server.__file__)
    assert len(server_path.read_text(encoding="utf-8").splitlines()) < 150
    assert server.app is not None
    assert server.db is not None
    assert callable(server.get_current_user)
