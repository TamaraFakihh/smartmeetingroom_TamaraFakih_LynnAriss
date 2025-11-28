# tests/test_rooms_service.py

import pytest
from datetime import datetime

import services.rooms_service.app as rooms_app
from services.rooms_service.db import (
    init_rooms_table,
    init_equipment_table,
    init_room_equipment_table,
    get_connection,
    create_room,
    fetch_room,
)
from services.users_service.db import init_users_table
from services.bookings_service.db import init_bookings_table
from common.config import API_VERSION
from common.security import create_access_token


# ─────────────────────────────────────────
# FIXTURES: SCHEMA + CLEANUP + CLIENT
# ─────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def ensure_schema():
    """
    Make sure core tables exist once for the whole test session.
    Order matters because of foreign keys.
    """
    init_users_table()
    init_rooms_table()
    init_equipment_table()
    init_room_equipment_table()
    init_bookings_table()


@pytest.fixture(autouse=True)
def clean_tables():
    """
    Clean tables that rooms_service touches before each test.
    We only clear what we actually use here.
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                # bookings depend on rooms
                cur.execute("DELETE FROM bookings;")
                # equipment mapping depends on rooms/equipment
                cur.execute("DELETE FROM room_equipment;")
                cur.execute("DELETE FROM equipment;")
                cur.execute("DELETE FROM rooms;")
    finally:
        conn.close()


@pytest.fixture
def client():
    """
    Flask test client for rooms_service.
    """
    app = rooms_app.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def make_auth_header(user_id: int, role: str) -> dict:
    """
    Create an Authorization header with a JWT for the given user/role.
    We rely only on RBAC logic (no need to insert user rows for rooms tests).
    """
    token = create_access_token(user_id, role)
    return {"Authorization": f"Bearer {token}"}


def create_test_room(name="Room A", capacity=10, location="Floor 1"):
    """
    Directly create a room via the DB helper (no RBAC required).
    """
    row = create_room(name, capacity, location)
    return row["room_id"]


# ─────────────────────────────────────────
# 1. GET ALL ROOMS
# ─────────────────────────────────────────

def test_get_all_rooms_with_existing_rooms(client):
    # Arrange: create a couple of rooms directly in DB
    create_test_room(name="R1", capacity=5, location="L1")
    create_test_room(name="R2", capacity=8, location="L2")

    # Act
    resp = client.get(f"{API_VERSION}/rooms")

    # Assert
    assert resp.status_code == 200
    data = resp.get_json()
    assert "rooms" in data
    assert len(data["rooms"]) >= 2
    names = {r["name"] for r in data["rooms"]}
    assert "R1" in names
    assert "R2" in names


# ─────────────────────────────────────────
# 2. ADD ROOM
# ─────────────────────────────────────────

def test_add_room_success_by_admin(client):
    headers = make_auth_header(user_id=1, role="admin")

    payload = {
        "name": "Conference X",
        "capacity": 20,
        "location": "1st Floor",
        "equipment": [
            {"name": "Projector", "quantity": 1},
            {"name": "Whiteboard", "quantity": 2},
        ],
    }

    resp = client.post(f"{API_VERSION}/rooms", json=payload, headers=headers)

    # add_room raises SmartRoomExceptions with status 201
    assert resp.status_code == 201
    body = resp.get_json()
    # SmartRoomExceptions.to_dict() is expected to wrap details
    details = body.get("details", {})
    room = details.get("room", {})
    assert room.get("name") == "Conference X"
    assert room.get("capacity") == 20
    assert len(room.get("equipment", [])) == 2


def test_add_room_forbidden_for_regular_user(client):
    headers = make_auth_header(user_id=2, role="regular")

    payload = {
        "name": "BadRoom",
        "capacity": 10,
        "location": "Somewhere",
        "equipment": [{"name": "Chair", "quantity": 1}],
    }

    resp = client.post(f"{API_VERSION}/rooms", json=payload, headers=headers)
    assert resp.status_code == 403


# ─────────────────────────────────────────
# 3. GET ROOM BY ID
# ─────────────────────────────────────────

def test_get_room_by_id_requires_auth(client):
    room_id = create_test_room()

    # No Authorization header
    resp = client.get(f"{API_VERSION}/rooms/{room_id}")
    assert resp.status_code == 401 or resp.status_code == 403


def test_get_room_by_id_success_for_human_user(client):
    room_id = create_test_room(name="FocusRoom", capacity=4, location="Quiet Zone")
    headers = make_auth_header(user_id=3, role="regular")  # human user

    resp = client.get(f"{API_VERSION}/rooms/{room_id}", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    room = data["room"]
    assert room["room_id"] == room_id
    assert room["name"] == "FocusRoom"
    assert room["capacity"] == 4


def test_get_room_not_found(client):
    headers = make_auth_header(user_id=4, role="regular")
    resp = client.get(f"{API_VERSION}/rooms/99999", headers=headers)
    assert resp.status_code == 404


# ─────────────────────────────────────────
# 4. UPDATE ROOM
# ─────────────────────────────────────────

def test_update_room_details_success(client):
    room_id = create_test_room(name="OldName", capacity=5, location="L1")
    headers = make_auth_header(user_id=5, role="facility_manager")

    payload = {
        "name": "NewName",
        "capacity": 15,
        "location": "L2",
        "equipment": [
            {"name": "TV", "quantity": 1},
            {"name": "Speaker", "quantity": 2},
        ],
    }

    resp = client.put(
        f"{API_VERSION}/rooms/update/OldName",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.get_json()
    room = body["room"]
    assert room["room_id"] == room_id
    assert room["name"] == "NewName"
    assert room["capacity"] == 15
    assert room["location"] == "L2"
    assert len(room["equipment"]) == 2


def test_update_room_forbidden_for_regular(client):
    create_test_room(name="RoomX", capacity=5, location="L1")
    headers = make_auth_header(user_id=6, role="regular")

    resp = client.put(
        f"{API_VERSION}/rooms/update/RoomX",
        json={"name": "RoomY"},
        headers=headers,
    )
    assert resp.status_code == 403


# ─────────────────────────────────────────
# 5. DELETE ROOM
# ─────────────────────────────────────────

def test_delete_room_by_admin(client):
    room_id = create_test_room(name="DeleteMe", capacity=3, location="L1")
    headers = make_auth_header(user_id=7, role="admin")

    resp = client.delete(f"{API_VERSION}/rooms/{room_id}", headers=headers)
    assert resp.status_code == 200

    # Verify it is really gone
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM rooms WHERE room_id = %s;", (room_id,))
                assert cur.fetchone() is None
    finally:
        conn.close()


def test_delete_room_forbidden_for_regular(client):
    room_id = create_test_room(name="KeepMe", capacity=3, location="L1")
    headers = make_auth_header(user_id=8, role="regular")

    resp = client.delete(f"{API_VERSION}/rooms/{room_id}", headers=headers)
    assert resp.status_code == 403


# ─────────────────────────────────────────
# 6. ROOM STATUS (AVAILABILITY)
# ─────────────────────────────────────────

def test_get_room_status_no_bookings(client):
    room_id = create_test_room(name="StatusRoom", capacity=4, location="L1")

    # Use a read-only role; in your RBAC this is typically 'auditor'
    headers = make_auth_header(user_id=9, role="auditor")

    resp = client.get(f"{API_VERSION}/rooms/{room_id}/status", headers=headers)
    assert resp.status_code == 200

    data = resp.get_json()
    assert data["room_id"] == room_id
    # No bookings yet
    assert isinstance(data["bookings"], list)
    assert len(data["bookings"]) == 0
    # At least one availability interval covering today
    assert len(data["availability_intervals"]) >= 1


def test_get_room_status_forbidden_for_non_readonly(client):
    room_id = create_test_room()
    # Assuming 'regular' is not considered read_only in your RBAC
    headers = make_auth_header(user_id=10, role="regular")

    resp = client.get(f"{API_VERSION}/rooms/{room_id}/status", headers=headers)
    assert resp.status_code == 403


# ─────────────────────────────────────────
# 7. TOGGLE ROOM AVAILABILITY
# ─────────────────────────────────────────

def test_toggle_room_availability_admin(client):
    room_id = create_test_room(name="ToggleRoom", capacity=6, location="L1")
    # Ensure default is_available is True
    original = fetch_room(room_id)
    assert original["is_available"] is True

    headers = make_auth_header(user_id=11, role="admin")

    resp = client.patch(
        f"{API_VERSION}/rooms/{room_id}/toggle_availability",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["room_id"] == room_id
    assert data["is_available"] is False

    # Check in DB
    updated = fetch_room(room_id)
    assert updated["is_available"] is False


def test_toggle_room_availability_forbidden_for_regular(client):
    room_id = create_test_room(name="ToggleForbidden", capacity=6, location="L1")
    headers = make_auth_header(user_id=12, role="regular")

    resp = client.patch(
        f"{API_VERSION}/rooms/{room_id}/toggle_availability",
        headers=headers,
    )
    assert resp.status_code == 403


# ─────────────────────────────────────────
# 8. SET / UNSET OUT OF SERVICE
# ─────────────────────────────────────────

def test_set_room_out_of_service_by_facility(client):
    room_id = create_test_room(name="ServiceRoom", capacity=10, location="L1")
    headers = make_auth_header(user_id=13, role="facility_manager")

    # Mark out of service
    resp = client.post(
        f"{API_VERSION}/rooms/out_of_service/{room_id}",
        json={"is_out_of_service": True},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["room"]["is_out_of_service"] is True

    # Mark back in service
    resp2 = client.post(
        f"{API_VERSION}/rooms/out_of_service/{room_id}",
        json={"is_out_of_service": False},
        headers=headers,
    )
    assert resp2.status_code == 200
    body2 = resp2.get_json()
    assert body2["room"]["is_out_of_service"] is False


def test_set_out_of_service_forbidden_for_non_facility(client):
    room_id = create_test_room()
    headers = make_auth_header(user_id=14, role="regular")

    resp = client.post(
        f"{API_VERSION}/rooms/out_of_service/{room_id}",
        json={"is_out_of_service": True},
        headers=headers,
    )
    assert resp.status_code == 403


# ─────────────────────────────────────────
# 9. OPS LOGS (ADMIN ONLY)
# ─────────────────────────────────────────

def test_ops_logs_admin_only(client):
    admin_headers = make_auth_header(user_id=15, role="admin")
    user_headers = make_auth_header(user_id=16, role="regular")

    # Admin should succeed
    resp_ok = client.get(f"{API_VERSION}/ops/logs", headers=admin_headers)
    assert resp_ok.status_code == 200
    data = resp_ok.get_json()
    assert "lines" in data
    assert isinstance(data["lines"], list)

    # Regular user should be forbidden
    resp_forbidden = client.get(f"{API_VERSION}/ops/logs", headers=user_headers)
    assert resp_forbidden.status_code == 403
