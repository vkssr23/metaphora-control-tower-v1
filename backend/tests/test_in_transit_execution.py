import pytest
from app.domain.in_transit_execution import *

def test_lifecycle_is_fail_closed():
 assert TRANSITIONS["pending_start"]=={"active"}
 assert "completed" not in TRANSITIONS["active"]
def test_eta_thresholds_and_unknown():
 p="2026-01-01T10:00:00Z"
 assert eta_evaluation(p,"",p)["status"]=="unknown"
 assert eta_evaluation(p,"2026-01-01T10:15:00Z",p)["status"]=="on_time"
 assert eta_evaluation(p,"2026-01-01T10:16:00Z",p)["status"]=="at_risk"
 assert eta_evaluation(p,"2026-01-01T10:31:00Z",p)["status"]=="late"
def test_eta_is_deterministic():
 args=("2026-01-01T10:00:00Z","2026-01-01T10:16:00Z","2026-01-01T09:00:00Z")
 assert eta_evaluation(*args)==eta_evaluation(*args)
def test_delay_does_not_invent_cause():
 assert delay_evaluation(None,None)["reason_code"] is None
 assert delay_evaluation(None,None,20)["reason_code"]=="driver_reported_delay"
def test_sla_states():
 assert sla_state("2026-01-01T12:00:00Z","2026-01-01T10:00:00Z")=="within_sla"
 assert sla_state("2026-01-01T10:20:00Z","2026-01-01T10:00:00Z")=="due_soon"
 assert sla_state("2026-01-01T09:00:00Z","2026-01-01T10:00:00Z")=="overdue"
def test_health():
 assert execution_health([],"2026-01-01T10:00:00Z")=="healthy"
 assert execution_health([{"status":"open","severity":"warning"}],"2026-01-01T10:00:00Z")=="watch"
 assert execution_health([{"status":"open","severity":"high"}],"2026-01-01T10:00:00Z")=="at_risk"
 assert execution_health([{"status":"open","severity":"critical"}],"2026-01-01T10:00:00Z")=="critical"
def test_detention_duration_server_calculated():
 assert detention_minutes("2026-01-01T10:00:00Z","2026-01-01T11:01:00Z")==61
 with pytest.raises(ValueError):detention_minutes("2026-01-01T11:00:00Z","2026-01-01T10:00:00Z")
def test_manual_route_cannot_confirm():
 with pytest.raises(ValueError):route_status("confirmed_deviation","manual")
 assert route_status("possible_deviation","manual")=="possible_deviation"
def test_material_change_detection():
 assert material_changes({"driver_id":"a","truck_id":"t"},{"driver_id":"b","truck_id":"t"})==["driver_id_changed"]
def test_completion_requires_delivery_pod_custody_and_no_blocker():
 s={"status":"delivery_confirmed","custody_state":"delivery_confirmed"}
 assert completion_readiness(s,[],True)["ready"]
 assert "pod_required" in completion_readiness(s,[],False)["reasons"]
 assert "blocking_exception" in completion_readiness(s,[{"status":"open","blocking":True}],True)["reasons"]
def test_future_sources_are_restricted():
 assert "future_telematics" in FUTURE_SOURCES and "system" in FUTURE_SOURCES
def test_material_detector_domains_and_history_policy():
 s={"status":"active"};old={"driver_id":"D1","delivery_appt":"a","miles":100}
 result=detect_material_load_change(old,{"driver_id":"D2","delivery_appt":"b","miles":120},s,{"immutable":True})
 assert result["is_material"] and result["exception_required"] and result["plan_amendment_required"]
 assert result["changed_field_names"]==["delivery_appt","driver_id","miles"]
 assert result["affected_execution_domains"]==["assignment","delivery","mileage"] and result["preserve_planned_snapshot"]
def test_material_detector_nonmaterial_and_equal_values():
 old={"notes":"a","driver_id":"D1"};s={"status":"active"}
 assert not detect_material_load_change(old,{"notes":"b"},s,{})["is_material"]
 assert not detect_material_load_change(old,{"driver_id":"D1"},s,{})["is_material"]
def test_terminal_sessions_do_not_open_material_control():
 for status in TERMINAL:
  assert not detect_material_load_change({"driver_id":"D1"},{"driver_id":"D2"},{"status":status},{})["is_material"]
 assert MATERIAL_CONTROL_ACTIVE=={"active","paused","exception","delivery_arrived"}
def test_current_release_selection_is_deterministic_and_fail_closed():
 confirmed={"id":"old","status":"pickup_confirmed","updated_at":"2026-01-01","version":1}
 assert select_current_pickup_release([confirmed])==(confirmed,None)
 review={"id":"new","status":"review_pending","updated_at":"2026-01-02","version":2}
 assert select_current_pickup_release([confirmed,review])==(None,"pickup_release_not_current")
 twin={**review,"id":"newer"}
 assert select_current_pickup_release([confirmed,review,twin])==(None,"pickup_release_ambiguous")
 assert select_current_pickup_release([])==(None,"pickup_confirmation_required")
def test_delay_requires_explicit_clock_and_is_deterministic():
 args=("2026-01-01T10:00:00Z","2026-01-01T10:31:00Z",0,False,False,"2026-01-01T09:00:00Z")
 assert delay_evaluation(*args)==delay_evaluation(*args)
 assert delay_evaluation("2026-01-01T10:00:00Z","2026-01-01T10:31:00Z",as_of=None)["reason_code"] is None
def test_owner_category_policy():
 assert owner_role_allowed("timing","operations") and owner_role_allowed("driver","safety")
 assert not owner_role_allowed("driver","operations") and owner_role_allowed("driver","owner")
