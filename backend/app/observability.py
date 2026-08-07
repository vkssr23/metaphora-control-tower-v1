"""Small standard-library structured logging and request correlation baseline."""
import json
import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

REQUEST_ID=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SENSITIVE=frozenset({"authorization","password","password_hash","jwt","jwt_secret","token","api_key","document_contents"})

def request_id(value):
    return value if isinstance(value,str) and REQUEST_ID.fullmatch(value) else "req_"+uuid.uuid4().hex

def safe_fields(fields):
    return {str(k):("[REDACTED]" if str(k).lower() in SENSITIVE else v) for k,v in fields.items() if str(k).lower() not in {"headers","body"}}

def structured_log(logger, event, **fields):
    logger.info(json.dumps({"event":event,**safe_fields(fields)},sort_keys=True,default=str))

class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid=request_id(request.headers.get("X-Request-ID")); request.state.request_id=rid; started=time.perf_counter()
        try:
            response=await call_next(request); classification="http_error" if response.status_code>=400 else "success"
        except Exception:
            structured_log(logging.getLogger("metaphora.request"),"request.completed",request_id=rid,method=request.method,path=request.url.path,status=500,error_class="unhandled",duration_ms=round((time.perf_counter()-started)*1000,2)); raise
        response.headers["X-Request-ID"]=rid
        structured_log(logging.getLogger("metaphora.request"),"request.completed",request_id=rid,method=request.method,path=request.url.path,status=response.status_code,error_class=classification,duration_ms=round((time.perf_counter()-started)*1000,2))
        return response
