import json
from datetime import datetime, timedelta

import pytest

# Import the bookings Flask app
import services.bookings_service.app as bookings_app

# Import DB helpers to seed test data
from services.bookings_service.db import (
    get_connection,
    init_bookings_table,
    fetch_booking,
    create_booking,
)
from services.rooms_service.db import (
    init_rooms_table,
    create_room,
)
from services.users_service.db import (
    init_users_table,
    fetch_one,
)

from common.security import hash_password


# ─────────────────────────────────────────
# Fixtures: app + client + clean DB
# ─────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def init_db_schema():
    """
    Make sure the core tables exist once for the whole test session.
    """
    init_rooms_table()
    init_users_table()
    init_bookings_table()


@pytest.fixture(autouse=True)
def clean_db():
    """
    Clean users/rooms/bookings tables before each test.
    This assumes all three tables exist in the same DATABASE_URL.
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                # Order matters because of FKs
                cur.execute("TRUNCATE TABLE bookings RESTART IDENTITY CASCADE;")
                cur.execute("TRUNCATE TABLE rooms RESTART IDENTITY CASCADE;")
                cur.execute("TRUNCATE TABLE users RESTART IDENTITY CASCADE;")
    finally:
        conn.close()


@pytest.fixture
def client():
    """
    Flask test client for bookings_service.
    """
    bookings_app.app.config["TESTING"] = True
    with bookings_app.app.test_client() as client:
        yield client


# ─────────────────────────────────────────
# Helper: seed user + room
# ─────────────────────────────────────────

def create_test_user(role: str = "regular") -> int:
    """
    Insert a user directly into the DB and return its id.
    """
    password_hash = hash_password("test-password")
    row = fetch_one(
        """
        INSERT INTO users (first_name, last_name, username, email, password_hash, role)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        ("Test", "User", f"user_{role}", f"{role}@example.com", password_hash, role),
    )
    return row["id"]


def create_test_room() -> int:
    """
    Create a room using the rooms_service DB helper and return room_id.
    """
    room = create_room("Test Room", 10, "1st floor")
    return room["room_id"]


# ─────────────────────────────────────────
# Helper: monkeypatch auth & RBAC
# ─────────────────────────────────────────

def patch_auth(monkeypatch, *, user_id: int, role: str):
    """
    Patch require_auth and the role-check helpers inside bookings_service.app
    so endpoints think the request is authenticated as (user_id, role).
    """

    def fake_require_auth():
        return ({"sub": str(user_id), "role": role}, None)

    def fake_is_human_user(payload):
        return payload.get("role") != "service_account"

    def fake_is_admin(payload):
        return payload.get("role") == "admin"

    def fake_is_admin_or_facility(payload):
        return payload.get("role") in {"admin", "facility_manager"}

    def fake_is_auditor(payload):
        return payload.get("role") == "auditor"

    monkeypatch.setattr(bookings_app, "require_auth", fake_require_auth)
    monkeypatch.setattr(bookings_app, "is_human_user", fake_is_human_user)
    monkeypatch.setattr(bookings_app, "is_admin", fake_is_admin)
    monkeypatch.setattr(bookings_app, "is_admin_or_facility", fake_is_admin_or_facility)
    monkeypatch.setattr(bookings_app, "is_auditor", fake_is_auditor)


# ─────────────────────────────────────────
# 1. CREATE BOOKING
# ─────────────────────────────────────────

def test_create_booking_success(client, monkeypatch):
    user_id = create_test_user(role="regular")
    room_id = create_test_room()
    patch_auth(monkeypatch, user_id=user_id, role="regular")

    start = datetime.utcnow() + timedelta(hours=1)
    end = start + timedelta(hours=1)

    resp = client.post(
        bookings_app.API_VERSION + "/bookings",
        json={
            "room_id": room_id,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
    )

    assert resp.status_code == 201
    data = resp.get_json()
    assert "booking" in data
    booking = data["booking"]
    assert booking["user_id"] == user_id
    assert booking["room_id"] == room_id


def test_create_booking_rejects_past_start(client, monkeypatch):
    user_id = create_test_user(role="regular")
    room_id = create_test_room()
    patch_auth(monkeypatch, user_id=user_id, role="regular")

    start = datetime.utcnow() - timedelta(hours=1)
    end = datetime.utcnow() + timedelta(hours=1)

    resp = client.post(
        bookings_app.API_VERSION + "/bookings",
        json={
            "room_id": room_id,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
    )

    assert resp.status_code == 400
    msg = resp.get_json().get("details", "") or resp.get_json().get("message", "")
    assert "future" in msg.lower()


def test_create_booking_conflict(client, monkeypatch):
    user_id = create_test_user(role="regular")
    room_id = create_test_room()
    patch_auth(monkeypatch, user_id=user_id, role="regular")

    # First booking (direct via DB helper)
    start = datetime.utcnow() + timedelta(hours=2)
    end = start + timedelta(hours=2)
    create_booking(user_id, room_id, start, end)

    # Second, overlapping booking via API
    overlap_start = start + timedelta(minutes=30)
    overlap_end = overlap_start + timedelta(hours=1)

    resp = client.post(
        bookings_app.API_VERSION + "/bookings",
        json={
            "room_id": room_id,
            "start_time": overlap_start.isoformat(),
            "end_time": overlap_end.isoformat(),
        },
    )

    assert resp.status_code == 409
    msg = resp.get_json().get("details", "") or resp.get_json().get("message", "")
    assert "already booked" in msg.lower()


# ─────────────────────────────────────────
# 2. UPDATE BOOKING
# ─────────────────────────────────────────

def test_update_booking_by_owner_success(client, monkeypatch):
    user_id = create_test_user(role="regular")
    room_id = create_test_room()
    patch_auth(monkeypatch, user_id=user_id, role="regular")

    # Seed booking
    start = datetime.utcnow() + timedelta(hours=3)
    end = start + timedelta(hours=1)
    row = create_booking(user_id, room_id, start, end)
    booking_id = row["booking_id"]

    new_start = start + timedelta(hours=1)
    new_end = new_start + timedelta(hours=1)

    resp = client.put(
        f"{bookings_app.API_VERSION}/bookings/{booking_id}",
        json={
            "start_time": new_start.isoformat(),
            "end_time": new_end.isoformat(),
        },
    )

    assert resp.status_code == 200
    data = resp.get_json()["booking"]
    assert data["booking_id"] == booking_id
    assert data["start_time"] == new_start.isoformat()
    assert data["end_time"] == new_end.isoformat()


# ─────────────────────────────────────────
# 3. DELETE BOOKING
# ─────────────────────────────────────────

def test_delete_booking_by_admin(client, monkeypatch):
    # Owner is regular user; admin deletes
    owner_id = create_test_user(role="regular")
    admin_id = create_test_user(role="admin")
    room_id = create_test_room()

    # Seed booking
    start = datetime.utcnow() + timedelta(hours=4)
    end = start + timedelta(hours=1)
    row = create_booking(owner_id, room_id, start, end)
    booking_id = row["booking_id"]

    # Authenticate as admin
    patch_auth(monkeypatch, user_id=admin_id, role="admin")

    resp = client.delete(f"{bookings_app.API_VERSION}/bookings/{booking_id}")
    assert resp.status_code == 200
    assert resp.get_json()["message"].lower().startswith("booking cancelled")

    # Verify deleted
    assert fetch_booking(booking_id) is None


# ─────────────────────────────────────────
# 4. CHECK AVAILABILITY
# ─────────────────────────────────────────

def test_check_availability_available_and_not_available(client, monkeypatch):
    user_id = create_test_user(role="regular")
    room_id = create_test_room()
    patch_auth(monkeypatch, user_id=user_id, role="regular")

    start = datetime.utcnow() + timedelta(hours=5)
    end = start + timedelta(hours=1)
    create_booking(user_id, room_id, start, end)

    # Range BEFORE the booking → should be available
    before_start = start - timedelta(hours=2)
    before_end = start - timedelta(hours=1)

    resp_free = client.get(
        bookings_app.API_VERSION + "/bookings/check",
        query_string={
            "room_id": room_id,
            "start_time": before_start.isoformat(),
            "end_time": before_end.isoformat(),
        },
    )
    assert resp_free.status_code == 200
    assert resp_free.get_json()["available"] is True

    # Overlapping range → should NOT be available
    overlap_start = start + timedelta(minutes=30)
    overlap_end = overlap_start + timedelta(hours=1)

    resp_busy = client.get(
        bookings_app.API_VERSION + "/bookings/check",
        query_string={
            "room_id": room_id,
            "start_time": overlap_start.isoformat(),
            "end_time": overlap_end.isoformat(),
        },
    )
    assert resp_busy.status_code == 200
    assert resp_busy.get_json()["available"] is False


# ─────────────────────────────────────────
# 5. AUDIT LOGS ENDPOINT
# ─────────────────────────────────────────

def test_get_service_logs_admin_only(client, monkeypatch):
    admin_id = create_test_user(role="admin")

    # Patch auth as admin
    patch_auth(monkeypatch, user_id=admin_id, role="admin")

    # Patch _tail_log to avoid depending on real file contents
    fake_lines = ["line1\n", "line2\n"]

    def fake_tail(path, max_lines):
        return fake_lines

    monkeypatch.setattr(bookings_app, "_tail_log", fake_tail)

    resp = client.get(bookings_app.API_VERSION + "/ops/logs")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["lines"] == fake_lines


def test_get_service_logs_forbidden_for_non_admin(client, monkeypatch):
    user_id = create_test_user(role="regular")
    patch_auth(monkeypatch, user_id=user_id, role="regular")

    resp = client.get(bookings_app.API_VERSION + "/ops/logs")
    assert resp.status_code == 403
