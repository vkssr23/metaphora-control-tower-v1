import asyncio
import pytest

from app.domain.invoice_authority import InvoiceAuthority,classify_invoice_authority,legacy_write_allowed
from app.infrastructure.impact_executor import execute_impact_plan
from app.domain.mutation_impact import (
    ImpactAction,MutationType,POLICY_VERSION,SourceEntityType,TargetDomain,
    derive_changed_fields,has_impact,impact_for,plan_mutation,
)


def domains(plan):return [item.target_domain for item in plan.impacts]


@pytest.mark.parametrize("field,execution_type",[("driver_id","driver_assignment"),("truck_id","truck_assignment"),("equipment_type","equipment"),("pickup_address","appointment"),("miles","mileage")])
def test_load_material_change_parity(field,execution_type):
    plan=plan_mutation("load","L1","load.updated",old_state={field:"old"},proposed_state={field:"new"},relevant_fields=[field])
    assert domains(plan)[:2]==[TargetDomain.PICKUP_RELEASE,TargetDomain.LOAD_PASSPORT]
    assert execution_type in impact_for(plan,TargetDomain.EXECUTION_ELIGIBILITY).change_types
    assert plan.policy_version==POLICY_VERSION and len(plan.plan_id)==68


def test_commercial_and_party_changes_are_centralized():
    plan=plan_mutation("load","L1","load.updated",old_state={"broker":"A","rate":10},proposed_state={"broker":"B","rate":11},relevant_fields=["broker","rate"])
    assert has_impact(plan,TargetDomain.PARTY_VERIFICATION)
    assert has_impact(plan,TargetDomain.INVOICE_READINESS)
    assert [x.order for x in plan.impacts]==sorted(x.order for x in plan.impacts)


def test_known_nonmaterial_and_same_value_are_no_impact():
    assert not plan_mutation("load","L1","load.updated",old_state={"notes":"a"},proposed_state={"notes":"b"},relevant_fields=["notes"]).impacts
    assert derive_changed_fields({"driver_id":"D1"},{"driver_id":"D1"},["driver_id"])==()


def test_unknown_field_fails_closed():
    plan=plan_mutation("load","L1","load.updated",old_state={"unknown_basis":"a"},proposed_state={"unknown_basis":"b"},relevant_fields=["unknown_basis"])
    assert plan.unknown_fields==("unknown_basis",)
    assert plan.impacts and has_impact(plan,TargetDomain.INVOICE_READINESS)


@pytest.mark.parametrize("doc_type,expected",[("rate_con",{TargetDomain.LOAD_PASSPORT,TargetDomain.PARTY_VERIFICATION,TargetDomain.EXECUTION_ELIGIBILITY,TargetDomain.PICKUP_RELEASE,TargetDomain.INVOICE_READINESS}),("pod",{TargetDomain.INVOICE_READINESS}),("insurance",{TargetDomain.LOAD_PASSPORT,TargetDomain.PARTY_VERIFICATION,TargetDomain.EXECUTION_ELIGIBILITY,TargetDomain.PICKUP_RELEASE}),("scale",set())])
def test_document_policy(doc_type,expected):
    plan=plan_mutation("document","D1","document.added",context={"document_type":doc_type})
    assert set(domains(plan))==expected
    assert all(item.action not in {"APPROVE","AUTHORIZE"} for item in plan.impacts)


@pytest.mark.parametrize("mutation",[MutationType.RATE_CONFIRMATION_ACCEPTED,MutationType.RATE_CONFIRMATION_SUPERSEDED])
def test_rate_identity_change_impacts_even_without_dollar_change(mutation):
    plan=plan_mutation(SourceEntityType.RATE_CONFIRMATION,"RC2",mutation)
    assert set(domains(plan))=={TargetDomain.PICKUP_RELEASE,TargetDomain.LOAD_PASSPORT,TargetDomain.PARTY_VERIFICATION,TargetDomain.EXECUTION_ELIGIBILITY,TargetDomain.INVOICE_READINESS}


def test_execution_and_finance_policy():
    amended=plan_mutation("execution_session","E1","execution.plan_amended")
    finance=plan_mutation("invoice_readiness","I1","invoice_readiness.financial_basis_changed")
    assert amended.impacts[0].action==ImpactAction.REOPEN
    assert finance.impacts[0].action==ImpactAction.RECALCULATE


def test_plan_is_deterministic_and_contains_no_raw_state():
    args=dict(old_state={"driver_id":"D1","secret":"old"},proposed_state={"driver_id":"D2","secret":"new"},relevant_fields=["driver_id"])
    one=plan_mutation("load","L1","load.updated",**args);two=plan_mutation("load","L1","load.updated",**args)
    assert one==two and "secret" not in str(one.as_dict())


def test_invoice_authority_classification():
    legacy={"id":"old","load_id":"L1"};modern={"id":"new","load_id":"L1","readiness_case_id":"R1","package_id":"P1"}
    assert classify_invoice_authority([legacy],[])==InvoiceAuthority.LEGACY
    assert classify_invoice_authority([], [{"id":"R1","status":"draft"}])==InvoiceAuthority.MODERN
    assert classify_invoice_authority([legacy,modern],[])==InvoiceAuthority.AMBIGUOUS
    assert legacy_write_allowed(InvoiceAuthority.LEGACY)
    assert not legacy_write_allowed(InvoiceAuthority.MODERN)


@pytest.mark.parametrize("lifecycle",[
    {"domain":"load_passports","id":"P1"},
    {"domain":"execution_eligibility_cases","id":"E1"},
    {"domain":"pickup_release_cases","id":"PR1"},
    {"domain":"execution_sessions","id":"S1"},
])
def test_modern_lifecycle_evidence_closes_legacy_boundary(lifecycle):
    assert classify_invoice_authority([],[],[lifecycle])==InvoiceAuthority.MODERN


def test_absence_is_unverifiable_and_malformed_modern_is_not_legacy():
    assert classify_invoice_authority()==InvoiceAuthority.UNVERIFIABLE
    assert classify_invoice_authority([{"id":"I1","readiness_case_id":"R1"}])==InvoiceAuthority.MODERN_INCOMPLETE
    assert classify_invoice_authority([{"id":"I2","package_id":"P1"}])==InvoiceAuthority.MODERN_INCOMPLETE
    assert not legacy_write_allowed(InvoiceAuthority.UNVERIFIABLE)
    assert not legacy_write_allowed(InvoiceAuthority.MODERN_INCOMPLETE)


def test_executor_rejects_not_applicable_for_required_current_record():
    plan=plan_mutation("load","L1","load.updated",old_state={"rate":1},proposed_state={"rate":2},relevant_fields=["rate"])
    async def absent(_tenant,_impact,_correlation):return "not_applicable"
    handlers={impact.target_domain:absent for impact in plan.impacts}
    with pytest.raises(RuntimeError,match="required current impact record missing"):
        asyncio.run(execute_impact_plan(plan,"T1",handlers))
