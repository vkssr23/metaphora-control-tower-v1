"""Controlled Phase 2B operation and step lifecycle vocabulary."""
from enum import Enum


class ExecutionMode(str, Enum):
    TRANSACTIONAL = "transactional"
    DURABLE_SAGA = "durable_saga"


class OperationStatus(str, Enum):
    PLANNED = "planned"
    STARTED = "started"
    COMMITTING = "committing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    RECONCILIATION_REQUIRED = "reconciliation_required"


class StepStatus(str, Enum):
    PENDING = "pending"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


ACTIVE_OPERATION_STATUSES = frozenset({"planned", "started", "committing"})
TERMINAL_OPERATION_STATUSES = frozenset({"succeeded", "failed", "partial", "reconciliation_required"})
ALLOWED_OPERATION_TRANSITIONS = {
    "planned": frozenset({"planned", "started", "failed", "partial", "reconciliation_required"}),
    "started": frozenset({"started", "committing", "failed", "partial", "reconciliation_required"}),
    "committing": frozenset({"committing", "succeeded", "failed", "partial", "reconciliation_required"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "partial": frozenset(),
    "reconciliation_required": frozenset(),
}
ALLOWED_STEP_TRANSITIONS = {
    "pending": frozenset({"pending", "started", "completed", "failed", "skipped"}),
    "started": frozenset({"started", "completed", "failed", "skipped"}),
    "completed": frozenset({"completed"}),
    "failed": frozenset({"failed"}),
    "skipped": frozenset({"skipped"}),
}
INVOICE_CREATE_STEPS = (
    "operation_started", "readiness_claimed", "package_created", "invoice_created",
    "readiness_finalized", "outbox_recorded",
)


def validate_steps(operation_type: str, steps: list[dict]) -> None:
    allowed = {"invoice.create": frozenset(INVOICE_CREATE_STEPS)}.get(operation_type, frozenset())
    names = [step.get("name") for step in steps]
    if not allowed or any(name not in allowed for name in names) or len(names) != len(set(names)):
        raise ValueError("Unsupported operation steps")


def validate_transition(current: str, requested: str) -> None:
    if requested not in ALLOWED_OPERATION_TRANSITIONS.get(current, frozenset()):
        raise ValueError(f"Illegal operation transition: {current} -> {requested}")


def validate_step_transition(steps: list[dict], step_name: str, requested: str) -> None:
    index = next((i for i, step in enumerate(steps) if step.get("name") == step_name), None)
    if index is None: raise ValueError("Unsupported operation step")
    current = steps[index].get("status")
    if requested not in ALLOWED_STEP_TRANSITIONS.get(current, frozenset()):
        raise ValueError(f"Illegal operation step transition: {current} -> {requested}")
    if requested in {"started", "completed"} and any(
        prior.get("status") not in {"completed", "skipped"} for prior in steps[:index]
    ):
        raise ValueError("Operation steps must advance in server-defined order")
