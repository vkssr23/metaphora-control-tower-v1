"""Fail-closed backend security configuration."""
from dataclasses import dataclass
import ipaddress
import os
import re
from urllib.parse import urlsplit

_KNOWN_BAD_SECRETS = {"dev_secret", "secret", "changeme", "change-me", "default", "jwt_secret"}


def validate_jwt_secret(value: str | None) -> str:
    secret = (value or "").strip()
    if len(secret) < 32 or secret.lower() in _KNOWN_BAD_SECRETS:
        raise RuntimeError("JWT_SECRET must be a non-default secret of at least 32 characters")
    return secret


def parse_cors_origins(value: str | None) -> list[str]:
    normalized = []
    for raw_origin in (value or "").split(","):
        origin = raw_origin.strip()
        if not origin:
            continue
        if "*" in origin or any(char.isspace() for char in origin):
            raise RuntimeError("CORS_ORIGINS entries cannot contain wildcards or whitespace")
        try:
            parsed = urlsplit(origin)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise RuntimeError("CORS_ORIGINS contains a malformed origin") from exc
        if parsed.scheme.lower() not in {"http", "https"} or not hostname:
            raise RuntimeError("CORS_ORIGINS entries must be explicit HTTP(S) origins")
        if parsed.username is not None or parsed.password is not None:
            raise RuntimeError("CORS_ORIGINS entries cannot contain credentials")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise RuntimeError("CORS_ORIGINS entries cannot contain paths, queries, or fragments")
        if parsed.netloc.endswith(":") or port is not None and not 1 <= port <= 65535:
            raise RuntimeError("CORS_ORIGINS contains an invalid port")
        host = hostname.lower()
        try:
            ipaddress.ip_address(host)
            rendered_host = f"[{host}]" if ":" in host else host
        except ValueError:
            labels = host.split(".")
            if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                   for label in labels):
                raise RuntimeError("CORS_ORIGINS contains an invalid hostname")
            rendered_host = host
        rendered = f"{parsed.scheme.lower()}://{rendered_host}"
        if port is not None:
            rendered += f":{port}"
        if rendered not in normalized:
            normalized.append(rendered)
    return normalized


SAFE_FORCE_SEED_ENVIRONMENTS = frozenset({"local", "development", "dev", "test"})


def force_seed_allowed(app_env: str | None) -> bool:
    return (app_env or "").strip().lower() in SAFE_FORCE_SEED_ENVIRONMENTS


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    jwt_secret: str
    cors_origins: list[str]
    app_env: str
    allow_seed_endpoint: bool
    # Dispatch-authorization shadow evaluator gate. Defaults OFF: PR1 only
    # lays the evaluation foundation (pure evaluator + append-only shadow
    # records), it never blocks anything. A later change makes the
    # evaluator's decision load-bearing when this is on.
    dispatch_gate_enforced: bool = False
    document_storage_backend: str = "local"
    document_storage_root: str = "./data/documents"
    document_max_upload_bytes: int = 15 * 1024 * 1024
    # Metaphora Verify integration (Party Verification broker-authority
    # check) — deliberately OPTIONAL and unvalidated at startup, unlike
    # every field above. jwt_secret/cors_origins are security-critical: a
    # missing/weak value there must stop the whole app from starting,
    # because every route depends on them. This integration is an
    # enhancement to one already-functional internal check (Party
    # Verification degrades to its pre-integration, internal-only behavior
    # when unset — see party_verification_client.is_configured()); an
    # unrelated missing env var must never be able to take down every
    # other route in Control Tower. If this integration later becomes
    # load-bearing for a compliance requirement, revisit this decision.
    metaphora_verify_base_url: str | None = None
    metaphora_verify_service_key: str | None = None
    metaphora_verify_timeout_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> "Settings":
        maximum = int(os.environ.get("DOCUMENT_MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
        if maximum < 1024 or maximum > 100 * 1024 * 1024:
            raise RuntimeError("DOCUMENT_MAX_UPLOAD_BYTES must be between 1 KiB and 100 MiB")
        backend = os.environ.get("DOCUMENT_STORAGE_BACKEND", "local").strip().lower()
        if backend != "local":
            raise RuntimeError("Only the local document storage backend is implemented")
        return cls(
            jwt_secret=validate_jwt_secret(os.environ.get("JWT_SECRET")),
            cors_origins=parse_cors_origins(os.environ.get("CORS_ORIGINS")),
            app_env=os.environ.get("APP_ENV", "production").strip().lower(),
            allow_seed_endpoint=env_flag("ALLOW_SEED_ENDPOINT"),
            dispatch_gate_enforced=env_flag("DISPATCH_GATE_ENFORCED"),
            document_storage_backend=backend,
            document_storage_root=os.environ.get("DOCUMENT_STORAGE_ROOT", "./data/documents"),
            document_max_upload_bytes=maximum,
            metaphora_verify_base_url=(os.environ.get("METAPHORA_VERIFY_BASE_URL") or "").strip().rstrip("/") or None,
            # Stripped defensively, unlike a typical secret: this one gets
            # hand-copied into Railway's UI (unlike JWT_SECRET, which is
            # generated and never retyped), so accidental leading/trailing
            # whitespace from a copy-paste is a real, observed failure mode
            # (httpx raises LocalProtocolError on a header value with
            # leading whitespace) rather than a hypothetical one.
            metaphora_verify_service_key=(os.environ.get("METAPHORA_VERIFY_SERVICE_KEY") or "").strip() or None,
            metaphora_verify_timeout_seconds=float(os.environ.get("METAPHORA_VERIFY_TIMEOUT_SECONDS", "5.0")),
        )
