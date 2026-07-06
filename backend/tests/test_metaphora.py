"""Backend tests for Metaphora Control Tower rebrand + new endpoints."""
import os
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://dispatch-control-28.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def owner_token(session):
    r = session.post(f"{API}/auth/login", json={"email": "owner@dispatch.com", "password": "owner123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="session", autouse=True)
def seed_once(session):
    r = session.post(f"{API}/seed?force=true")
    assert r.status_code == 200


# --- Rebrand root ---
def test_root_app_name(session):
    r = session.get(f"{API}/")
    assert r.status_code == 200
    data = r.json()
    assert data["app"] == "Metaphora Control Tower"
    assert data["status"] == "operational"


# --- Assumptions ---
def test_get_assumptions_defaults(session):
    r = session.get(f"{API}/assumptions")
    assert r.status_code == 200
    a = r.json()
    for k in ["fuel_price", "mpg", "driver_pay_solo_cpm", "target_margin_pct", "min_rpm"]:
        assert k in a, f"missing key {k}"
    assert a["fuel_price"] > 0
    assert a["mpg"] > 0


def test_put_assumptions_persists(session):
    payload = {"fuel_price": 4.10, "mpg": 6.8, "driver_pay_solo_cpm": 0.62,
               "driver_pay_team_cpm": 0.92, "insurance_per_week": 360, "rental_per_week": 410,
               "factoring_fee_pct": 3.1, "default_toll": 65, "target_margin_pct": 22,
               "min_rpm": 1.9, "min_net_profit": 420}
    r = session.put(f"{API}/assumptions", json=payload)
    assert r.status_code == 200
    r2 = session.get(f"{API}/assumptions")
    a = r2.json()
    assert abs(a["fuel_price"] - 4.10) < 0.001
    assert abs(a["mpg"] - 6.8) < 0.001
    assert a["target_margin_pct"] == 22
    # reset to defaults so subsequent decision tests use expected
    reset = {"fuel_price": 3.85, "mpg": 6.5, "driver_pay_solo_cpm": 0.60,
             "driver_pay_team_cpm": 0.90, "insurance_per_week": 350, "rental_per_week": 400,
             "factoring_fee_pct": 3.0, "default_toll": 60, "target_margin_pct": 20,
             "min_rpm": 1.85, "min_net_profit": 400}
    session.put(f"{API}/assumptions", json=reset)


# --- Load Decision Engine ---
def test_analyze_profitable_load(session):
    r = session.post(f"{API}/loads/analyze", json={
        "offered_rate": 2400, "loaded_miles": 900, "deadhead_miles": 80, "driver_type": "Solo"
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["decision"] == "Book"
    assert d["risk"] == "Green"
    assert d["net_profit"] > 0
    assert d["target_rate"] > d["min_acceptable_rate"] > 0
    for k in ["fuel_cost", "driver_pay", "tolls", "insurance", "factoring", "margin_pct",
              "rpm", "score", "reasoning"]:
        assert k in d


def test_analyze_bad_load_rejected_or_negotiate(session):
    r = session.post(f"{API}/loads/analyze", json={
        "offered_rate": 800, "loaded_miles": 900, "deadhead_miles": 200, "driver_type": "Solo"
    })
    assert r.status_code == 200
    d = r.json()
    assert d["decision"] in ("Reject", "Negotiate")
    assert d["risk"] in ("Red", "Yellow")


def test_analyze_invalid_miles(session):
    r = session.post(f"{API}/loads/analyze", json={
        "offered_rate": 1000, "loaded_miles": 0, "deadhead_miles": 0
    })
    assert r.status_code == 400


# --- Compliance ---
def test_compliance_structure(session):
    r = session.get(f"{API}/compliance")
    assert r.status_code == 200
    data = r.json()
    assert "summary" in data and "items" in data
    s = data["summary"]
    for k in ["total", "green", "yellow", "red", "dispatch_blocked"]:
        assert k in s
    assert s["total"] == len(data["items"])
    # Should have a mix
    assert s["red"] > 0
    assert s["green"] + s["yellow"] + s["red"] == s["total"]
    # Sample structure
    it = data["items"][0]
    for k in ["entity_type", "entity_id", "entity_name", "status", "blockers",
              "warnings", "dispatch_allowed", "details"]:
        assert k in it


# --- Extended seed fields ---
def test_drivers_have_compliance_fields(session):
    r = session.get(f"{API}/drivers")
    assert r.status_code == 200
    drivers = r.json()
    assert len(drivers) > 0
    d = drivers[0]
    for k in ["cdl_expiry", "medical_expiry", "mvr_status", "clearinghouse_status"]:
        assert k in d, f"missing {k} in driver"


def test_trucks_have_inspection_field(session):
    r = session.get(f"{API}/trucks")
    assert r.status_code == 200
    trucks = r.json()
    assert len(trucks) > 0
    assert "annual_inspection_expiry" in trucks[0]


# --- Regression basics ---
def test_dashboard_stats(session):
    r = session.get(f"{API}/dashboard/stats")
    assert r.status_code == 200
    for k in ["total_revenue", "active_loads", "active_trucks", "active_drivers"]:
        assert k in r.json()


def test_loads_list(session):
    r = session.get(f"{API}/loads")
    assert r.status_code == 200
    assert len(r.json()) >= 10


def test_invoices_list(session):
    r = session.get(f"{API}/invoices")
    assert r.status_code == 200
