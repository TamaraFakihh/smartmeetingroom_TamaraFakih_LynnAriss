import logging
import sys
import time
import uuid
import re

from flask import Flask, request, jsonify, g

from services.users_service.db import init_users_table, fetch_one, fetch_all, execute
from services.users_service.models import User
from common.email_service import send_templated_email, EmailConfigurationError
from common.security import (
    hash_password,
    verify_password,
    create_access_token,
)
from common.RBAC import (
    require_auth,
    is_admin,
)
from common.exeptions import *
from common.config import API_VERSION

app = Flask(__name__)

# ─────────────────────────────────────────
# Logging configuration (stdout for Docker)
# ─────────────────────────────────────────
logger = logging.getLogger("users_service")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)
logger.propagate = False
app.logger = logger

@app.errorhandler(SmartRoomExceptions)
def handle_smart_room_exception(e):
    return jsonify(e.to_dict()), e.status_code

@app.before_request
def start_audit_logging():
    g.request_id = str(uuid.uuid4())
    g.start_time = time.time()
    app.logger.info(
        "REQUEST",
        extra={
            "request_id": g.request_id,
            "method": request.method,
            "path": request.path,
            "remote_addr": request.remote_addr,
            "user_agent": request.user_agent.string,
        },
    )

@app.after_request
def end_audit_logging(response):
    duration = time.time() - g.get("start_time", time.time())
    app.logger.info(
        "RESPONSE",
        extra={
            "request_id": g.get("request_id"),
            "status_code": response.status_code,
            "path": request.path,
            "duration_ms": int(duration * 1000),
        },
    )
    response.headers["X-Request-ID"] = g.get("request_id", "")
    return response

# Initialize DB tables once at startup (Flask 3 has no before_first_request)
init_users_table()

# Precompiled regex patterns matching your rules
USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$')
EMAIL_PATTERN = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', re.IGNORECASE)

RESERVED_USERNAMES = {"admin", "root", "support", "system", "null"}

ALLOWED_ROLES = {
    "regular",
    "admin",
    "facility_manager",
    "moderator",
    "auditor",
    "service_account",
}


def validate_username(username: str) -> str | None:
    """
    raise error message if invalid, else None.
    """
    if not (3 <= len(username) <= 15):
        return "Username must be between 3 and 15 characters."

    if not USERNAME_PATTERN.match(username):
        return (
            "Username must start and end with a letter or digit and may contain "
            "letters, digits, ., _ and - in the middle (no spaces)."
        )

    if re.search(r'(\.|_|-){2,}', username):
        return "Username cannot contain two special characters (., _, -) in a row."

    if username.lower() in RESERVED_USERNAMES:
        return "This username is reserved. Please choose another one."

    return None


def validate_email(email: str) -> str | None:
    """
    raise error message if invalid, else None.
    """
    if not EMAIL_PATTERN.match(email):
        return "Invalid email format."

    if len(email) > 254:
        return "Email is too long (must be at most 254 characters)."

    local_part = email.split("@", 1)[0]
    if len(local_part) > 64:
        return "Email local part (before @) must be at most 64 characters."

    return None

# ─────────────────────────────────────────────
# 1. REGISTER
# ─────────────────────────────────────────────

@app.route(f"{API_VERSION}/users/register", methods=["POST"])
def register_user():
    """
    Register a new user.

    Expected JSON body:
    {
        "first_name": "...",
        "last_name": "...",
        "username": "...",
        "email": "...",
        "password": "...",
        "role": "regular"  # optional
    }
    """
    data = request.get_json() or {}

    required_fields = ["first_name", "last_name", "username", "email", "password"]
    missing = [f for f in required_fields if not data.get(f)]
    if missing:
        raise SmartRoomExceptions(400, "Bad Request", f"Missing fields: {', '.join(missing)}")

    first_name = data["first_name"].strip()
    last_name = data["last_name"].strip()
    username = data["username"].strip().lower()   # normalize to lowercase
    email = data["email"].strip().lower()         # normalize to lowercase
    password = data["password"]
    role = data.get("role", "regular")

    # Validate username
    username_error = validate_username(username)
    if username_error:
        raise SmartRoomExceptions(400, "Bad Request", username_error)

    # Validate email
    email_error = validate_email(email)
    if email_error:
        raise SmartRoomExceptions(400, "Bad Request", email_error)

    # Validate role (just in case, even though DB also checks)
    if role not in ALLOWED_ROLES:
        raise SmartRoomExceptions(400, "Bad Request", "Invalid role value.")
    
    # Check if username or email already exists
    existing = fetch_one(
        "SELECT 1 FROM users WHERE username = %s OR email = %s",
        (username, email),
    )
    if existing:
        raise SmartRoomExceptions(409, "Conflict", "Username or email already in use.")

    password_hash = hash_password(password)

    insert_sql = """
    INSERT INTO users (first_name, last_name, username, email, password_hash, role)
    VALUES (%s, %s, %s, %s, %s, %s)
    RETURNING id, first_name, last_name, username, email, role;
    """

    row = fetch_one(
        insert_sql,
        (first_name, last_name, username, email, password_hash, role),
    )

    user = User(
        id=row["id"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        username=row["username"],
        email=row["email"],
        password_hash="",
        role=row["role"],
    )

    return jsonify({"user": user.to_public_dict()}), 201


# ─────────────────────────────────────────────
# 2. LOGIN
# ─────────────────────────────────────────────

@app.route(f"{API_VERSION}/auth/login", methods=["POST"])
def login():
    """
    Log in a user and return an access token.

    Expected JSON:
    {
        "username": "...",
        "password": "..."
    }
    """
    data = request.get_json() or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")

    if not username or not password:
        raise SmartRoomExceptions(400, "Bad Request", "Username and password are required.")

    row = fetch_one("SELECT * FROM users WHERE username = %s", (username,))
    if not row:
        raise SmartRoomExceptions(401, "Unauthorized", "Invalid credentials.")
    
    if not verify_password(password, row["password_hash"]):
        raise SmartRoomExceptions(401, "Unauthorized", "Invalid credentials.")

    token = create_access_token(row["id"], row["role"])

    user = User(
        id=row["id"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        username=row["username"],
        email=row["email"],
        password_hash="",
        role=row["role"],
    )

    # Fire-and-forget sign-in email; logging captures any send issues without blocking login.
    try:
        status_code, message_id = send_templated_email(
            to_email=user.email,
            subject="Smart Meeting Rooms sign-in",
            template_name="SignIn.html",
            context={
                "first_name": user.first_name,
                "last_name": user.last_name,
                "username": user.username,
                "email": user.email,
            },
        )
        if status_code != 202:
            app.logger.warning(
                "Sign-in email returned unexpected status %s for user %s",
                status_code,
                user.username,
            )
        else:
            app.logger.info(
                "Sign-in email sent for user %s (message_id=%s)",
                user.username,
                message_id,
            )
    except EmailConfigurationError as cfg_err:
        app.logger.warning("Sign-in email skipped: %s", cfg_err)
    except Exception as email_err:
        app.logger.exception("Failed to send sign-in email: %s", email_err)

    return jsonify({
        "access_token": token,
        "user": user.to_public_dict()
    }), 200


# ─────────────────────────────────────────────
# 3. GET CURRENT USER
# ─────────────────────────────────────────────

@app.route(f"{API_VERSION}/users/me", methods=["GET"])
def get_my_profile():
    """
    Return the profile of the currently authenticated user.

    Requires Authorization: Bearer <token>
    """
    payload, error = require_auth()
    if error:
        raise error

    user_id = int(payload["sub"])

    row = fetch_one(
        "SELECT id, first_name, last_name, username, email, role FROM users WHERE id = %s",
        (user_id,),
    )
    if not row:
        raise SmartRoomExceptions(404, "Not Found", "User not found.")

    user = User(
        id=row["id"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        username=row["username"],
        email=row["email"],
        password_hash="",
        role=row["role"],
    )

    return jsonify({"user": user.to_public_dict()}), 200


# ─────────────────────────────────────────────
# 4. UPDATE OWN PROFILE
# ─────────────────────────────────────────────

@app.route(f"{API_VERSION}/users/me", methods=["PUT"])
def update_my_profile():
    """
    Update the profile of the currently authenticated user.

    Allowed fields: first_name, last_name, username, email, password.
    Role change must be done by admin via /users/<user_id>.
    """
    payload, error = require_auth()
    if error:
        raise error

    user_id = int(payload["sub"])
    data = request.get_json() or {}

    fields_to_update = []
    params = []

    # First name
    if "first_name" in data and data["first_name"].strip():
        fields_to_update.append("first_name = %s")
        params.append(data["first_name"].strip())

    # Last name
    if "last_name" in data and data["last_name"].strip():
        fields_to_update.append("last_name = %s")
        params.append(data["last_name"].strip())

    # Username
    if "username" in data and data["username"].strip():
        new_username = data["username"].strip().lower()
        username_error = validate_username(new_username)
        if username_error:
            raise SmartRoomExceptions(400, "Bad Request", username_error)

        # Check if taken by someone else
        existing = fetch_one(
            "SELECT id FROM users WHERE username = %s AND id <> %s",
            (new_username, user_id),
        )
        if existing:
            raise SmartRoomExceptions(409, "Conflict", "Username already in use.")

        fields_to_update.append("username = %s")
        params.append(new_username)

    # Email
    if "email" in data and data["email"].strip():
        new_email = data["email"].strip().lower()
        email_error = validate_email(new_email)
        if email_error:
            raise SmartRoomExceptions(400, "Bad Request", email_error)

        existing = fetch_one(
            "SELECT id FROM users WHERE email = %s AND id <> %s",
            (new_email, user_id),
        )
        if existing:
            raise SmartRoomExceptions(409, "Conflict", "Email already in use.")

        fields_to_update.append("email = %s")
        params.append(new_email)

    # Password
    if "password" in data and data["password"]:
        new_password_hash = hash_password(data["password"])
        fields_to_update.append("password_hash = %s")
        params.append(new_password_hash)

    if not fields_to_update:
        raise SmartRoomExceptions(400, "Bad Request", "No valid fields provided to update.")

    # Build dynamic UPDATE
    set_clause = ", ".join(fields_to_update)
    params.append(user_id)

    update_sql = f"""
    UPDATE users
       SET {set_clause}
     WHERE id = %s
     RETURNING id, first_name, last_name, username, email, role;
    """

    row = fetch_one(update_sql, tuple(params))
    if not row:
        raise SmartRoomExceptions(404, "Not Found", "User not found.")

    user = User(
        id=row["id"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        username=row["username"],
        email=row["email"],
        password_hash="",
        role=row["role"],
    )

    return jsonify({"user": user.to_public_dict()}), 200


# ─────────────────────────────────────────────
# 5. DELETE OWN ACCOUNT
# ─────────────────────────────────────────────

@app.route(f"{API_VERSION}/users/me", methods=["DELETE"])
def delete_my_account():
    """
    Delete the currently authenticated user's account.

    Note: Later we may discuss how this interacts with bookings/reviews.
    """
    payload, error = require_auth()
    if error:
        raise error

    user_id = int(payload["sub"])

    deleted = execute("DELETE FROM users WHERE id = %s", (user_id,))
    if deleted == 0:
        raise SmartRoomExceptions(404, "Not Found", "User not found.")

    return jsonify({"message": "Account deleted successfully."}), 200


# ─────────────────────────────────────────────
# 6. ADMIN: GET ALL USERS
# ─────────────────────────────────────────────

@app.route(f"{API_VERSION}/users", methods=["GET"])
def get_all_users():
    """
    Return all users.
    Admin-only endpoint.
    """
    payload, error = require_auth()
    if error:
        raise error

    if not is_admin(payload):
        raise SmartRoomExceptions(403, "Forbidden", "Admins only.")

    rows = fetch_all(
        "SELECT id, first_name, last_name, username, email, role FROM users ORDER BY id"
    )

    users = [
        User(
            id=row["id"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            username=row["username"],
            email=row["email"],
            password_hash="",
            role=row["role"],
        ).to_public_dict()
        for row in rows
    ]

    return jsonify({"users": users}), 200


# ─────────────────────────────────────────────
# 7. GET SPECIFIC USER BY USERNAME
# ─────────────────────────────────────────────

@app.route(f"{API_VERSION}/users/<string:username>", methods=["GET"])
def get_user_by_username(username: str):
    """
    Get details of a specific user by username.

    - Admin: can view anyone.
    - Regular: can only view themselves.
    """
    payload, error = require_auth()
    if error:
        raise error

    user_id = int(payload["sub"])
    target_username = username.strip().lower()

    row = fetch_one(
        "SELECT id, first_name, last_name, username, email, role FROM users WHERE username = %s",
        (target_username,),
    )
    if not row:
        raise SmartRoomExceptions(404, "Not Found", "User not found.")

    # If not admin, ensure they are requesting their own profile
    if not is_admin(payload) and row["id"] != user_id:
        raise SmartRoomExceptions(403, "Forbidden", "Forbidden.")
    
    user = User(
        id=row["id"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        username=row["username"],
        email=row["email"],
        password_hash="",
        role=row["role"],
    )

    return jsonify({"user": user.to_public_dict()}), 200


# ─────────────────────────────────────────────
# 8. ADMIN: UPDATE USER (INCL. ROLE)
# ─────────────────────────────────────────────

@app.route(f"{API_VERSION}/users/<int:user_id>", methods=["PUT"])
def admin_update_user(user_id: int):
    """
    Admin-only endpoint to update another user's profile and role.

    Allowed fields: first_name, last_name, username, email, password, role.
    """
    payload, error = require_auth()
    if error:
        raise error

    if not is_admin(payload):
        raise SmartRoomExceptions(403, "Forbidden", "Admins only.")

    data = request.get_json() or {}

    fields_to_update = []
    params = []

    # First name
    if "first_name" in data and data["first_name"].strip():
        fields_to_update.append("first_name = %s")
        params.append(data["first_name"].strip())

    # Last name
    if "last_name" in data and data["last_name"].strip():
        fields_to_update.append("last_name = %s")
        params.append(data["last_name"].strip())

    # Username
    if "username" in data and data["username"].strip():
        new_username = data["username"].strip().lower()
        username_error = validate_username(new_username)
        if username_error:
            raise SmartRoomExceptions(400, "Bad Request", username_error)

        existing = fetch_one(
            "SELECT id FROM users WHERE username = %s AND id <> %s",
            (new_username, user_id),
        )
        if existing:
            raise SmartRoomExceptions(409, "Conflict", "Username already in use.")

        fields_to_update.append("username = %s")
        params.append(new_username)

    # Email
    if "email" in data and data["email"].strip():
        new_email = data["email"].strip().lower()
        email_error = validate_email(new_email)
        if email_error:
            raise SmartRoomExceptions(400, "Bad Request", email_error)

        existing = fetch_one(
            "SELECT id FROM users WHERE email = %s AND id <> %s",
            (new_email, user_id),
        )
        if existing:
            raise SmartRoomExceptions(409, "Conflict", "Email already in use.")

        fields_to_update.append("email = %s")
        params.append(new_email)

    # Password
    if "password" in data and data["password"]:
        new_password_hash = hash_password(data["password"])
        fields_to_update.append("password_hash = %s")
        params.append(new_password_hash)

    # Role
    if "role" in data:
        new_role = data["role"]
        if new_role not in ALLOWED_ROLES:
            raise SmartRoomExceptions(400, "Bad Request", "Invalid role value.")
        fields_to_update.append("role = %s")
        params.append(new_role)

    if not fields_to_update:
        raise SmartRoomExceptions(400, "Bad Request", "No valid fields provided to update.")

    set_clause = ", ".join(fields_to_update)
    params.append(user_id)

    update_sql = f"""
    UPDATE users
       SET {set_clause}
     WHERE id = %s
     RETURNING id, first_name, last_name, username, email, role;
    """

    row = fetch_one(update_sql, tuple(params))
    if not row:
        raise SmartRoomExceptions(404, "Not Found", "User not found.")

    user = User(
        id=row["id"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        username=row["username"],
        email=row["email"],
        password_hash="",
        role=row["role"],
    )

    return jsonify({"user": user.to_public_dict()}), 200


# ─────────────────────────────────────────────
# 9. ADMIN: DELETE USER
# ─────────────────────────────────────────────

@app.route(f"{API_VERSION}/users/<int:user_id>", methods=["DELETE"])
def admin_delete_user(user_id: int):
    """
    Admin-only endpoint to delete a specific user by ID.
    """
    payload, error = require_auth()
    if error:
        raise error

    if not is_admin(payload):
        raise SmartRoomExceptions(403, "Forbidden", "Admins only.")

    deleted = execute("DELETE FROM users WHERE id = %s", (user_id,))
    if deleted == 0:
        raise SmartRoomExceptions(404, "Not Found", "User not found.")
    
    return jsonify({"message": "User deleted successfully."}), 200


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # For development only; later we'll run via gunicorn or Docker
    app.run(host="0.0.0.0", port=5001, debug=True)
