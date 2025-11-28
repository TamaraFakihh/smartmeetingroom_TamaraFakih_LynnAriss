import importlib
from pathlib import Path

import pytest


def load_users_app(monkeypatch):
    import services.users_service.db as users_db
    # Prevent real DB/table creation on import
    monkeypatch.setattr(users_db, "init_users_table", lambda: None)
    users_app = importlib.reload(importlib.import_module("services.users_service.app"))
    return users_app, users_db


def test_password_reset_request(monkeypatch, tmp_path):
    users_app, users_db = load_users_app(monkeypatch)

    # Stub user lookup and token creation
    user_row = {"id": 1, "first_name": "A", "last_name": "B", "username": "ab", "email": "a@b.com"}
    monkeypatch.setattr(users_db, "fetch_one", lambda q, p: user_row)
    monkeypatch.setattr(users_app, "fetch_one", lambda q, p: user_row)
    created = {}

    def fake_create_reset_token(user_id, token_hash, expires_at):
        created.update({"user_id": user_id, "token_hash": token_hash, "expires_at": expires_at})
        return {}

    monkeypatch.setattr(users_db, "create_reset_token", fake_create_reset_token)
    monkeypatch.setattr(users_app, "create_reset_token", fake_create_reset_token)
    monkeypatch.setattr(users_app, "send_templated_email", lambda **kwargs: (202, "msg"))

    client = users_app.app.test_client()
    resp = client.post(f"{users_app.API_VERSION}/auth/password-reset/request", json={"email": "a@b.com"})

    assert resp.status_code == 200
    assert created["user_id"] == 1
    assert created["token_hash"]  # token hash should be generated


def test_ops_logs_admin(monkeypatch, tmp_path):
    users_app, _ = load_users_app(monkeypatch)

    # Prepare a temporary log file
    log_file = Path(tmp_path) / "users.log"
    log_file.write_text("line1\nline2\nline3\n", encoding="utf-8")
    monkeypatch.setattr(users_app, "LOG_FILE_PATH", str(log_file))

    # Admin payload
    monkeypatch.setattr(users_app, "require_auth", lambda: ({"role": "admin"}, None))

    client = users_app.app.test_client()
    resp = client.get(f"{users_app.API_VERSION}/ops/logs?lines=2")

    assert resp.status_code == 200
    assert resp.get_json()["lines"] == ["line2\n", "line3\n"]


def test_login_invalid_user(monkeypatch):
    users_app, users_db = load_users_app(monkeypatch)
    # No user found
    monkeypatch.setattr(users_db, "fetch_one", lambda q, p=None: None)
    client = users_app.app.test_client()
    resp = client.post(f"{users_app.API_VERSION}/auth/login", json={"username": "nope", "password": "bad"})
    assert resp.status_code == 401


def test_get_user_by_username_forbidden(monkeypatch):
    users_app, users_db = load_users_app(monkeypatch)
    # requester is user id 1, target user id 2
    monkeypatch.setattr(users_app, "require_auth", lambda: ({"role": "regular", "sub": "1"}, None))
    monkeypatch.setattr(
        users_db,
        "fetch_one",
        lambda q, p=None: {"id": 2, "first_name": "A", "last_name": "B", "username": "target", "email": "t@e", "role": "regular"},
    )
    monkeypatch.setattr(
        users_app,
        "fetch_one",
        lambda q, p=None: {"id": 2, "first_name": "A", "last_name": "B", "username": "target", "email": "t@e", "role": "regular"},
    )
    client = users_app.app.test_client()
    resp = client.get(f"{users_app.API_VERSION}/users/target")
    assert resp.status_code == 403
