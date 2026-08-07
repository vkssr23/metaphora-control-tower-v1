"""Pure deterministic Phase 1B rate-confirmation comparison rules."""
from datetime import datetime, timezone
import re, uuid
from pydantic import ValidationError
from app.schemas.rate_confirmations import ExtractedFields

BLOCKING={"total_rate_mismatch","pickup_date_mismatch","delivery_date_mismatch","pickup_location_mismatch","delivery_location_mismatch","broker_name_mismatch","broker_mc_mismatch","equipment_type_mismatch","missing_rate","missing_pickup","missing_delivery"}
MATERIAL=BLOCKING|{"mileage_mismatch","linehaul_rate_mismatch","commodity_mismatch","weight_mismatch","customer_reference_mismatch","duplicate_or_changed_rate_confirmation"}
FINANCIAL={"total_rate_mismatch","linehaul_rate_mismatch","missing_rate"}
LOAD_FIELD_MAP={"total_rate":"rate","loaded_miles":"miles","deadhead_miles":"deadhead_miles","broker_name":"broker","customer_reference":"customer","commodity":"commodity","weight":"weight","equipment_type":"equipment_type","rate_confirmation_number":"rate_con_number","pickup_address":"pickup_address","pickup_city":"pickup_city","pickup_state":"pickup_state","pickup_postal_code":"pickup_zip","delivery_address":"delivery_address","delivery_city":"delivery_city","delivery_state":"delivery_state","delivery_postal_code":"delivery_zip"}
CORRECTABLE_FIELDS=frozenset(LOAD_FIELD_MAP)|{"pickup_date","pickup_time_start","delivery_date","delivery_time_start"}
EQUIPMENT_TYPES=frozenset({"dry van","reefer","flatbed","step deck","power only","box truck","tanker","container","lowboy","conestoga","other"})
def validate_corrected_value(field,value):
    """Validate one correction through the controlled extraction/canonical vocabulary."""
    if field not in CORRECTABLE_FIELDS: raise ValueError("Unsupported corrected field")
    if field=="equipment_type":
        if not isinstance(value,str) or norm(value) not in EQUIPMENT_TYPES: raise ValueError("Unknown equipment type")
    try: validated=ExtractedFields.model_validate({field:value})
    except ValidationError as exc: raise ValueError("Invalid corrected value") from exc
    normalized=getattr(validated,field)
    if normalized is None or isinstance(normalized,str) and not normalized.strip(): raise ValueError("Corrected value cannot be empty")
    return str(normalized) if field=="broker_contact_email" else normalized
def now(): return datetime.now(timezone.utc).isoformat()
def norm(v): return re.sub(r"\s+"," ",str(v or "").strip()).casefold()
def numeq(a,b,tolerance=.01):
    try: return abs(float(a)-float(b))<=tolerance
    except (TypeError,ValueError): return False
def _disc(kind,field,document_value,load_value):
    return {"id":f"dsc_{uuid.uuid5(uuid.NAMESPACE_URL,kind+'|'+field).hex[:16]}","type":kind,"field":field,"severity":"blocking" if kind in BLOCKING else "warning","document_value":document_value,"load_value":load_value,"resolution_status":"unresolved"}
def compare_rate_confirmation(fields,load,compared_at=None):
    discrepancies=[]; matches=[]; missing_doc=[]; missing_load=[]; compared=[]
    rules=[("total_rate","rate","total_rate_mismatch","numeric"),("linehaul_rate","rate","linehaul_rate_mismatch","numeric"),("loaded_miles","miles","mileage_mismatch","numeric"),("broker_name","broker","broker_name_mismatch","text"),("commodity","commodity","commodity_mismatch","text"),("weight","weight","weight_mismatch","numeric"),("equipment_type","equipment_type","equipment_type_mismatch","text"),("customer_reference","customer","customer_reference_mismatch","text"),("rate_confirmation_number","rate_con_number","duplicate_or_changed_rate_confirmation","text")]
    for ef,lf,kind,mode in rules:
        ev,lv=fields.get(ef),load.get(lf)
        if ev is None or ev=="": continue
        compared.append(ef)
        if lv is None or lv=="": missing_load.append(lf)
        elif (numeq(ev,lv) if mode=="numeric" else norm(ev)==norm(lv)): matches.append(ef)
        else: discrepancies.append(_disc(kind,ef,ev,lv))
    for prefix,missing_kind in (("pickup","missing_pickup"),("delivery","missing_delivery")):
        docloc=" ".join(str(fields.get(f"{prefix}_{x}") or "") for x in ("address","city","state","postal_code")).strip(); loadloc=" ".join(str(load.get(f"{prefix}_{x if x!='postal_code' else 'zip'}") or "") for x in ("address","city","state","postal_code")).strip()
        if not docloc: missing_doc.append(prefix); discrepancies.append(_disc(missing_kind,prefix,None,loadloc))
        elif norm(docloc)!=norm(loadloc): discrepancies.append(_disc(f"{prefix}_location_mismatch",f"{prefix}_location",docloc,loadloc))
        else: matches.append(f"{prefix}_location")
        appt=str(load.get(f"{prefix}_appt") or ""); d=fields.get(f"{prefix}_date"); t=fields.get(f"{prefix}_time_start")
        if d and appt and d!=appt[:10]: discrepancies.append(_disc(f"{prefix}_date_mismatch",f"{prefix}_date",d,appt[:10]))
        if t and len(appt)>=16 and t[:5]!=appt[11:16]: discrepancies.append(_disc(f"{prefix}_time_mismatch",f"{prefix}_time_start",t,appt[11:16]))
    if fields.get("total_rate") is None: missing_doc.append("total_rate"); discrepancies.append(_disc("missing_rate","total_rate",None,load.get("rate")))
    if not fields.get("broker_name") and not fields.get("broker_mc"): missing_doc.append("broker"); discrepancies.append(_disc("missing_broker","broker",None,load.get("broker")))
    blocking=sorted({d["type"] for d in discrepancies if d["severity"]=="blocking"}); material=sorted({d["type"] for d in discrepancies if d["type"] in MATERIAL})
    return {"comparison_status":"discrepancies_found" if discrepancies else "match","compared_at":compared_at or now(),"compared_fields":sorted(compared),"matches":sorted(matches),"discrepancies":discrepancies,"informational_differences":[],"missing_document_fields":sorted(set(missing_doc)),"missing_load_fields":sorted(set(missing_load)),"material_discrepancy_types":material,"blocking_discrepancy_types":blocking,"comparison_summary":{"match_count":len(matches),"discrepancy_count":len(discrepancies),"blocking_count":len(blocking)}}
