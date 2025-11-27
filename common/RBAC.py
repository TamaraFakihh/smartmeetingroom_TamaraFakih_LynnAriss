from common.security import decode_access_token
from flask import request
from common.exeptions import SmartRoomExceptions

# ─────────────────────────────────────────────
# Auth & RBAC helpers (mirroring users_service style)
# ─────────────────────────────────────────────

def get_current_user_payload():
    """
    Helper to read Authorization header, decode JWT, and return token payload.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1]
    payload = decode_access_token(token)
    return payload


def require_auth():
    """
    Helper to enforce authentication.
    Returns (payload, error_response) where error_response is a Flask response or None.
    """
    payload = get_current_user_payload()
    if not payload:
        raise SmartRoomExceptions(401, "Unauthorized", "Make sure your token is valid and not expired.")
    return payload, None


def is_admin(payload: dict) -> bool:
    return payload.get("role") == "admin"

def is_moderator(payload: dict) -> bool:
    return payload.get("role") == "moderator"

def is_facility_manager(payload: dict) -> bool:
    return payload.get("role") == "facility_manager"

def is_facility(payload: dict) -> bool:
    return payload.get("role") == "facility_manager"

def is_regular(payload: dict) -> bool:
    """
    Allow only 'auditor' and 'service_account' roles.
    """
    return payload.get("role") in {"regular"}

def is_admin_or_facility(payload: dict) -> bool:
    return payload.get("role") in {"admin", "facility_manager"}

def is_auditor(payload: dict) -> bool:
    return payload.get("role") == "auditor"

def is_human_user(payload: dict) -> bool:
    """
    Exclude 'service_account' from normal interactive operations.
    """
    return payload.get("role") in {
        "regular",
        "admin",
        "facility_manager",
        "moderator",
        "auditor",
    }

def read_only(payload: dict) -> bool:
    """
    Allow only 'auditor' and 'service_account' roles.
    """
    return payload.get("role") in {
        "auditor",
        "regular",
    }