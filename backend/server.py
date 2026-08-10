"""Metaphora Control Tower - Freight Operations Backend bootstrap."""
from fastapi import FastAPI, APIRouter, Depends, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import logging
import os
from pathlib import Path

from app.config import Settings, force_seed_allowed
from app.permissions import require_capability, require_owner, require_audit_reader
from app.security import authenticated_user_dependency
from app.observability import RequestContextMiddleware
from app.runtime import configure_runtime, db as runtime_db, now_iso, new_id, clean_doc, safe_db, audited_db
from app.passport_routes import register_passport_routes
from app.rate_confirmation_routes import register_rate_confirmation_routes
from app.party_verification_routes import register_party_verification_routes
from app.execution_eligibility_routes import register_execution_eligibility_routes
from app.pickup_release_routes import register_pickup_release_routes
from app.in_transit_execution_routes import register_in_transit_execution_routes
from app.invoice_readiness_routes import register_invoice_readiness_routes
from app.api.auth_routes import register_auth_routes
from app.api.fleet_routes import register_fleet_routes
from app.api.load_routes import register_load_routes
from app.api.activity_audit_routes import register_activity_audit_routes
from app.api.document_routes import register_document_routes
from app.api.legacy_invoice_routes import register_legacy_invoice_routes
from app.api.demo_routes import register_demo_routes
from app.api.query_routes import register_query_routes
from app.api.health_routes import register_health_routes
from app.api.action_center_routes import register_action_center_routes

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]
settings = Settings.from_env()
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
configure_runtime(lambda: db, lambda: settings)

app = FastAPI(title="Metaphora Control Tower", docs_url=None, redoc_url=None, openapi_url=None)
public_api = APIRouter(prefix="/api")
get_current_user = authenticated_user_dependency(runtime_db, settings.jwt_secret)
api = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])
operational_write = require_capability(get_current_user, "operational")
safety_write = require_capability(get_current_user, "safety")
finance_write = require_capability(get_current_user, "finance")
ai_access = require_capability(get_current_user, "ai")
owner_only = require_owner(get_current_user)
audit_reader = require_audit_reader(get_current_user)

def enforce_seed_config(force: bool) -> None:
    """Validate all configuration gates before seed reads or writes begin."""
    if not settings.allow_seed_endpoint:
        raise HTTPException(403, "Seed endpoint is disabled")
    if force and not force_seed_allowed(settings.app_env):
        raise HTTPException(403, "Forced seed is disabled in this environment")

register_auth_routes(public_api, api, get_current_user)
register_fleet_routes(api, get_current_user, safety_write)
register_load_routes(api, get_current_user, operational_write)
register_activity_audit_routes(api, get_current_user, audit_reader)
register_document_routes(api, get_current_user, operational_write)
register_legacy_invoice_routes(api, get_current_user, finance_write)
_demo_handlers = register_demo_routes(api, get_current_user, operational_write, ai_access, owner_only, enforce_seed_config, EMERGENT_LLM_KEY)
ai_chat = _demo_handlers["ai_chat"]
register_query_routes(api, get_current_user, operational_write, finance_write)

register_passport_routes(api, runtime_db, get_current_user)
register_rate_confirmation_routes(api, runtime_db, get_current_user)
register_party_verification_routes(api, runtime_db, get_current_user)
register_execution_eligibility_routes(api, runtime_db, get_current_user)
register_pickup_release_routes(api, runtime_db, get_current_user)
register_in_transit_execution_routes(api, runtime_db, get_current_user)
register_invoice_readiness_routes(api, runtime_db, get_current_user)
register_action_center_routes(api, runtime_db, get_current_user)
register_health_routes(public_api, get_current_user)

app.include_router(public_api)
app.include_router(api)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown():
    client.close()
