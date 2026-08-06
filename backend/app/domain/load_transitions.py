from app.schemas.loads import LoadStage

ORDERED_STAGES = (
    LoadStage.BOOKED, LoadStage.ASSIGNED, LoadStage.DISPATCHED, LoadStage.PICKUP_STARTED,
    LoadStage.ARRIVED_PICKUP, LoadStage.LOADED, LoadStage.IN_TRANSIT,
    LoadStage.ARRIVED_DELIVERY, LoadStage.DELIVERED, LoadStage.DOCS_PENDING,
    LoadStage.INVOICE_PENDING, LoadStage.PAYMENT_PENDING, LoadStage.CLOSED,
)
LOAD_TRANSITIONS = {stage: {ORDERED_STAGES[index + 1], LoadStage.EXCEPTION} for index, stage in enumerate(ORDERED_STAGES[:-1])}
LOAD_TRANSITIONS[LoadStage.CLOSED] = set()
LOAD_TRANSITIONS[LoadStage.EXCEPTION] = set()

def transition_allowed(current: LoadStage, requested: LoadStage, exception_origin: LoadStage | None = None) -> bool:
    if current == requested:
        return True
    if current == LoadStage.EXCEPTION:
        return exception_origin is not None and requested == exception_origin
    return requested in LOAD_TRANSITIONS[current]
