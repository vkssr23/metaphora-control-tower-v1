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

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            jwt_secret=validate_jwt_secret(os.environ.get("JWT_SECRET")),
            cors_origins=parse_cors_origins(os.environ.get("CORS_ORIGINS")),
            app_env=os.environ.get("APP_ENV", "production").strip().lower(),
            allow_seed_endpoint=env_flag("ALLOW_SEED_ENDPOINT"),
        )
