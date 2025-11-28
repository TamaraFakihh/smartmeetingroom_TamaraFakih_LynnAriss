# profile_memory_bookings.py
from memory_profiler import profile
from datetime import datetime, timedelta

from services.bookings_service import app as bookings_app
from services.bookings_service.db import (
    get_connection,
    init_bookings_table,
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
from common.config import API_VERSION


def _reset_db():
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE bookings RESTART IDENTITY CASCADE;")
                cur.execute("TRUNCATE TABLE rooms RESTART IDENTITY CASCADE;")
                cur.execute("TRUNCATE TABLE users RESTART IDENTITY CASCADE;")
    finally:
        conn.close()


def _create_test_user():
    password_hash = hash_password("StrongPass123!")
    row = fetch_one(
        """
        INSERT INTO users (first_name, last_name, username, email, password_hash, role)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
        """,
        ("Mem", "Profiler", "mem_user", "mem@example.com", password_hash, "regular"),
    )
    return row["id"]


def _auth_headers_for(user_id: int, role: str = "regular") -> dict:
    # We can bypass full JWT and reuse the same fake shape as the tests do.
    from common.security import create_access_token

    token = create_access_token(user_id, role)
    return {"Authorization": f"Bearer {token}"}


@profile
def run_memory_scenario():
    """
    Simple scenario:
    - Reset DB
    - Init tables
    - Create user + room
    - Hit POST /bookings several times via Flask test client
    """
    init_rooms_table()
    init_users_table()
    init_bookings_table()
    _reset_db()

    user_id = _create_test_user()
    room = create_room("Mem Room", 5, "2nd floor")
    room_id = room["room_id"]

    bookings_app.app.config["TESTING"] = True
    client = bookings_app.app.test_client()

    headers = _auth_headers_for(user_id)

    base_start = datetime.utcnow() + timedelta(hours=1)

    # Create 10 bookings with different start times
    for i in range(10):
        start = base_start + timedelta(hours=i * 2)
        end = start + timedelta(hours=1)
        resp = client.post(
            f"{API_VERSION}/bookings",
            json={
                "room_id": room_id,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
            headers=headers,
        )
        # Ensure it succeeds so we profile realistic flow
        assert resp.status_code in (201, 409)


if __name__ == "__main__":
    run_memory_scenario()
