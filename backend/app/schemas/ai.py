from pydantic import Field

from .common import StrictMutationModel


class AiChatRequest(StrictMutationModel):
    session_id: str = Field(default="default", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    message: str = Field(min_length=1, max_length=10000)
