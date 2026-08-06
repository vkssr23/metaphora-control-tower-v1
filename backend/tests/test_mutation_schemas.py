"""Pure, isolated tests for strict operational mutation contracts."""
import math
import pytest
from pydantic import ValidationError

from app.schemas import (
    AssumptionUpdate, DocumentCreate, DriverCreate, DriverUpdate, InvoiceCreate,
    InvoiceUpdate, LoadCreate, LoadUpdate, TruckCreate, TruckUpdate,
)


FRONTEND_LOAD = {"customer":"Acme", "broker":"Broker", "pickup_address":"Dallas", "pickup_city":"Dallas", "pickup_state":"TX", "delivery_address":"Atlanta", "delivery_city":"Atlanta", "delivery_state":"GA", "miles":900, "rate":2400, "est_drive_hours":16}

@pytest.mark.parametrize("model,payload", [
    (TruckUpdate, {"status":"Available", "unknown":1}),
    (DriverUpdate, {"status":"Available", "password":"hidden"}),
    (LoadUpdate, {"notes":"x", "created_at":"spoof"}),
    (DocumentCreate, {"load_id":"L1", "doc_type":"pod", "filename":"x.pdf", "url":"mock://x.pdf", "uploaded_by":"spoof"}),
    (InvoiceUpdate, {"status":"Paid", "_id":"spoof"}),
    (AssumptionUpdate, {"fuel_price":3, "id":"default"}),
])
def test_unknown_and_protected_fields_are_rejected(model, payload):
    with pytest.raises(ValidationError): model.model_validate(payload)

@pytest.mark.parametrize("model", [TruckUpdate, DriverUpdate, LoadUpdate, InvoiceUpdate, AssumptionUpdate])
def test_empty_updates_rejected(model):
    with pytest.raises(ValidationError): model.model_validate({})

def test_representative_frontend_payloads_pass():
    assert TruckCreate.model_validate({"truck_number":"TRK-1"}).truck_number == "TRK-1"
    assert TruckUpdate.model_validate({"status":"In Transit"}).status.value == "In Transit"
    assert DriverCreate.model_validate({"name":"Driver", "email":"USER@Example.com"}).email == "user@example.com"
    assert DriverCreate.model_validate({"name":"Driver"}).email == ""
    assert DriverCreate.model_validate({"name":"Driver", "email":""}).email == ""
    assert DriverUpdate.model_validate({"status":"Driving"}).status.value == "Driving"
    assert LoadCreate.model_validate(FRONTEND_LOAD).miles == 900
    assert LoadUpdate.model_validate({"driver_id":"D1", "truck_id":"T1"}).driver_id == "D1"
    assert InvoiceCreate.model_validate({"load_id":"L1", "amount":2400}).amount == 2400
    assert InvoiceUpdate.model_validate({"status":"Payment Pending"}).status.value == "Payment Pending"
    assert AssumptionUpdate.model_validate({"fuel_price":3.85, "mpg":6.5, "target_margin_pct":20}).mpg == 6.5

@pytest.mark.parametrize("model,payload", [
    (LoadCreate, {**FRONTEND_LOAD, "rate":-1}), (LoadCreate, {**FRONTEND_LOAD, "miles":-1}),
    (InvoiceCreate, {"load_id":"L1", "amount":-1}), (DriverCreate, {"name":"D", "cents_per_mile":-1}),
    (AssumptionUpdate, {"mpg":0}), (AssumptionUpdate, {"mpg":-1}),
    (AssumptionUpdate, {"target_margin_pct":100}), (AssumptionUpdate, {"factoring_fee_pct":100}),
    (AssumptionUpdate, {"factoring_fee_pct":-1}),
])
def test_invalid_numeric_ranges_rejected(model, payload):
    with pytest.raises(ValidationError): model.model_validate(payload)

@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("model,payload", [
    (LoadUpdate, {"rate":0}), (InvoiceUpdate, {"amount":0}), (AssumptionUpdate, {"fuel_price":0}),
])
def test_non_finite_numbers_rejected(model, payload, bad):
    key = next(iter(payload)); payload[key] = bad
    with pytest.raises(ValidationError): model.model_validate(payload)

def test_enums_dates_and_urls_are_strict():
    for model, payload in [(TruckUpdate,{"status":"Flying"}), (TruckUpdate,{"maintenance_status":"Maybe"}), (DriverUpdate,{"clearinghouse_status":"Claimed"}), (DriverUpdate,{"mvr_status":"Verified"}), (DriverUpdate,{"employment_verification":"Verified"}), (InvoiceUpdate,{"status":"Unknown"})]:
        with pytest.raises(ValidationError): model.model_validate(payload)
    with pytest.raises(ValidationError): InvoiceUpdate.model_validate({"due_date":"not-a-date"})
    for url in ["javascript:alert(1)", "data:text/plain,x", "file:///x", "ftp://example.com/x"]:
        with pytest.raises(ValidationError): DocumentCreate.model_validate({"load_id":"L1", "doc_type":"pod", "filename":"x.pdf", "url":url})
    assert DocumentCreate.model_validate({"load_id":"L1", "doc_type":"pod", "filename":"x.pdf", "url":"mock://x.pdf"})

@pytest.mark.parametrize("url,filename", [
    ("mock://other.pdf","x.pdf"), ("mock://user:pass@x.pdf","x.pdf"), ("mock://","x.pdf"),
    ("mock://x.pdf/path","x.pdf"), ("mock://x.pdf?query=1","x.pdf"), ("mock://x.pdf#fragment","x.pdf"),
    ("mock://../x.pdf","x.pdf"), ("mock://%2e%2e","x.pdf"), ("mock://x%0a.pdf","x.pdf"),
    ("https://user:pass@example.com/x.pdf","x.pdf"), ("https://example.com/x.pdf?query=1","x.pdf"),
    ("https://example.com/x.pdf#fragment","x.pdf"), (" https://example.com/x.pdf","x.pdf"),
    ("https://example.com/a/../x.pdf","x.pdf"), ("https://example.com/%2e%2e/x.pdf","x.pdf"),
    ("https://example.com/%0a.pdf","x.pdf"), ("https:////example.com/x.pdf","x.pdf"),
    ("https://example.com:99999/x.pdf","x.pdf"), ("http://example.com/x.pdf","x.pdf"),
])
def test_document_url_bypass_matrix(url, filename):
    with pytest.raises(ValidationError):
        DocumentCreate.model_validate({"load_id":"L1","doc_type":"pod","filename":filename,"url":url})

def test_exact_https_document_url_is_valid():
    assert DocumentCreate.model_validate({"load_id":"L1","doc_type":"pod","filename":"x.pdf","url":"https://example.com/docs/x.pdf"})

def test_stage_and_computed_fields_cannot_use_general_load_update():
    for field in ("stage", "rpm", "dispatcher", "updated_by", "profitability", "id", "_id"):
        with pytest.raises(ValidationError): LoadUpdate.model_validate({field:"spoof"})
    with pytest.raises(ValidationError): TruckUpdate.model_validate({"profit_per_mile":1.5})

def test_only_explicit_relationship_fields_can_be_cleared_with_null():
    assert LoadUpdate.model_validate({"driver_id":None}).driver_id is None
    assert TruckUpdate.model_validate({"assigned_driver_id":None}).assigned_driver_id is None
    with pytest.raises(ValidationError): LoadUpdate.model_validate({"customer":None})
    with pytest.raises(ValidationError): InvoiceUpdate.model_validate({"amount":None})

def test_driver_email_update_clears_to_historical_empty_string():
    assert DriverUpdate.model_validate({"email":""}).model_dump(exclude_unset=True)["email"] == ""
    with pytest.raises(ValidationError): DriverUpdate.model_validate({"email":None})
    with pytest.raises(ValidationError): DriverCreate.model_validate({"name":"Driver","email":"invalid"})

@pytest.mark.parametrize("model,payload", [
    (TruckCreate,{"truck_number":"T1","insurance_expiry":"x"*65}),
    (TruckUpdate,{"registration_expiry":"x"*65}),
    (TruckUpdate,{"annual_inspection_expiry":"x"*65}),
    (DriverCreate,{"name":"D","cdl_expiry":"x"*65}),
    (DriverUpdate,{"medical_expiry":"x"*65}),
    (LoadCreate,{**FRONTEND_LOAD,"pickup_appt":"x"*65}),
    (LoadUpdate,{"delivery_appt":"x"*65}),
    (InvoiceCreate,{"load_id":"L1","due_date":"x"*65}),
    (InvoiceUpdate,{"paid_date":"x"*65}),
])
def test_date_and_datetime_strings_are_bounded(model, payload):
    with pytest.raises(ValidationError): model.model_validate(payload)

def test_valid_iso_dates_remain_accepted():
    iso="2026-08-06T12:34:56+00:00"
    assert TruckUpdate.model_validate({"insurance_expiry":iso})
    assert DriverUpdate.model_validate({"medical_expiry":iso})
    assert LoadUpdate.model_validate({"pickup_appt":iso})
    assert InvoiceUpdate.model_validate({"due_date":iso})

@pytest.mark.parametrize("field", ["load_id","id","_id","created_at","updated_at","tenant_id","security_metadata","audit_metadata","updated_by","actor"])
def test_invoice_update_rejects_relationship_and_immutable_fields(field):
    with pytest.raises(ValidationError): InvoiceUpdate.model_validate({field:"blocked"})
