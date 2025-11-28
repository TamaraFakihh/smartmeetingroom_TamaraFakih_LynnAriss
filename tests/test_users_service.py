# tests/test_users_service.py

import hashlib
from datetime import datetime, timedelta

import pytest

import services.users_service.app as users_app
from services.users_service.db import (
    init_users_table,
    get_connection,
    fetch_one,
    create_reset_token,
)
from common.config import API_VERSION


# ─────────────────────────────────────────
# GLOBAL FIXTURES
# ─────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def init_db_schema():
    """
    Ensure the users and password_reset_tokens tables exist once per test session.
    """
    init_users_table()


@pytest.fixture(autouse=True)
def clean_users_tables():
    """
    Clean users-related tables before each test to ensure isolation.
    Cascades will clean dependent data (e.g., bookings).
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM password_reset_tokens;")
                cur.execute("DELETE FROM users;")
    finally:
        conn.close()


@pytest.fixture
def client():
    """
    Flask test client for the users_service.
    """
    app = users_app.app
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ─────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────

def register_user(client, username, email, password="StrongPass123!", role="regular"):
    """
    Helper to register a user via the API.
    """
    payload = {
        "first_name": "Test",
        "last_name": "User",
        "username": username,
        "email": email,
        "password": password,
        "role": role,
    }
    return client.post(f"{API_VERSION}/users/register", json=payload)


def login_user(client, username, password="StrongPass123!"):
    """
    Helper to login and return (response, token or None).
    """
    resp = client.post(
        f"{API_VERSION}/auth/login",
        json={"username": username, "password": password},
    )
    if resp.status_code == 200:
        token = resp.get_json()["access_token"]
        return resp, token
    return resp, None


def auth_headers(token: str) -> dict:
    """
    Build Authorization headers for a given access token.
    """
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────────────────────
# 1. REGISTER TESTS
# ─────────────────────────────────────────

def test_register_user_success(client):
    resp = register_user(client, "alice", "alice@example.com")
    assert resp.status_code == 201

    data = resp.get_json()
    assert "user" in data
    user = data["user"]
    assert user["username"] == "alice"
    assert user["email"] == "alice@example.com"
    assert user["role"] == "regular"
    assert "password_hash" not in user


def test_register_user_invalid_username(client):
    # invalid because starts with a dot
    resp = register_user(client, ".badname", "bad@example.com")
    assert resp.status_code == 400
    data = resp.get_json()
    assert "Username must start and end with a letter or digit" in data["details"]


def test_register_user_invalid_email(client):
    resp = register_user(client, "bob", "not-an-email")
    assert resp.status_code == 400
    data = resp.get_json()
    assert "Invalid email format" in data["details"]


def test_register_user_duplicate_username_or_email(client):
    # First registration OK
    first = register_user(client, "charlie", "charlie@example.com")
    assert first.status_code == 201

    # Second registration with same username or email should conflict
    resp = register_user(client, "charlie", "another@example.com")
    assert resp.status_code == 409

    resp2 = register_user(client, "other", "charlie@example.com")
    assert resp2.status_code == 409


# ─────────────────────────────────────────
# 2. LOGIN TESTS
# ─────────────────────────────────────────

def test_login_success(client):
    register_user(client, "dana", "dana@example.com")
    resp, token = login_user(client, "dana")

    assert resp.status_code == 200
    assert token is not None

    data = resp.get_json()
    assert "user" in data
    assert data["user"]["username"] == "dana"


def test_login_invalid_credentials(client):
    register_user(client, "ed", "ed@example.com")

    # wrong password
    resp = client.post(
        f"{API_VERSION}/auth/login",
        json={"username": "ed", "password": "WrongPass!"},
    )
    assert resp.status_code == 401

    # unknown user
    resp2 = client.post(
        f"{API_VERSION}/auth/login",
        json={"username": "noone", "password": "whatever"},
    )
    assert resp2.status_code == 401


def test_login_missing_fields(client):
    resp = client.post(f"{API_VERSION}/auth/login", json={"username": "x"})
    assert resp.status_code == 400


# ─────────────────────────────────────────
# 3. PASSWORD RESET TESTS
# ─────────────────────────────────────────

def test_request_password_reset_creates_token(client):
    # Create a user
    register_user(client, "frank", "frank@example.com")
    row = fetch_one(
        "SELECT id FROM users WHERE username = %s", ("frank",)
    )
    user_id = row["id"]

    # Request reset by email
    resp = client.post(
        f"{API_VERSION}/auth/password-reset/request",
        json={"email": "frank@example.com"},
    )
    assert resp.status_code == 200
    msg = resp.get_json()["message"]
    assert "If the account exists" in msg

    # Verify that a token row exists
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM password_reset_tokens WHERE user_id = %s",
                    (user_id,),
                )
                count = cur.fetchone()[0]
    finally:
        conn.close()

    assert count == 1


def test_confirm_password_reset_success(client):
    # Create user with known password
    register_user(client, "gina", "gina@example.com", password="OldPass123!")
    row = fetch_one(
        "SELECT id FROM users WHERE username = %s", ("gina",)
    )
    user_id = row["id"]

    # Manually create a valid reset token in DB
    raw_token = "reset-token-gina"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.utcnow() + timedelta(minutes=10)
    create_reset_token(user_id, token_hash, expires_at)

    # Confirm reset via API
    resp = client.post(
        f"{API_VERSION}/auth/password-reset/confirm",
        json={
            "token": raw_token,
            "new_password": "NewPass123!",
        },
    )
    assert resp.status_code == 200
    assert resp.get_json()["message"] == "Password reset successful."

    # Login with new password should succeed
    resp_login, token = login_user(client, "gina", password="NewPass123!")
    assert resp_login.status_code == 200
    assert token is not None


def test_confirm_password_reset_invalid_token(client):
    resp = client.post(
        f"{API_VERSION}/auth/password-reset/confirm",
        json={
            "token": "non-existent-token",
            "new_password": "SomePass123!",
        },
    )
    assert resp.status_code == 400
    assert "Invalid or expired reset token" in resp.get_json()["details"]


# ─────────────────────────────────────────
# 4. SELF PROFILE TESTS: /users/me
# ─────────────────────────────────────────

def test_get_my_profile(client):
    register_user(client, "hannah", "hannah@example.com")
    _, token = login_user(client, "hannah")

    resp = client.get(
        f"{API_VERSION}/users/me",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    user = resp.get_json()["user"]
    assert user["username"] == "hannah"
    assert user["email"] == "hannah@example.com"


def test_update_my_profile_success(client):
    register_user(client, "ian", "ian@example.com")
    _, token = login_user(client, "ian")

    new_data = {
        "first_name": "IanUpdated",
        "last_name": "UserUpdated",
        "email": "ian.updated@example.com",
    }
    resp = client.put(
        f"{API_VERSION}/users/me",
        json=new_data,
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    user = resp.get_json()["user"]
    assert user["first_name"] == "IanUpdated"
    assert user["last_name"] == "UserUpdated"
    assert user["email"] == "ian.updated@example.com".lower()


def test_update_my_profile_conflict_username(client):
    # two users: jake and jane
    register_user(client, "jake", "jake@example.com")
    register_user(client, "jane", "jane@example.com")

    _, token_jane = login_user(client, "jane")

    # Jane tries to change username to "jake"
    resp = client.put(
        f"{API_VERSION}/users/me",
        json={"username": "jake"},
        headers=auth_headers(token_jane),
    )
    assert resp.status_code == 409
    assert "Username already in use" in resp.get_json()["details"]


def test_update_my_profile_no_fields(client):
    register_user(client, "kate", "kate@example.com")
    _, token = login_user(client, "kate")

    resp = client.put(
        f"{API_VERSION}/users/me",
        json={},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert "No valid fields provided" in resp.get_json()["details"]


def test_delete_my_account(client):
    register_user(client, "leo", "leo@example.com")
    _, token = login_user(client, "leo")

    resp = client.delete(
        f"{API_VERSION}/users/me",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200

    # After deletion, login should fail
    resp_login = client.post(
        f"{API_VERSION}/auth/login",
        json={"username": "leo", "password": "StrongPass123!"},
    )
    assert resp_login.status_code == 401


# ─────────────────────────────────────────
# 5. ADMIN ENDPOINT TESTS
# ─────────────────────────────────────────

def test_get_all_users_admin_only(client):
    # create admin
    register_user(client, "adminuser", "admin@example.com", role="admin")
    _, admin_token = login_user(client, "adminuser")

    # create a couple of regular users
    register_user(client, "mike", "mike@example.com")
    register_user(client, "nina", "nina@example.com")

    # admin should see all
    resp = client.get(
        f"{API_VERSION}/users",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    users = resp.get_json()["users"]
    usernames = {u["username"] for u in users}
    assert {"adminuser", "mike", "nina"}.issubset(usernames)

    # non-admin should be forbidden
    _, token_mike = login_user(client, "mike")
    resp2 = client.get(
        f"{API_VERSION}/users",
        headers=auth_headers(token_mike),
    )
    assert resp2.status_code == 403


def test_get_user_by_username_permissions(client):
    # create admin and two regular users
    register_user(client, "adminuser", "admin@example.com", role="admin")
    register_user(client, "oliver", "oliver@example.com")
    register_user(client, "paula", "paula@example.com")

    _, admin_token = login_user(client, "adminuser")
    _, oliver_token = login_user(client, "oliver")
    _, paula_token = login_user(client, "paula")

    # admin can fetch any user
    resp_admin = client.get(
        f"{API_VERSION}/users/oliver",
        headers=auth_headers(admin_token),
    )
    assert resp_admin.status_code == 200
    assert resp_admin.get_json()["user"]["username"] == "oliver"

    # oliver can fetch himself
    resp_self = client.get(
        f"{API_VERSION}/users/oliver",
        headers=auth_headers(oliver_token),
    )
    assert resp_self.status_code == 200

    # paula cannot fetch oliver
    resp_forbidden = client.get(
        f"{API_VERSION}/users/oliver",
        headers=auth_headers(paula_token),
    )
    assert resp_forbidden.status_code == 403


def test_admin_update_user_including_role(client):
    # admin + regular user
    register_user(client, "adminuser", "admin@example.com", role="admin")
    register_user(client, "quentin", "quentin@example.com")

    _, admin_token = login_user(client, "adminuser")

    # look up quentin's id
    row = fetch_one(
        "SELECT id FROM users WHERE username = %s", ("quentin",)
    )
    user_id = row["id"]

    payload = {
        "first_name": "QuentinUpdated",
        "role": "facility_manager",
    }
    resp = client.put(
        f"{API_VERSION}/users/{user_id}",
        json=payload,
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    user = resp.get_json()["user"]
    assert user["first_name"] == "QuentinUpdated"
    assert user["role"] == "facility_manager"


def test_admin_delete_user(client):
    register_user(client, "adminuser", "admin@example.com", role="admin")
    register_user(client, "rachel", "rachel@example.com")

    _, admin_token = login_user(client, "adminuser")

    row = fetch_one(
        "SELECT id FROM users WHERE username = %s", ("rachel",)
    )
    user_id = row["id"]

    resp = client.delete(
        f"{API_VERSION}/users/{user_id}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200

    # user should be gone
    row_after = fetch_one(
        "SELECT id FROM users WHERE username = %s", ("rachel",)
    )
    assert row_after is None


# ─────────────────────────────────────────
# 6. OPS LOGS (ADMIN ONLY)
# ─────────────────────────────────────────

def test_get_service_logs_admin_only(client):
    register_user(client, "adminuser", "admin@example.com", role="admin")
    register_user(client, "sam", "sam@example.com")

    _, admin_token = login_user(client, "adminuser")
    _, sam_token = login_user(client, "sam")

    # admin can access logs
    resp = client.get(
        f"{API_VERSION}/ops/logs",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "lines" in body
    assert isinstance(body["lines"], list)

    # non-admin must be forbidden
    resp2 = client.get(
        f"{API_VERSION}/ops/logs",
        headers=auth_headers(sam_token),
    )
    assert resp2.status_code == 403
