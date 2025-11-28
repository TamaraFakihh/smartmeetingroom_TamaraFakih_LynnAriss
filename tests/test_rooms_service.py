import importlib
from pathlib import Path

import pytest


def load_rooms_app(monkeypatch):
    import services.rooms_service.db as rooms_db
    # Prevent real DB/table creation on import
    monkeypatch.setattr(rooms_db, "init_rooms_table", lambda: None)
    monkeypatch.setattr(rooms_db, "init_equipment_table", lambda: None)
    monkeypatch.setattr(rooms_db, "init_room_equipment_table", lambda: None)
    rooms_app = importlib.reload(importlib.import_module("services.rooms_service.app"))
    return rooms_app, rooms_db


def test_room_status_allows_regular(monkeypatch):
    rooms_app, rooms_db = load_rooms_app(monkeypatch)

    monkeypatch.setattr(rooms_app, "require_auth", lambda: ({"role": "regular"}, None))
    monkeypatch.setattr(rooms_db, "fetch_room", lambda room_id: {"room_id": room_id, "room_name": "A"})
    monkeypatch.setattr(rooms_db, "fetch_bookings_for_room", lambda room_id: [])

    client = rooms_app.app.test_client()
    resp = client.get(f"{rooms_app.API_VERSION}/rooms/1/status")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["room_id"] == 1
    assert body["room_available"] is True


def test_toggle_availability_requires_admin(monkeypatch):
    rooms_app, rooms_db = load_rooms_app(monkeypatch)

    # Facility manager should be forbidden per current logic
    monkeypatch.setattr(rooms_app, "require_auth", lambda: ({"role": "facility_manager"}, None))
    monkeypatch.setattr(rooms_db, "fetch_room", lambda room_id: {"room_id": room_id, "is_available": True})
    monkeypatch.setattr(rooms_db, "update_room_availability", lambda room_id, avail: {"room_id": room_id, "is_available": avail})

    client = rooms_app.app.test_client()
    resp = client.patch(f"{rooms_app.API_VERSION}/rooms/1/toggle_availability")

    assert resp.status_code == 403


def test_ops_logs_admin(monkeypatch, tmp_path):
    rooms_app, _ = load_rooms_app(monkeypatch)
    log_file = Path(tmp_path) / "rooms.log"
    log_file.write_text("r1\nr2\n", encoding="utf-8")
    monkeypatch.setattr(rooms_app, "LOG_FILE_PATH", str(log_file))
    monkeypatch.setattr(rooms_app, "require_auth", lambda: ({"role": "admin"}, None))

    client = rooms_app.app.test_client()
    resp = client.get(f"{rooms_app.API_VERSION}/ops/logs?lines=1")

    assert resp.status_code == 200
    assert resp.get_json()["lines"] == ["r2\n"]


def test_add_room_success(monkeypatch):
    rooms_app, rooms_db = load_rooms_app(monkeypatch)
    monkeypatch.setattr(rooms_app, "require_auth", lambda: ({"role": "admin"}, None))
    monkeypatch.setattr(rooms_app, "is_admin_or_facility", lambda payload: True)
    monkeypatch.setattr(rooms_db, "create_room", lambda name, cap, loc: {"room_id": 1, "room_name": name, "capacity": cap, "location": loc})
    monkeypatch.setattr(rooms_app, "create_room", lambda name, cap, loc: {"room_id": 1, "room_name": name, "capacity": cap, "location": loc})
    monkeypatch.setattr(rooms_db, "set_room_equipment", lambda room_id, eq: None)
    monkeypatch.setattr(rooms_app, "set_room_equipment", lambda room_id, eq: None)
    monkeypatch.setattr(rooms_db, "fetch_equipment_for_room", lambda room_id: [])
    monkeypatch.setattr(rooms_app, "fetch_equipment_for_room", lambda room_id: [])
    client = rooms_app.app.test_client()
    resp = client.post(
        f"{rooms_app.API_VERSION}/rooms",
        json={"name": "Room A", "capacity": 4, "location": "HQ", "equipment": [{"name": "Screen", "quantity": 1}]},
    )
    assert resp.status_code == 201


def test_delete_room_success(monkeypatch):
    rooms_app, rooms_db = load_rooms_app(monkeypatch)
    monkeypatch.setattr(rooms_app, "require_auth", lambda: ({"role": "admin"}, None))
    monkeypatch.setattr(rooms_db, "delete_room", lambda room_id: 1)
    monkeypatch.setattr(rooms_app, "delete_room", lambda room_id: 1)
    client = rooms_app.app.test_client()
    resp = client.delete(f"{rooms_app.API_VERSION}/rooms/5")
    assert resp.status_code == 200
