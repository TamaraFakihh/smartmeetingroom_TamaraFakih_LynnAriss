import importlib
from pathlib import Path
from datetime import datetime

import pytest


def load_reviews_app(monkeypatch):
    import services.reviews_service.db as reviews_db
    # Prevent table init on import
    monkeypatch.setattr(reviews_db, "init_reviews_table", lambda: None)
    monkeypatch.setattr(reviews_db, "init_reports_table", lambda: None)
    reviews_app = importlib.reload(importlib.import_module("services.reviews_service.app"))
    return reviews_app, reviews_db


def test_regular_can_hide_own_review(monkeypatch):
    reviews_app, reviews_db = load_reviews_app(monkeypatch)

    # Review owner payload
    monkeypatch.setattr(reviews_app, "require_auth", lambda: ({"role": "regular", "sub": "1"}, None))
    monkeypatch.setattr(reviews_db, "fetch_review_by_id", lambda rid: {"review_id": rid, "user_id": 1})
    monkeypatch.setattr(reviews_app, "fetch_review_by_id", lambda rid: {"review_id": rid, "user_id": 1})

    hidden = {}
    monkeypatch.setattr(
        reviews_db,
        "hide_review",
        lambda rid, is_hidden: hidden.setdefault("result", {"review_id": rid, "is_hidden": is_hidden}),
    )
    monkeypatch.setattr(
        reviews_app,
        "hide_review",
        lambda rid, is_hidden: hidden.setdefault("result", {"review_id": rid, "is_hidden": is_hidden}),
    )

    client = reviews_app.app.test_client()
    resp = client.patch(f"{reviews_app.API_VERSION}/reviews/hide/2", json={"is_hidden": True})

    assert resp.status_code == 200
    assert hidden["result"]["is_hidden"] is True


def test_regular_cannot_unhide(monkeypatch):
    reviews_app, reviews_db = load_reviews_app(monkeypatch)

    monkeypatch.setattr(reviews_app, "require_auth", lambda: ({"role": "regular", "sub": "1"}, None))
    monkeypatch.setattr(reviews_db, "fetch_review_by_id", lambda rid: {"review_id": rid, "user_id": 1})
    monkeypatch.setattr(reviews_app, "fetch_review_by_id", lambda rid: {"review_id": rid, "user_id": 1})

    client = reviews_app.app.test_client()
    resp = client.patch(f"{reviews_app.API_VERSION}/reviews/hide/2", json={"is_hidden": False})

    assert resp.status_code == 403


def test_ops_logs_admin(monkeypatch, tmp_path):
    reviews_app, _ = load_reviews_app(monkeypatch)
    log_file = Path(tmp_path) / "reviews.log"
    log_file.write_text("v1\nv2\n", encoding="utf-8")
    monkeypatch.setattr(reviews_app, "LOG_FILE_PATH", str(log_file))
    monkeypatch.setattr(reviews_app, "require_auth", lambda: ({"role": "admin"}, None))

    client = reviews_app.app.test_client()
    resp = client.get(f"{reviews_app.API_VERSION}/ops/logs?lines=1")

    assert resp.status_code == 200
    assert resp.get_json()["lines"] == ["v2\n"]


def test_submit_review_success(monkeypatch):
    reviews_app, reviews_db = load_reviews_app(monkeypatch)
    monkeypatch.setattr(reviews_app, "require_auth", lambda: ({"role": "regular", "sub": "1"}, None))
    monkeypatch.setattr(
        reviews_db,
        "create_review",
        lambda room_id, user_id, rating, comment: {
            "review_id": 1,
            "room_id": room_id,
            "user_id": user_id,
            "rating": rating,
            "comment": comment,
            "created_at": datetime.utcnow(),
        },
    )
    monkeypatch.setattr(
        reviews_app,
        "create_review",
        lambda room_id, user_id, rating, comment: {
            "review_id": 1,
            "room_id": room_id,
            "user_id": user_id,
            "rating": rating,
            "comment": comment,
            "created_at": datetime.utcnow(),
        },
    )

    client = reviews_app.app.test_client()
    resp = client.post(
        f"{reviews_app.API_VERSION}/reviews",
        json={"room_id": 1, "rating": 5, "comment": "Great"},
    )
    assert resp.status_code == 201
    assert resp.get_json()["review"]["rating"] == 5


def test_flag_review_by_moderator(monkeypatch):
    reviews_app, reviews_db = load_reviews_app(monkeypatch)
    monkeypatch.setattr(reviews_app, "require_auth", lambda: ({"role": "moderator"}, None))
    monkeypatch.setattr(reviews_db, "fetch_review_by_id", lambda rid: {"review_id": rid})
    monkeypatch.setattr(reviews_app, "fetch_review_by_id", lambda rid: {"review_id": rid})
    monkeypatch.setattr(
        reviews_db,
        "flag_unflag_review",
        lambda rid, flag: {"review_id": rid, "is_flagged": flag},
    )
    monkeypatch.setattr(
        reviews_app,
        "flag_unflag_review",
        lambda rid, flag: {"review_id": rid, "is_flagged": flag},
    )
    client = reviews_app.app.test_client()
    resp = client.post(f"{reviews_app.API_VERSION}/reviews/flag/3")
    assert resp.status_code == 200
    assert resp.get_json()["review"]["is_flagged"] is True
