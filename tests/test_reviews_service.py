# tests/test_reviews_service.py

import pytest

import services.reviews_service.app as reviews_app
from services.reviews_service.db import (
    init_reviews_table,
    init_reports_table,
    get_connection,
)
from services.users_service.db import init_users_table
from services.rooms_service.db import init_rooms_table, create_room
from common.config import API_VERSION

# --------------------------------------------------------------------------
# FIXTURES
# --------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def ensure_schema():
    """Create all tables across services exactly once."""
    init_users_table()
    init_rooms_table()
    init_reviews_table()
    init_reports_table()


@pytest.fixture(autouse=True)
def clean_tables():
    """Clean all related tables before each test."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM reports;")
                cur.execute("DELETE FROM reviews;")
    finally:
        conn.close()


@pytest.fixture
def client():
    """Flask test client."""
    app = reviews_app.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# --------------------------------------------------------------------------
# HELPERS
# --------------------------------------------------------------------------

def register_user(client, username, email, role="regular"):
    data = {
        "first_name": "X",
        "last_name": "Y",
        "username": username,
        "email": email,
        "password": "StrongPass123!",
        "role": role,
    }
    return client.post(f"{API_VERSION}/users/register", json=data)


def login(client, username):
    resp = client.post(
        f"{API_VERSION}/auth/login",
        json={"username": username, "password": "StrongPass123!"}
    )
    token = None
    if resp.status_code == 200:
        token = resp.get_json()["access_token"]
    return resp, token


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------
# SETUP ROOM FOR TESTS
# --------------------------------------------------------------------------

@pytest.fixture
def room_id():
    """Create one room in DB."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO rooms (name, capacity, location)
                    VALUES ('Room A', 10, 'Floor 1')
                    RETURNING room_id;
                """)
                return cur.fetchone()[0]
    finally:
        conn.close()


# --------------------------------------------------------------------------
# 1. SUBMIT REVIEW
# --------------------------------------------------------------------------

def test_submit_review_success(client, room_id):
    register_user(client, "alice", "alice@example.com")
    _, token = login(client, "alice")

    resp = client.post(
        f"{API_VERSION}/reviews",
        json={"room_id": room_id, "rating": 5, "comment": "Great!"},
        headers=auth(token),
    )

    assert resp.status_code == 201
    data = resp.get_json()
    assert data["review"]["rating"] == 5
    assert data["review"]["room_id"] == room_id


def test_submit_review_requires_regular(client, room_id):
    register_user(client, "bob", "bob@example.com", role="admin")
    _, token = login(client, "bob")

    resp = client.post(
        f"{API_VERSION}/reviews",
        json={"room_id": room_id, "rating": 4},
        headers=auth(token),
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------
# 2. UPDATE REVIEW
# --------------------------------------------------------------------------

def test_update_review_by_owner(client, room_id):
    register_user(client, "user1", "u1@example.com")
    _, token = login(client, "user1")

    # submit
    r = client.post(
        f"{API_VERSION}/reviews",
        json={"room_id": room_id, "rating": 3},
        headers=auth(token)
    )
    review_id = r.get_json()["review"]["review_id"]

    # update
    resp = client.put(
        f"{API_VERSION}/reviews/update/{review_id}",
        json={"rating": 5, "comment": "Updated"},
        headers=auth(token),
    )
    assert resp.status_code == 200
    assert resp.get_json()["review"]["rating"] == 5


def test_update_review_not_owner_forbidden(client, room_id):
    register_user(client, "owner", "o@example.com")
    _, owner_token = login(client, "owner")

    register_user(client, "stranger", "s@example.com")
    _, stranger_token = login(client, "stranger")

    r = client.post(
        f"{API_VERSION}/reviews",
        json={"room_id": room_id, "rating": 2},
        headers=auth(owner_token),
    )
    review_id = r.get_json()["review"]["review_id"]

    resp = client.put(
        f"{API_VERSION}/reviews/update/{review_id}",
        json={"rating": 4},
        headers=auth(stranger_token),
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------
# 3. DELETE REVIEW
# --------------------------------------------------------------------------

def test_admin_can_delete_review(client, room_id):
    register_user(client, "user2", "u2@example.com")
    _, user_token = login(client, "user2")

    # Make review
    r = client.post(
        f"{API_VERSION}/reviews",
        json={"room_id": room_id, "rating": 4},
        headers=auth(user_token),
    )
    review_id = r.get_json()["review"]["review_id"]

    register_user(client, "admin", "admin@example.com", role="admin")
    _, admin_token = login(client, "admin")

    resp = client.delete(
        f"{API_VERSION}/reviews/{review_id}",
        headers=auth(admin_token),
    )
    assert resp.status_code == 200


def test_regular_user_cannot_delete_review(client, room_id):
    register_user(client, "u3", "u3@example.com")
    _, token1 = login(client, "u3")

    register_user(client, "u4", "u4@example.com")
    _, token2 = login(client, "u4")

    # u3 creates review
    r = client.post(
        f"{API_VERSION}/reviews",
        json={"room_id": room_id, "rating": 4},
        headers=auth(token1)
    )
    review_id = r.get_json()["review"]["review_id"]

    # u4 tries to delete
    resp = client.delete(
        f"{API_VERSION}/reviews/{review_id}",
        headers=auth(token2)
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------
# 4. GET REVIEWS FOR ROOM
# --------------------------------------------------------------------------

def test_fetch_reviews_requires_read_or_admin(client, room_id):
    register_user(client, "reader", "read@example.com", role="auditor")
    _, t_reader = login(client, "reader")

    register_user(client, "user5", "u5@example.com")
    _, t5 = login(client, "user5")

    # user5 creates review
    client.post(
        f"{API_VERSION}/reviews",
        json={"room_id": room_id, "rating": 5},
        headers=auth(t5),
    )

    # reader can view
    resp = client.get(
        f"{API_VERSION}/reviews/{room_id}",
        headers=auth(t_reader),
    )
    assert resp.status_code == 200

    # regular user = forbidden if not read-only role
    resp2 = client.get(
        f"{API_VERSION}/reviews/{room_id}",
        headers=auth(t5),
    )
    assert resp2.status_code == 403


# --------------------------------------------------------------------------
# 5. REPORT REVIEW
# --------------------------------------------------------------------------

def test_report_review_success(client, room_id):
    register_user(client, "u6", "u6@example.com")
    _, t6 = login(client, "u6")

    r = client.post(
        f"{API_VERSION}/reviews",
        json={"room_id": room_id, "rating": 1},
        headers=auth(t6),
    )
    rv_id = r.get_json()["review"]["review_id"]

    resp = client.post(
        f"{API_VERSION}/reviews/report/{rv_id}",
        json={"reason": "Spam / Promotional Content"},
        headers=auth(t6),
    )
    assert resp.status_code == 201


# --------------------------------------------------------------------------
# 6. FLAG / UNFLAG (Admin / Moderator)
# --------------------------------------------------------------------------

def test_flag_review(client, room_id):
    register_user(client, "flagger", "flagger@example.com")
    _, t_user = login(client, "flagger")

    register_user(client, "mod", "mod@example.com", role="moderator")
    _, t_mod = login(client, "mod")

    r = client.post(
        f"{API_VERSION}/reviews",
        json={"room_id": room_id, "rating": 3},
        headers=auth(t_user),
    )
    review_id = r.get_json()["review"]["review_id"]

    resp = client.post(
        f"{API_VERSION}/reviews/flag/{review_id}",
        headers=auth(t_mod),
    )
    assert resp.status_code == 200


def test_unflag_review(client, room_id):
    register_user(client, "u7", "u7@example.com")
    _, t7 = login(client, "u7")

    register_user(client, "admin", "adm@example.com", role="admin")
    _, t_admin = login(client, "admin")

    r = client.post(
        f"{API_VERSION}/reviews",
        json={"room_id": room_id, "rating": 5},
        headers=auth(t7),
    )
    review_id = r.get_json()["review"]["review_id"]

    client.post(f"{API_VERSION}/reviews/flag/{review_id}", headers=auth(t_admin))

    resp = client.post(
        f"{API_VERSION}/reviews/unflag/{review_id}",
        headers=auth(t_admin),
    )
    assert resp.status_code == 200


# --------------------------------------------------------------------------
# 7. GET ALL REPORTS (Moderator)
# --------------------------------------------------------------------------

def test_get_all_reports_requires_moderator(client, room_id):
    register_user(client, "u8", "u8@example.com")
    _, t8 = login(client, "u8")

    register_user(client, "mod", "m2@example.com", role="moderator")
    _, t_mod = login(client, "mod")

    # Create review + report
    r = client.post(
        f"{API_VERSION}/reviews",
        json={"room_id": room_id, "rating": 2},
        headers=auth(t8),
    )
    rv = r.get_json()["review"]["review_id"]

    client.post(
        f"{API_VERSION}/reviews/report/{rv}",
        json={"reason": "Inaccurate Review"},
        headers=auth(t8),
    )

    # admin/mod can see
    resp = client.get(
        f"{API_VERSION}/reviews/reports",
        headers=auth(t_mod),
    )
    assert resp.status_code == 200
    assert len(resp.get_json()["reports"]) == 1


# --------------------------------------------------------------------------
# 8. HIDE / UNHIDE REVIEW
# --------------------------------------------------------------------------

def test_user_can_hide_own_review(client, room_id):
    register_user(client, "hider", "h@example.com")
    _, t = login(client, "hider")

    r = client.post(
        f"{API_VERSION}/reviews",
        json={"room_id": room_id, "rating": 4},
        headers=auth(t),
    )
    rid = r.get_json()["review"]["review_id"]

    resp = client.patch(
        f"{API_VERSION}/reviews/hide/{rid}",
        json={"is_hidden": True},
        headers=auth(t),
    )
    assert resp.status_code == 200


def test_regular_cannot_unhide_review(client, room_id):
    register_user(client, "u9", "u9@example.com")
    _, t = login(client, "u9")

    r = client.post(
        f"{API_VERSION}/reviews",
        json={"room_id": room_id, "rating": 2},
        headers=auth(t),
    )
    rid = r.get_json()["review"]["review_id"]

    # hide
    client.patch(
        f"{API_VERSION}/reviews/hide/{rid}",
        json={"is_hidden": True},
        headers=auth(t),
    )

    # try unhide
    resp = client.patch(
        f"{API_VERSION}/reviews/hide/{rid}",
        json={"is_hidden": False},
        headers=auth(t),
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------
# 9. OPS LOGS — ADMIN ONLY
# --------------------------------------------------------------------------

def test_ops_logs_admin_only(client):
    register_user(client, "ad", "ad@example.com", role="admin")
    _, t_admin = login(client, "ad")

    register_user(client, "usr", "usr@example.com")
    _, t_user = login(client, "usr")

    resp_ok = client.get(
        f"{API_VERSION}/ops/logs",
        headers=auth(t_admin)
    )
    assert resp_ok.status_code == 200

    resp_fail = client.get(
        f"{API_VERSION}/ops/logs",
        headers=auth(t_user)
    )
    assert resp_fail.status_code == 403
