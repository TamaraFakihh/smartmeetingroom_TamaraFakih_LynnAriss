import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import Optional

from common.config import DATABASE_URL


def get_connection():
    """
    Create and return a new database connection.
    Uses DATABASE_URL from common.config.
    """
    return psycopg2.connect(DATABASE_URL)


def init_bookings_table():
    """
    Initialize the bookings table if it does not exist.
    Stores which user booked which room at what time.
    """
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS bookings (
        booking_id SERIAL PRIMARY KEY,
        user_id    INT NOT NULL
            REFERENCES users(id)
            ON DELETE CASCADE
            ON UPDATE CASCADE,
        room_id    INT NOT NULL
            REFERENCES rooms(room_id)
            ON DELETE CASCADE
            ON UPDATE CASCADE,
        start_time TIMESTAMP NOT NULL,
        end_time   TIMESTAMP NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        CONSTRAINT chk_booking_time
            CHECK (start_time < end_time)
    );

    CREATE INDEX IF NOT EXISTS idx_bookings_room_time
        ON bookings (room_id, start_time, end_time);

    CREATE INDEX IF NOT EXISTS idx_bookings_user_id
        ON bookings (user_id);

    CREATE INDEX IF NOT EXISTS idx_bookings_start_time
        ON bookings (start_time);
    """

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(create_table_sql)
    finally:
        conn.close()


def fetch_booking(booking_id: int) -> Optional[dict]:
    """
    Fetch a single booking by its ID.
    Returns a dict row or None if not found.
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM bookings WHERE booking_id = %s;", (booking_id,))
                return cur.fetchone()
    finally:
        conn.close()


def fetch_all_bookings() -> list[dict]:
    """
    Fetch all bookings in the system, ordered by start_time.
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT 
                        b.booking_id,
                        b.user_id,
                        b.room_id,
                        b.start_time,
                        b.end_time,
                        b.created_at,
                        u.first_name AS user_first_name,
                        u.last_name  AS user_last_name,
                        u.username   AS username,
                        u.email      AS user_email,
                        r.room_name  AS room_name,
                        r.location   AS room_location
                    FROM bookings b
                    LEFT JOIN users u ON u.id = b.user_id
                    LEFT JOIN rooms r ON r.room_id = b.room_id
                    ORDER BY b.start_time;
                    """
                )
                return cur.fetchall()
    finally:
        conn.close()


def fetch_bookings_for_user_with_details(user_id: int) -> list[dict]:
    """
    Fetch all bookings for a given user, including user and room details.
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT 
                        b.booking_id,
                        b.user_id,
                        b.room_id,
                        b.start_time,
                        b.end_time,
                        b.created_at,
                        u.first_name AS user_first_name,
                        u.last_name  AS user_last_name,
                        u.username   AS username,
                        u.email      AS user_email,
                        r.room_name  AS room_name,
                        r.location   AS room_location
                    FROM bookings b
                    LEFT JOIN users u ON u.id = b.user_id
                    LEFT JOIN rooms r ON r.room_id = b.room_id
                    WHERE b.user_id = %s
                    ORDER BY b.start_time;
                    """,
                    (user_id,),
                )
                return cur.fetchall()
    finally:
        conn.close()


def fetch_bookings_for_user(user_id: int) -> list[dict]:
    """
    Fetch all bookings for a given user, ordered by start_time.
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM bookings WHERE user_id = %s ORDER BY start_time;",
                    (user_id,),
                )
                return cur.fetchall()
    finally:
        conn.close()


def fetch_bookings_for_room(room_id: int) -> list[dict]:
    """
    Fetch all bookings for a given room, ordered by start_time.
    (Useful later for analytics or admin views.)
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                        SELECT room_name AS name, location
                        FROM rooms
                        WHERE room_id = %s;
                    """,
                    (room_id,),
                )
                return cur.fetchall()
    finally:
        conn.close()


def fetch_user_contact(user_id: int) -> Optional[dict]:
    """Return the first name, last name, and email for a user."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT first_name, last_name, email FROM users WHERE id = %s;",
                    (user_id,),
                )
                return cur.fetchone()
    finally:
        conn.close()


def fetch_room_details(room_id: int) -> Optional[dict]:
    """Return the room name and location to enrich notification emails."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT room_name AS name, location
                    FROM rooms
                    WHERE room_id = %s;
                    """,
                    (room_id,),
                )
                return cur.fetchone()
    finally:
        conn.close()


def create_booking(user_id: int, room_id: int, start_time: datetime, end_time: datetime) -> dict:
    """
    Insert a new booking and return the created row as a dict.
    """
    insert_sql = """
    INSERT INTO bookings (user_id, room_id, start_time, end_time)
    VALUES (%s, %s, %s, %s)
    RETURNING *;
    """

    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(insert_sql, (user_id, room_id, start_time, end_time))
                return cur.fetchone()
    finally:
        conn.close()


def update_booking_times(
    booking_id: int,
    room_id: Optional[int] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> Optional[dict]:
    """
    Update the room and/or time window for a booking.
    Only fields that are not None are updated.
    Returns the updated row or None if not found or no fields provided.
    """
    fields = []
    params = []

    if room_id is not None:
        fields.append("room_id = %s")
        params.append(room_id)

    if start_time is not None:
        fields.append("start_time = %s")
        params.append(start_time)

    if end_time is not None:
        fields.append("end_time = %s")
        params.append(end_time)

    if not fields:
        return None

    params.append(booking_id)
    update_sql = f"""
    UPDATE bookings
       SET {", ".join(fields)}
     WHERE booking_id = %s
     RETURNING *;
    """

    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(update_sql, tuple(params))
                return cur.fetchone()
    finally:
        conn.close()


def delete_booking(booking_id: int) -> int:
    """
    Delete a booking by its ID.
    Returns number of deleted rows (0 or 1).
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM bookings WHERE booking_id = %s;", (booking_id,))
                return cur.rowcount
    finally:
        conn.close()


def room_exists(room_id: int) -> bool:
    """
    Check if a room exists in the rooms table.
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM rooms WHERE room_id = %s;", (room_id,))
                return cur.fetchone() is not None
    finally:
        conn.close()


def has_conflict(
    room_id: int,
    start_time: datetime,
    end_time: datetime,
    exclude_booking_id: Optional[int] = None,
) -> bool:
    """
    Check whether there is any overlapping booking for the same room.

    Overlap condition:
      NOT (existing_end <= new_start OR existing_start >= new_end)

    If exclude_booking_id is given, that booking is ignored (used during updates).
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                if exclude_booking_id is None:
                    cur.execute(
                        """
                        SELECT 1
                          FROM bookings
                         WHERE room_id = %s
                           AND NOT (end_time <= %s OR start_time >= %s)
                         LIMIT 1;
                        """,
                        (room_id, start_time, end_time),
                    )
                else:
                    cur.execute(
                        """
                        SELECT 1
                          FROM bookings
                         WHERE room_id = %s
                           AND booking_id <> %s
                           AND NOT (end_time <= %s OR start_time >= %s)
                         LIMIT 1;
                        """,
                        (room_id, exclude_booking_id, start_time, end_time),
                    )
                return cur.fetchone() is not None
    finally:
        conn.close()
