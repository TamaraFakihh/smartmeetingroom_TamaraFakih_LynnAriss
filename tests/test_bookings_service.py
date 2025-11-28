import importlib
from pathlib import Path

import pytest


def load_bookings_app(monkeypatch):
    import services.bookings_service.db as bookings_db
    # Prevent table init on import
    monkeypatch.setattr(bookings_db, "init_bookings_table", lambda: None)
    bookings_app = importlib.reload(importlib.import_module("services.bookings_service.app"))
    return bookings_app, bookings_db


def test_admin_get_bookings_for_user(monkeypatch):
    bookings_app, bookings_db = load_bookings_app(monkeypatch)

    monkeypatch.setattr(bookings_app, "require_auth", lambda: ({"role": "admin"}, None))
    bookings_data = [
        {
            "booking_id": 10,
            "user_id": 1,
            "room_id": 5,
            "start_time": bookings_app.datetime(2025, 1, 1, 10, 0, 0),
            "end_time": bookings_app.datetime(2025, 1, 1, 11, 0, 0),
            "created_at": bookings_app.datetime(2024, 12, 31, 12, 0, 0),
            "user_first_name": "A",
            "user_last_name": "B",
            "username": "ab",
            "user_email": "a@b.com",
            "room_name": "Conf",
            "room_location": "HQ",
        }
    ]
    monkeypatch.setattr(bookings_db, "fetch_bookings_for_user_with_details", lambda user_id: bookings_data)
    monkeypatch.setattr(bookings_app, "fetch_bookings_for_user_with_details", lambda user_id: bookings_data)

    client = bookings_app.app.test_client()
    resp = client.get(f"{bookings_app.API_VERSION}/bookings/user/1")

    assert resp.status_code == 200
    data = resp.get_json()["bookings"][0]
    assert data["booking_id"] == 10
    assert data["user"]["email"] == "a@b.com"
    assert data["room"]["name"] == "Conf"


def test_ops_logs_admin(monkeypatch, tmp_path):
    bookings_app, _ = load_bookings_app(monkeypatch)
    log_file = Path(tmp_path) / "bookings.log"
    log_file.write_text("b1\nb2\nb3\n", encoding="utf-8")
    monkeypatch.setattr(bookings_app, "LOG_FILE_PATH", str(log_file))
    monkeypatch.setattr(bookings_app, "require_auth", lambda: ({"role": "admin"}, None))

    client = bookings_app.app.test_client()
    resp = client.get(f"{bookings_app.API_VERSION}/ops/logs?lines=2")

    assert resp.status_code == 200
    assert resp.get_json()["lines"] == ["b2\n", "b3\n"]


def test_create_booking_success(monkeypatch):
    bookings_app, bookings_db = load_bookings_app(monkeypatch)

    payload = {"role": "regular", "sub": "1"}
    monkeypatch.setattr(bookings_app, "require_auth", lambda: (payload, None))
    monkeypatch.setattr(bookings_app, "is_human_user", lambda p: True)
    monkeypatch.setattr(bookings_db, "room_exists", lambda room_id: True)
    monkeypatch.setattr(bookings_app, "room_exists", lambda room_id: True)
    monkeypatch.setattr(bookings_db, "has_conflict", lambda room_id, s, e, exclude_booking_id=None: False)
    monkeypatch.setattr(bookings_app, "has_conflict", lambda room_id, s, e, exclude_booking_id=None: False)
    fake_row = {
        "booking_id": 1,
        "user_id": 1,
        "room_id": 2,
        "start_time": bookings_app.datetime(2050, 1, 1, 10, 0, 0),
        "end_time": bookings_app.datetime(2050, 1, 1, 11, 0, 0),
        "created_at": bookings_app.datetime.utcnow(),
    }
    monkeypatch.setattr(bookings_db, "create_booking", lambda uid, rid, st, et: fake_row)
    monkeypatch.setattr(bookings_app, "create_booking", lambda uid, rid, st, et: fake_row)
    monkeypatch.setattr(bookings_db, "fetch_user_contact", lambda uid: {"email": "a@b.com", "first_name": "A", "last_name": "B"})
    monkeypatch.setattr(bookings_app, "fetch_user_contact", lambda uid: {"email": "a@b.com", "first_name": "A", "last_name": "B"})
    monkeypatch.setattr(bookings_db, "fetch_room_details", lambda rid: {"name": "Conf", "location": "HQ"})
    monkeypatch.setattr(bookings_app, "fetch_room_details", lambda rid: {"name": "Conf", "location": "HQ"})
    monkeypatch.setattr(bookings_app, "send_templated_email", lambda **kwargs: (202, "msg"))

    client = bookings_app.app.test_client()
    resp = client.post(
        f"{bookings_app.API_VERSION}/bookings",
        json={
            "room_id": 2,
            "start_time": "2050-01-01T10:00:00",
            "end_time": "2050-01-01T11:00:00",
        },
    )

    assert resp.status_code == 201
    assert resp.get_json()["booking"]["room_id"] == 2


def test_create_booking_conflict(monkeypatch):
    bookings_app, bookings_db = load_bookings_app(monkeypatch)
    payload = {"role": "regular", "sub": "1"}
    monkeypatch.setattr(bookings_app, "require_auth", lambda: (payload, None))
    monkeypatch.setattr(bookings_app, "is_human_user", lambda p: True)
    monkeypatch.setattr(bookings_db, "room_exists", lambda room_id: True)
    monkeypatch.setattr(bookings_app, "room_exists", lambda room_id: True)
    monkeypatch.setattr(bookings_db, "has_conflict", lambda room_id, s, e, exclude_booking_id=None: True)
    monkeypatch.setattr(bookings_app, "has_conflict", lambda room_id, s, e, exclude_booking_id=None: True)

    client = bookings_app.app.test_client()
    resp = client.post(
        f"{bookings_app.API_VERSION}/bookings",
        json={
            "room_id": 2,
            "start_time": "2050-01-01T10:00:00",
            "end_time": "2050-01-01T11:00:00",
        },
    )

    assert resp.status_code == 409


def test_update_booking_forbidden(monkeypatch):
    bookings_app, bookings_db = load_bookings_app(monkeypatch)

    payload = {"role": "regular", "sub": "1"}
    monkeypatch.setattr(bookings_app, "require_auth", lambda: (payload, None))
    booking_row = {"booking_id": 9, "user_id": 2, "room_id": 1, "start_time": bookings_app.datetime.utcnow(), "end_time": bookings_app.datetime.utcnow()}
    monkeypatch.setattr(bookings_db, "fetch_booking", lambda booking_id: booking_row)
    monkeypatch.setattr(bookings_app, "fetch_booking", lambda booking_id: booking_row)

    client = bookings_app.app.test_client()
    resp = client.put(f"{bookings_app.API_VERSION}/bookings/9", json={})
    assert resp.status_code == 403
