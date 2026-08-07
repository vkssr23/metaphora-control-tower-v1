from app.domain.pickup_release import bounded_snapshot,evaluate,material_changes,authorization,authorization_binding,revoke_authorization,norm,phone,TRANSITIONS

def records():
    load={"id":"L1","customer":"Plant","pickup_address":"1 Main St","pickup_appt":"2026-09-01T10:00:00","rate_con_number":"PU1","equipment_type":"Power Only","commodity":"General","weight":1000,"driver_id":"D1","truck_id":"T1"}
    passport={"id":"P1","tenant_id":"TEN","load_id":"L1","version":4,"status":"approved","rate_confirmation":{"extraction_id":"R1"}}
    rate={"id":"R1","load_id":"L1","version":2,"revision":1,"status":"accepted","document_id":"DOC1","accepted_snapshot":{"extracted_fields":{"pickup_name":"Plant","pickup_address":"1 main st","pickup_date":"2026-09-01","pickup_time_start":"10:00","pickup_number":"PU1","equipment_type":"power only","commodity":"general"}}}
    party={"id":"V1","load_id":"L1","passport_id":"P1","version":2,"status":"cleared","broker_snapshot":{"contact_name":"Jane"},"contact_validation_snapshot":{"normalized_email":"jane@example.test"}}
    execution={"id":"E1","load_id":"L1","passport_id":"P1","passport_version":4,"version":3,"status":"eligible","driver_snapshot":{"id":"D1"},"truck_snapshot":{"id":"T1"},"trailer_snapshot":{"identifier":"TRL1"}}
    snap=bounded_snapshot(load,passport,rate,party,execution)
    case={"id":"C1","tenant_id":"TEN","load_id":"L1","passport_id":"P1","version":2,"release_snapshot":snap,"contact_snapshot":{"name":"","email":"jane@example.test","phone":"","source":"internal_records"},"prerequisite_snapshot":{"passport_id":"P1","passport_version":4,"rate_confirmation_id":"R1","rate_confirmation_version":2,"rate_confirmation_revision":1,"rate_confirmation_document_id":"DOC1","party_verification_id":"V1","party_verification_version":2,"execution_eligibility_id":"E1","execution_eligibility_version":3},"findings":[],"execution_eligibility_case_id":"E1","party_verification_case_id":"V1","rate_confirmation_extraction_id":"R1"}
    return load,passport,rate,party,execution,case

def test_valid_records_are_deterministically_release_ready():
    values=records(); context={"as_of":"2026-08-07T12:00:00+00:00"}; a=evaluate(*values,context); b=evaluate(*values,context)
    assert a["verdict"]=="release_ready" and a["blocking_reasons"]==[]
    for key in ("verdict","blocking_reasons","warning_reasons","unresolved_finding_ids","satisfied_checklist_items","unsatisfied_checklist_items"): assert a[key]==b[key]
def test_mandatory_prerequisites_fail_closed():
    l,p,r,v,e,c=records()
    for index,kind in ((1,"load_passport_not_current"),(2,"rate_confirmation_not_current"),(3,"party_verification_not_current"),(4,"execution_eligibility_not_current")):
        args=[l,p,r,v,e,c]; args[index]=None; out=evaluate(*args,{"as_of":"now"})
        assert out["verdict"]=="blocked" and kind in out["blocking_reasons"]
def test_assignment_mismatches_block():
    l,p,r,v,e,c=records()
    for field,kind in (("driver_id","driver_assignment_changed"),("truck_id","truck_assignment_changed")):
        changed=dict(l); changed[field]="OTHER"; out=evaluate(changed,p,r,v,e,c,{"as_of":"now"}); assert kind in out["blocking_reasons"]
    e={**e,"trailer_snapshot":{"identifier":"OTHER"}}; assert "trailer_identifier_changed" in evaluate(l,p,r,v,e,c,{"as_of":"now"})["blocking_reasons"]
def test_pickup_mismatches_generate_controlled_findings():
    l,p,r,v,e,c=records(); fields={"pickup_address":"pickup_address_mismatch","pickup_appt":"pickup_date_mismatch","rate_con_number":"pickup_reference_mismatch","equipment_type":"equipment_mismatch","commodity":"commodity_mismatch"}
    for field,kind in fields.items():
        changed={**l,field:"different"}; assert kind in evaluate(changed,p,r,v,e,c,{"as_of":"now"})["blocking_reasons"]
def test_contact_normalization_and_warning_policy():
    assert norm(" A  B ")=="a b" and phone("+1 (212) 555-0123")=="2125550123"
    l,p,r,v,e,c=records(); c={**c,"contact_snapshot":{"email":"other@example.test"}}; out=evaluate(l,p,r,v,e,c,{"as_of":"now"}); assert out["verdict"]=="review_required" and "pickup_contact_mismatch" in out["warning_reasons"]
def test_duplicate_authorization_blocks():
    l,p,r,v,e,c=records(); p={**p,"pickup_authorization":{"status":"active"}}; c={**c,"release_snapshot":bounded_snapshot(l,p,r,v,e)}
    assert "duplicate_active_authorization" in evaluate(l,p,r,v,e,c,{"as_of":"now"})["blocking_reasons"]
def test_material_change_detector():
    l,p,r,v,e,c=records(); out=material_changes(c["release_snapshot"],{**c["release_snapshot"]["load"],"pickup_address":"2 Main"}); assert out["blocking"] and out["authorization_revocation_required"] and "pickup_address" in out["changed_fields"]
def test_lifecycle_released_immutability_policy():
    assert "released" in TRANSITIONS["release_ready"] and "released" not in TRANSITIONS["draft"] and TRANSITIONS["released"]=={"pickup_confirmed","exception","revoked"}
def test_authorization_hash_and_revocation_preserve_evidence():
    l,p,r,v,e,c=records(); user={"id":"U1","tenant_id":"TEN"}; a=authorization(c,p,user,"2026-01-01T00:00:00+00:00"); b=authorization(c,p,user,"2026-01-01T00:00:00+00:00")
    assert a==b and len(a["evidence_hash"])==64 and a["state"]=="active"
    revoked=revoke_authorization(a,user,"material change","2026-01-02T00:00:00+00:00")
    for key in ("authorization_id","issued_at","issued_by","evidence_hash"): assert revoked[key]==a[key]
    assert revoked["state"]=="revoked" and revoked["revoked_by"]=="U1"
def test_each_prerequisite_version_drift_blocks():
    l,p,r,v,e,c=records()
    for record,field in ((r,"version"),(v,"version"),(e,"version"),(p,"version")):
        changed=dict(record); changed[field]+=1; args=[l,p,r,v,e,c]; args[[p,r,v,e].index(record)+1]=changed
        out=evaluate(*args,{"as_of":"fixed"}); assert out["verdict"]=="blocked" and "prerequisite_version_changed" in out["blocking_reasons"]
def test_authorization_binding_requires_full_relationship_and_no_reuse():
    l,p,r,v,e,c=records(); c={**c,"version":3,"pickup_authorization_id":"A1","assignment_snapshot":c["release_snapshot"]["load"]}; p={**p,"tenant_id":"TEN","pickup_authorization":{"authorization_id":"A1","tenant_id":"TEN","load_id":"L1","passport_id":"P1","release_case_id":"C1","release_case_version":3,"driver_id":"D1","truck_id":"T1","trailer_identifier":"TRL1","state":"active","status":"active"}}
    assert authorization_binding(c,p,l,"TEN")["valid"]
    for field in ("load_id","passport_id","release_case_id"):
        bad={**p,"pickup_authorization":{**p["pickup_authorization"],field:"OTHER"}}; assert authorization_binding(c,bad,l,"TEN")["reason"]=="pickup_authorization_binding_mismatch"
    consumed={**p,"pickup_authorization":{**p["pickup_authorization"],"state":"consumed","status":"consumed","consumed_at":"now"}}; assert not authorization_binding(c,consumed,l,"TEN")["valid"]
