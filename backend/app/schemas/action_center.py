from typing import Literal
from pydantic import Field
from .common import StrictMutationModel

class AcknowledgeAction(StrictMutationModel):
    version:int=Field(ge=1)

ActionStatus=Literal["open","acknowledged","resolved"]
ActionCategory=Literal["execution","safety","fraud_risk","documents","finance","reconciliation","platform_integrity"]
ActionSeverity=Literal["critical","high","medium","low"]
OwnerRole=Literal["operations","safety","finance","admin"]
