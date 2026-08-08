"""Bounded executor contract for pure impact plans.

Handlers remain domain-specific and must tenant-scope their own guarded writes.
"""
from enum import StrEnum

from app.domain.mutation_impact import MAX_IMPACTS


class ImpactResultStatus(StrEnum):
    APPLIED = "applied"
    NOT_APPLICABLE = "not_applicable"
    ALREADY_CONSERVATIVE = "already_conservative"
    CONFLICT = "conflict"
    FAILED = "failed"


async def execute_impact_plan(plan, tenant_id, handlers, *, correlation_id=None):
    if not tenant_id:
        raise ValueError("tenant_id is required")
    if len(plan.impacts) > MAX_IMPACTS:
        raise ValueError("impact plan is not bounded")
    results = []
    for impact in plan.impacts:
        handler = handlers.get(impact.target_domain)
        if handler is None:
            if impact.requires_current_record:
                raise RuntimeError(f"required impact handler missing: {impact.target_domain}")
            status = ImpactResultStatus.NOT_APPLICABLE
        else:
            status = ImpactResultStatus(await handler(tenant_id, impact, correlation_id))
            if status == ImpactResultStatus.NOT_APPLICABLE and impact.requires_current_record:
                raise RuntimeError(f"required current impact record missing: {impact.target_domain}")
        results.append({"target_domain": impact.target_domain.value, "action": impact.action.value, "reason_code": impact.reason_code, "status": status.value})
        if status in {ImpactResultStatus.CONFLICT, ImpactResultStatus.FAILED}:
            raise RuntimeError(f"required impact did not complete: {impact.target_domain}:{status}")
    return {"plan_id": plan.plan_id, "policy_version": plan.policy_version, "correlation_id": correlation_id, "results": results}
