import re
from urllib.parse import unquote, urlparse, urlunparse

from pydantic import Field, field_validator, model_validator

from .common import StrictMutationModel, StringEnum

class DocumentType(StringEnum):
    RATE_CON="rate_con"; BOL="bol"; POD="pod"; LUMPER="lumper"; SCALE="scale"; INVOICE="invoice"; OTHER="other"

class DocumentCreate(StrictMutationModel):
    load_id: str = Field(min_length=1, max_length=100)
    doc_type: DocumentType
    filename: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2048)
    notes: str = Field(default="", max_length=5000)

    @field_validator("filename")
    @classmethod
    def clean_filename(cls, value):
        value = value.strip()
        if not value or any(c in value for c in "\r\n\0"):
            raise ValueError("Invalid filename")
        return value

    @field_validator("url")
    @classmethod
    def safe_url(cls, value):
        if value != value.strip() or any(ord(char) < 32 or char.isspace() for char in value) or "\\" in value:
            raise ValueError("URL contains whitespace, controls, or backslashes")
        decoded = unquote(value)
        if any(ord(char) < 32 for char in decoded) or ".." in decoded:
            raise ValueError("URL contains encoded controls or traversal")
        parsed = urlparse(value)
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise ValueError("URL credentials, query strings, and fragments are not supported")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("URL port is invalid") from exc
        if parsed.scheme == "https":
            if not parsed.hostname or parsed.netloc.startswith(":") or value.startswith("https:////"):
                raise ValueError("HTTPS URL requires an unambiguous hostname")
            if urlunparse(parsed) != value:
                raise ValueError("URL is not canonical")
            return value
        if parsed.scheme == "mock":
            if parsed.path or not parsed.hostname or parsed.port is not None:
                raise ValueError("Mock URL must contain exactly one filename authority")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", parsed.netloc):
                raise ValueError("Mock filename authority is invalid")
            return value
        raise ValueError("Only HTTPS and the local mock preview URL are supported")

    @model_validator(mode="after")
    def mock_url_must_match_filename(self):
        parsed = urlparse(self.url)
        if parsed.scheme == "mock" and parsed.netloc != self.filename:
            raise ValueError("Mock URL authority must exactly match filename")
        return self
