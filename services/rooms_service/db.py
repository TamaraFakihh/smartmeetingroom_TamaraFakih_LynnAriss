import psycopg2
from psycopg2.extras import RealDictCursor
from common.config import DATABASE_URL
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://smartroom:smartroom123@localhost:5432/smartroom")

def get_connection():
    """
    Create and return a new database connection.
    Uses DATABASE_URL from common.config.
    """
    return psycopg2.connect(DATABASE_URL)

def init_rooms_table():
    """
    Initialize the rooms table if it does not exist.
    This table stores information about meeting rooms.
    """
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS rooms (
        room_id SERIAL PRIMARY KEY,
        room_name TEXT NOT NULL UNIQUE,
        capacity INT NOT NULL CHECK (capacity > 0),
        location TEXT,
        is_available BOOLEAN DEFAULT TRUE,
        is_out_of_service BOOLEAN DEFAULT FALSE
    );

    CREATE INDEX IF NOT EXISTS idx_rooms_room_name ON rooms (room_name);
    CREATE INDEX IF NOT EXISTS idx_rooms_capacity ON rooms (capacity);
    CREATE INDEX IF NOT EXISTS idx_rooms_location ON rooms (location);
    CREATE INDEX IF NOT EXISTS idx_rooms_availability ON rooms (is_available, is_out_of_service);
    """

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(create_table_sql)
    finally:
        conn.close()
        
def init_equipment_table():
    """
    Initialize the equipment table if it does not exist.
    This table stores different types of equipment that can be associated with rooms.
    """
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS equipment (
        equipment_id SERIAL PRIMARY KEY,
        equipment_name TEXT NOT NULL UNIQUE
    );
    """

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(create_table_sql)
    finally:
        conn.close()

def init_room_equipment_table():
    """
    Initialize the room_equipment association table if it does not exist.
    This table links rooms with their available equipment.
    """

    create_table_sql = """
    CREATE TABLE IF NOT EXISTS room_equipment (
        room_id INT NOT NULL,
        equipment_id INT NOT NULL,
        quantity INT NOT NULL CHECK (quantity > 0),
        PRIMARY KEY (room_id, equipment_id),
        FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE,
        FOREIGN KEY (equipment_id) REFERENCES equipment(equipment_id) ON DELETE CASCADE
    );
    """

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(create_table_sql)
    finally:
        conn.close()

def fetch_equipment_for_room(room_id):
    """
    Return the equipment rows (equipment_id, equipment_name, quantity) for the given room.
    """
    fetch_equipment_for_room_sql = """
        SELECT e.equipment_id,
               e.equipment_name,
               re.quantity
          FROM equipment e
          JOIN room_equipment re ON e.equipment_id = re.equipment_id
         WHERE re.room_id = %s;
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(fetch_equipment_for_room_sql, (room_id,))
                return cur.fetchall()
    finally:
        conn.close()

def fetch_room(room_id):
    """
    Fetch a single room by its ID.
    Returns a dictionary representing the room, or None if not found.
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM rooms WHERE room_id = %s;", (room_id,))
                room = cur.fetchone()
                return room
    finally:
        conn.close()

def fetch_all_rooms():
    """
    Fetch all rooms from the database.
    Returns a list of dictionaries representing rooms.
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM rooms;")
                rooms = cur.fetchall()
                return rooms
    finally:
        conn.close()

def create_room(room_name, capacity, location):
    """
    Create a new room in the database.
    Returns the created room as a dictionary.
    """
    insert_sql = """
    INSERT INTO rooms (ROOM_NAME, capacity, location)
    VALUES (%s, %s, %s)
    RETURNING *;
    """

    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(insert_sql, (room_name, capacity, location))
                room = cur.fetchone()
                return room
    finally:
        conn.close()

def get_create_equipment(equipment_name):
    """
    Get an equipment by name, or create it if it does not exist.
    Returns the equipment as a dictionary.
    """
    select_sql = "SELECT * FROM equipment WHERE equipment_name = %s;"
    insert_equipment_sql = """
    INSERT INTO equipment (equipment_name)
    VALUES (%s)
    RETURNING *;
    """

    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(select_sql, (equipment_name,))
                equipment = cur.fetchone()
                if equipment:
                    return equipment
                cur.execute(insert_equipment_sql, (equipment_name,))
                equipment = cur.fetchone()
                return equipment
    finally:
        conn.close()


def set_room_equipment(room_id, equipments):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                for entry in equipments:
                    name = entry["name"].strip()
                    quantity = entry["quantity"]

                    cur.execute("SELECT equipment_id FROM equipment WHERE equipment_name = %s;", (name,))
                    row = cur.fetchone()
                    if row:
                        equipment_id = row["equipment_id"]
                    else:
                        cur.execute(
                            "INSERT INTO equipment (equipment_name) VALUES (%s) RETURNING equipment_id;",
                            (name,)
                        )
                        equipment_id = cur.fetchone()["equipment_id"]

                    cur.execute(
                        """
                        INSERT INTO room_equipment (room_id, equipment_id, quantity)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (room_id, equipment_id)
                        DO UPDATE SET quantity = EXCLUDED.quantity;
                        """,
                        (room_id, equipment_id, quantity),
                    )
    finally:
        conn.close()

def update_room(current_name, new_name=None , capacity=None, location=None):
    """
    Update the specified fields of a room identified by its name.
    Only updates fields that are provided (not None).
    Returns the updated room as a dictionary, or None if not found.
    """
    fields = []
    values = []

    if new_name is not None:
        fields.append("room_name = %s")
        values.append(new_name)

    if capacity is not None:
        fields.append("capacity = %s")
        values.append(capacity)

    if location is not None:
        fields.append("location = %s")
        values.append(location)

    if not fields:
        return None 
    
    values.append(current_name)
    Update_room_query = """ UPDATE rooms SET {} WHERE room_name = %s RETURNING *;
      """.format(", ".join(fields))
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(Update_room_query, tuple(values))
                updated_room = cur.fetchone()
                return updated_room
    finally:
        conn.close()

def delete_room(room_id):
    """
    Delete a room by its ID.
    Returns the number of deleted rows (0 or 1).
    """
    delete_room_sql = "DELETE FROM rooms WHERE room_id = %s;"

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(delete_room_sql, (room_id,))
                return cur.rowcount
    finally:
        conn.close()

def fetch_available_rooms(min_capacity=None, location=None, required_equipment=None):
    required_equipment = required_equipment or []
    eq_names = [e.strip().lower() for e in required_equipment if isinstance(e, str) and e.strip()]

    params = []
    where = []
    sql = """
        SELECT r.room_id, r.room_name, r.capacity, r.location
          FROM rooms r
    """

    if eq_names:
        placeholders = ", ".join(["%s"] * len(eq_names))
        sql += f"""
        JOIN (
            SELECT re.room_id
              FROM room_equipment re
              JOIN equipment e ON e.equipment_id = re.equipment_id
             WHERE LOWER(e.equipment_name) IN ({placeholders})
          GROUP BY re.room_id
            HAVING COUNT(DISTINCT LOWER(e.equipment_name)) = {len(eq_names)}
        ) rq ON rq.room_id = r.room_id
        """
        params.extend(eq_names)  # equipment params first

    if min_capacity is not None:
        where.append("r.capacity >= %s")
        params.append(min_capacity)

    if location is not None:
        where.append("r.location = %s")
        params.append(location)

    if where:
        sql += " WHERE " + " AND ".join(where)

    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, tuple(params))
                return cur.fetchall()
    finally:
        conn.close()

def fetch_bookings_for_room(room_id):
    """
    Fetch all bookings for a given room from the bookings table.
    Returns a list of booking dictionaries ordered by start_time.
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM bookings WHERE room_id = %s ORDER BY start_time;",
                    (room_id,)
                )
                return cur.fetchall()
    finally:
        conn.close()

def update_room_availability(room_id, is_available):
    """
    Update the availability of a room.
    """
    update_sql = """
    UPDATE rooms
    SET is_available = %s
    WHERE room_id = %s
    RETURNING room_id, is_available;
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(update_sql, (is_available, room_id))
                return cur.fetchone()
    finally:
        conn.close()

def set_unset_out_of_service(room_id, is_out_of_service):
    """
    Mark or unmark a room as out of service.
    """
    update_sql = """
    UPDATE rooms
    SET is_out_of_service = %s
    WHERE room_id = %s
    RETURNING room_id, room_name, capacity, location, is_out_of_service;
    """
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(update_sql, (is_out_of_service, room_id))
                return cur.fetchone()
    finally:
        conn.close()


def fetch_user_contact(user_id):
    """
    Return the first name, last name, and email for a user.
    """
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
