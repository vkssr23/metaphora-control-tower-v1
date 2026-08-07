"""Pure Phase 1B schema and deterministic comparison coverage; no database/network."""
import math, pytest
from pydantic import ValidationError
from app.schemas.rate_confirmations import ExtractionCreate, ExtractionUpdate, ConfidenceUpdate, ExtractedFields, ResolutionUpdate
from app.domain.rate_confirmations import compare_rate_confirmation, validate_corrected_value

LOAD={"rate":1200,"miles":500,"broker":"Acme Broker","customer":"REF-1","commodity":"Food","weight":42000,"equipment_type":"Dry Van","pickup_address":"1 Main St","pickup_city":"Chicago","pickup_state":"IL","pickup_zip":"60601","pickup_appt":"2026-08-10T08:00:00","delivery_address":"2 Oak St","delivery_city":"Boston","delivery_state":"MA","delivery_zip":"02108","delivery_appt":"2026-08-11T09:00:00"}
FIELDS={"total_rate":1200,"loaded_miles":500,"broker_name":"  ACME   broker ","customer_reference":"ref-1","commodity":"food","weight":42000,"equipment_type":"dry van","pickup_address":"1 Main St","pickup_city":"Chicago","pickup_state":"IL","pickup_postal_code":"60601","pickup_date":"2026-08-10","pickup_time_start":"08:00","delivery_address":"2 Oak St","delivery_city":"Boston","delivery_state":"MA","delivery_postal_code":"02108","delivery_date":"2026-08-11","delivery_time_start":"09:00"}

def test_exact_and_normalized_match_is_deterministic():
    a=compare_rate_confirmation(FIELDS,LOAD,"fixed"); b=compare_rate_confirmation(FIELDS,LOAD,"fixed")
    assert a==b and a["comparison_status"]=="match" and not a["discrepancies"]
def test_rate_mileage_location_and_required_discrepancies():
    r=compare_rate_confirmation({"total_rate":1000,"loaded_miles":550,"pickup_address":"Wrong","delivery_address":"Wrong","broker_name":"Other"},LOAD,"fixed")
    kinds={d["type"] for d in r["discrepancies"]}
    assert {"total_rate_mismatch","mileage_mismatch","pickup_location_mismatch","delivery_location_mismatch","broker_name_mismatch"}<=kinds
    assert all(x in r["blocking_discrepancy_types"] for x in ("total_rate_mismatch","pickup_location_mismatch","delivery_location_mismatch"))
def test_missing_required_document_fields():
    r=compare_rate_confirmation({},LOAD,"fixed")
    assert {"missing_rate","missing_pickup","missing_delivery"}<={d["type"] for d in r["discrepancies"]}
def test_strict_fields_and_validation():
    with pytest.raises(ValidationError): ExtractedFields.model_validate({"unknown":1})
    with pytest.raises(ValidationError): ExtractedFields(total_rate=math.inf)
    with pytest.raises(ValidationError): ExtractedFields(document_date="not-a-date")
    with pytest.raises(ValidationError): ExtractedFields(broker_contact_email="invalid")
    with pytest.raises(ValidationError): ExtractedFields(special_instructions="x"*2001)
def test_future_sources_protected_fields_and_confidence_rejected():
    with pytest.raises(ValidationError): ExtractionCreate(document_id="D",source="future_ocr")
    with pytest.raises(ValidationError): ExtractionCreate(document_id="D",tenant_id="spoof")
    with pytest.raises(ValidationError): ExtractionCreate(document_id="D",source="manual",extraction_confidence={"total_rate":.9})
    with pytest.raises(ValidationError): ExtractionCreate(document_id="D",source="structured_import",extraction_confidence={"total_rate":1.1})
def test_waiver_and_corrected_value_require_contract():
    with pytest.raises(ValidationError): ResolutionUpdate(resolution="waived",decision="keep_load_value",reason="")
    with pytest.raises(ValidationError): ResolutionUpdate(resolution="corrected_load",decision="corrected_value")
def test_general_update_excludes_confidence_and_dedicated_contract_is_bounded():
    with pytest.raises(ValidationError): ExtractionUpdate.model_validate({"extraction_confidence":{"total_rate":.5}})
    assert ConfidenceUpdate(extraction_confidence={"total_rate":.5}).extraction_confidence=={"total_rate":.5}
    for value in (-.1,1.1,math.nan,math.inf):
        with pytest.raises(ValidationError): ConfidenceUpdate(extraction_confidence={"total_rate":value})
def test_corrected_value_controlled_validation():
    valid={"total_rate":1300,"loaded_miles":550,"weight":41000,"pickup_date":"2026-08-10","pickup_time_start":"08:30","delivery_date":"2026-08-11","delivery_time_start":"09:45","broker_name":"Broker","customer_reference":"Customer","commodity":"Produce","equipment_type":"Reefer"}
    for field,value in valid.items(): assert validate_corrected_value(field,value) is not None
    invalid={"total_rate":-1,"loaded_miles":math.inf,"weight":"heavy","pickup_date":"tomorrow","pickup_time_start":"25:00","delivery_date":"bad","delivery_time_start":"noon","broker_name":"x"*201,"customer_reference":"x"*151,"commodity":"x"*201,"equipment_type":"spaceship"}
    for field,value in invalid.items():
        with pytest.raises(ValueError): validate_corrected_value(field,value)
    with pytest.raises(ValueError): validate_corrected_value("arbitrary.mongo.path",1)
