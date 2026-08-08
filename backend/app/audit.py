"""Audit-first operation envelope. Audit events are insert-only by design."""
import logging
from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import HTTPException

from app.domain.audit_events import build_event, new_operation_id
from app.schemas.audit import AuditEntityType, AuditPhase, AuditSource

AUDIT_START_UNAVAILABLE = "Operation unavailable because audit evidence could not be recorded"
AUDIT_TERMINAL_WARNING = "Audit terminal event could not be recorded after primary operation"


@dataclass
class AuditOperation:
    collection: Any
    user: Mapping[str, Any]
    action: str
    entity_type: AuditEntityType
    entity_id: str
    changed_fields: list[str]
    previous: Mapping[str, Any] | None
    source: AuditSource
    operation_id: str

    async def _append(self, phase: AuditPhase, *, new=None, reason_code="", message="") -> None:
        event = build_event(user=self.user, operation_id=self.operation_id, phase=phase,
                            action=self.action, entity_type=self.entity_type, entity_id=self.entity_id,
                            source=self.source, changed_fields=self.changed_fields,
                            previous=self.previous, new=new, reason_code=reason_code, message=message)
        await self.collection.insert_one(event)

    async def succeeded(self, new=None) -> None:
        try:
            await self._append(AuditPhase.SUCCEEDED, new=new)
        except Exception:
            logging.warning(AUDIT_TERMINAL_WARNING)

    async def rejected(self, reason_code: str) -> None:
        try:
            await self._append(AuditPhase.REJECTED, reason_code=reason_code)
        except Exception:
            logging.warning(AUDIT_TERMINAL_WARNING)

    async def failed(self, reason_code: str = "internal_failure") -> None:
        try:
            await self._append(AuditPhase.FAILED, reason_code=reason_code)
        except Exception:
            logging.warning(AUDIT_TERMINAL_WARNING)


async def begin_audit(collection: Any, user: Mapping[str, Any], action: str,
                      entity_type: AuditEntityType, entity_id: str, *, changed_fields=None,
                      previous=None, source: AuditSource = AuditSource.API,
                      operation_id: str | None = None) -> AuditOperation:
    operation = AuditOperation(collection, user, action, entity_type, entity_id,
                               list(changed_fields or []), previous, source, operation_id or new_operation_id())
    try:
        await operation._append(AuditPhase.STARTED)
    except Exception:
        logging.error("Audit start event could not be recorded")
        raise HTTPException(status_code=503, detail=AUDIT_START_UNAVAILABLE)
    return operation
