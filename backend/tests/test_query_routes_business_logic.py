"""
Deterministic FakeDB replacement coverage for the business-logic behavior
test_metaphora.py used to check live against a now-dead third-party URL,
using demo credentials this app's own security hardening has since removed
(see test_auth_signup.py / test_metaphora.py's skip reasoning).

This does NOT replace test_metaphora.py's route-existence coverage alone --
it replaces the actual *business logic* each skipped test was really
checking, using the same isolated FakeDB + dependency_overrides pattern
already established in test_mutation_endpoints.py/test_tenant_isolation.py,
rather than a live server + demo login. Mapping:

  test_root_app_name                    -> covered elsewhere (route allowlist,
                                            test_security_patch.py); response
                                            *content* has no other test --
                                            not duplicated here since it's a
                                            static literal, not business logic
  test_get_assumptions_defaults         -> test_assumptions_defaults_are_returned_and_persisted
  test_put_assumptions_persists         -> test_assumptions_defaults_are_returned_and_persisted
  test_analyze_profitable_load          -> test_analyze_profitable_load_books_green
  test_analyze_bad_load_rejected_or_negotiate -> test_analyze_thin_margin_load_is_negotiate_or_reject
  test_analyze_invalid_miles            -> test_analyze_zero_miles_is_400
  test_compliance_structure             -> test_compliance_overview_structure_and_severity
  test_drivers_have_compliance_fields   -> test_compliance_overview_structure_and_severity
                                            (same fixture proves the fields
                                            are read and drive real output)
  test_trucks_have_inspection_field     -> test_compliance_overview_structure_and_severity
  test_dashboard_stats                  -> test_dashboard_stats_reflects_seeded_data
  test_loads_list                       -> covered by test_tenant_isolation.py's
                                            tenant-scoped list assertions;
                                            not duplicated here
  test_invoices_list                    -> covered by test_tenant_isolation.py's
                                            tenant-scoped list assertions;
                                            not duplicated here
"""
import os
from datetime import datetime, timedelta, timezone

os.environ.update({"JWT_SECRET": "isolated-test-only-secret-value-over-32-characters",
                    "MONGO_URL": "mongodb://127.0.0.1:1/no-network-test", "DB_NAME": "isolated",
                    "CORS_ORIGINS": "http://localhost:3000", "APP_ENV": "test", "ALLOW_SEED_ENDPOINT": "false"})

import pytest
from fastapi.testclient import TestClient

import server
# test_mutation_endpoints's Collection.find() only accepts a query
# positionally; query_routes.py's dashboard/compliance handlers call
# db.<collection>.find(scope, {"_id": 0}) with a second positional
# projection arg, so this reuses test_rate_confirmation_routes's more
# permissive Collection (query=None, *args, **kwargs) instead.
from test_rate_confirmation_routes import Collection

VALID_TENANT = "ten_" + "a" * 32

ISO = lambda days: (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


class FakeDB:
    def __init__(self):
        events = []
        for name in ("users", "tenants", "loads", "activity", "audit_events",
                     "trucks", "drivers", "documents", "invoices", "assumptions"):
            setattr(self, name, Collection(name, events))


@pytest.fixture
def api(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(server, "db", fake)
    server.app.dependency_overrides.clear()

    def role(name):
        async def dependency():
            return {"id": f"U-{name}", "name": "Authenticated Actor", "role": name, "tenant_id": VALID_TENANT}
        server.app.dependency_overrides[server.get_current_user] = dependency

    yield TestClient(server.app), fake, role
    server.app.dependency_overrides.clear()


def test_assumptions_defaults_are_returned_and_persisted(api):
    client, db, role = api
    role("owner")

    defaults = client.get("/api/assumptions").json()
    assert defaults["fuel_price"] == 3.85 and defaults["mpg"] == 6.5
    assert defaults["target_margin_pct"] == 20 and defaults["min_rpm"] == 1.85

    role("finance")
    payload = {"fuel_price": 4.10, "mpg": 6.8, "driver_pay_solo_cpm": 0.62,
               "driver_pay_team_cpm": 0.92, "insurance_per_week": 360, "rental_per_week": 410,
               "factoring_fee_pct": 3.1, "default_toll": 65, "target_margin_pct": 22,
               "min_rpm": 1.9, "min_net_profit": 420}
    assert client.put("/api/assumptions", json=payload).status_code == 200

    role("owner")
    updated = client.get("/api/assumptions").json()
    assert abs(updated["fuel_price"] - 4.10) < 0.001
    assert updated["target_margin_pct"] == 22


def test_analyze_profitable_load_books_green(api):
    client, db, role = api
    role("owner")
    resp = client.post("/api/loads/analyze", json={
        "offered_rate": 2400, "loaded_miles": 900, "deadhead_miles": 80, "driver_type": "Solo"
    })
    assert resp.status_code == 200, resp.text
    d = resp.json()
    assert d["decision"] == "Book"
    assert d["risk"] == "Green"
    assert d["net_profit"] > 0
    assert d["target_rate"] > d["min_acceptable_rate"] > 0
    for k in ["fuel_cost", "driver_pay", "tolls", "insurance", "factoring", "margin_pct",
              "rpm", "score", "reasoning"]:
        assert k in d


def test_analyze_thin_margin_load_is_negotiate_or_reject(api):
    client, db, role = api
    role("owner")
    resp = client.post("/api/loads/analyze", json={
        "offered_rate": 800, "loaded_miles": 900, "deadhead_miles": 200, "driver_type": "Solo"
    })
    assert resp.status_code == 200
    d = resp.json()
    assert d["decision"] in ("Reject", "Negotiate")
    assert d["risk"] in ("Red", "Yellow")


def test_analyze_zero_miles_is_400(api):
    client, db, role = api
    role("owner")
    resp = client.post("/api/loads/analyze", json={
        "offered_rate": 1000, "loaded_miles": 0, "deadhead_miles": 0
    })
    assert resp.status_code == 400


def test_compliance_overview_structure_and_severity(api):
    client, db, role = api
    role("owner")
    db.drivers.docs = [
        {"id": "D1", "tenant_id": VALID_TENANT, "name": "Clean Driver", "cdl_expiry": ISO(365), "medical_expiry": ISO(365),
         "mvr_status": "Clear", "clearinghouse_status": "Clear", "employment_verification": "Complete"},
        {"id": "D2", "tenant_id": VALID_TENANT, "name": "Expired Driver", "cdl_expiry": ISO(-5), "medical_expiry": ISO(365),
         "mvr_status": "Clear", "clearinghouse_status": "Clear", "employment_verification": "Complete"},
    ]
    db.trucks.docs = [
        {"id": "T1", "tenant_id": VALID_TENANT, "truck_number": "T-100", "insurance_expiry": ISO(365),
         "registration_expiry": ISO(365), "annual_inspection_expiry": ISO(365), "maintenance_status": "Good"},
        {"id": "T2", "tenant_id": VALID_TENANT, "truck_number": "T-200", "insurance_expiry": ISO(365),
         "registration_expiry": ISO(365), "annual_inspection_expiry": ISO(-10), "maintenance_status": "Good"},
    ]

    resp = client.get("/api/compliance")
    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data and "items" in data
    s = data["summary"]
    for k in ["total", "green", "yellow", "red", "dispatch_blocked"]:
        assert k in s
    assert s["total"] == len(data["items"]) == 4
    assert s["red"] > 0
    assert s["green"] + s["yellow"] + s["red"] == s["total"]

    driver_item = next(i for i in data["items"] if i["entity_id"] == "D2")
    assert driver_item["entity_type"] == "Driver" and driver_item["status"] == "Red"
    assert driver_item["dispatch_allowed"] is False
    assert any("CDL expired" in b for b in driver_item["blockers"])
    for k in ["cdl_expiry", "cdl_days", "medical_expiry", "medical_days",
              "mvr_status", "clearinghouse_status", "employment_verification"]:
        assert k in driver_item["details"]

    truck_item = next(i for i in data["items"] if i["entity_id"] == "T2")
    assert truck_item["entity_type"] == "Truck" and truck_item["status"] == "Red"
    assert any("inspection expired" in b for b in truck_item["blockers"])
    assert "inspection_expiry" in truck_item["details"] and "inspection_days" in truck_item["details"]

    clean_driver = next(i for i in data["items"] if i["entity_id"] == "D1")
    assert clean_driver["status"] == "Green" and clean_driver["dispatch_allowed"] is True


def test_dashboard_stats_reflects_seeded_data(api):
    client, db, role = api
    role("owner")
    db.loads.docs = [
        {"id": "L1", "tenant_id": VALID_TENANT, "stage": "Booked", "rate": 1000, "fuel_cost": 100, "tolls": 20,
         "lumper": 0, "driver_pay": 300, "factoring_fee": 30, "other_expenses": 0, "miles": 500},
        {"id": "L2", "tenant_id": VALID_TENANT, "stage": "Closed", "rate": 2000, "fuel_cost": 200, "tolls": 40,
         "lumper": 0, "driver_pay": 600, "factoring_fee": 60, "other_expenses": 0, "miles": 900},
    ]
    db.trucks.docs = [{"id": "T1", "tenant_id": VALID_TENANT, "status": "Available"}, {"id": "T2", "tenant_id": VALID_TENANT, "status": "Idle"}]
    db.drivers.docs = [{"id": "D1", "tenant_id": VALID_TENANT, "status": "Available"}, {"id": "D2", "tenant_id": VALID_TENANT, "status": "Assigned"}]
    db.invoices.docs = [{"id": "I1", "tenant_id": VALID_TENANT, "status": "Payment Pending", "amount": 500}]

    resp = client.get("/api/dashboard/stats")
    assert resp.status_code == 200
    data = resp.json()
    for k in ["total_revenue", "active_loads", "active_trucks", "active_drivers"]:
        assert k in data
    assert data["total_revenue"] == 3000
    assert data["active_loads"] == 1  # Closed is excluded
    assert data["active_trucks"] == 1  # Idle excluded
    assert data["active_drivers"] == 2
    assert data["loads_closed"] == 1
