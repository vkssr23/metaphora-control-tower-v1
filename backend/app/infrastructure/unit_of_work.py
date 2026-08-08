"""Explicit execution strategies; saga mode intentionally makes no atomicity claim."""
from dataclasses import dataclass
from enum import Enum


class TransactionRequirement(str, Enum):
    DISABLED = "disabled"
    PREFERRED = "preferred"
    REQUIRED = "required"


@dataclass(frozen=True)
class UnitOfWorkCapability:
    mode: str
    transaction_capability: str
    atomic_multi_document_writes: bool
    warning: str | None = None


def select_unit_of_work(requirement=TransactionRequirement.DISABLED, *, verified_session=None):
    """Selection is configuration-driven; a Mongo URL is never evidence of capability."""
    if verified_session is not None:
        return TransactionalUnitOfWork(verified_session)
    if requirement == TransactionRequirement.REQUIRED:
        raise RuntimeError("transaction_required_but_unverified")
    warning = "transaction_unverified_saga_selected" if requirement == TransactionRequirement.PREFERRED else None
    return DurableSagaUnitOfWork(warning)


class DurableSagaUnitOfWork:
    def __init__(self, warning=None):
        self.capability = UnitOfWorkCapability("durable_saga", "unverified", False, warning)

    async def execute(self, command):
        return await command(None)


class TransactionalUnitOfWork:
    """Adapter for an explicitly supplied, already-verified session only."""
    def __init__(self, session):
        self.session = session
        self.capability = UnitOfWorkCapability("transactional", "verified", True)

    async def execute(self, command):
        async with self.session.start_transaction():
            return await command(self.session)

