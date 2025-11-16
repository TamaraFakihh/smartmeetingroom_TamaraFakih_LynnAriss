import datetime as dt
from typing import Optional, Dict, Any

import jwt
from werkzeug.security import generate_password_hash, check_password_hash

from common.config import JWT_SECRET_KEY, JWT_EXP_MINUTES


def hash_password(plain_password: str) -> str:
    """
    Hash a raw password using a strong algorithm (PBKDF2 via Werkzeug).
    """
    return generate_password_hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """
    Verify a raw password against the stored hash.
    """
    return check_password_hash(password_hash, plain_password)


def create_access_token(user_id: int, role: str) -> str:
    """
    Create a JWT access token that encodes the user id and role.

    NOTE: PyJWT expects the `sub` (subject) claim to be a STRING.
    So we store str(user_id) here.
    """
    now = dt.datetime.utcnow()
    payload = {
        "sub": str(user_id),  # <-- IMPORTANT: cast to string
        "role": role,
        "iat": now,
        "exp": now + dt.timedelta(minutes=JWT_EXP_MINUTES),
    }
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode and validate a JWT access token.
    Returns the payload if valid, None otherwise.
    """
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=["HS256"],
        )
        return payload
    except jwt.ExpiredSignatureError as e:
        print("JWT EXPIRED:", e)
        return None
    except jwt.InvalidTokenError as e:
        print("JWT DECODE ERROR:", repr(e))
        return None
