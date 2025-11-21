from datetime import datetime
from flask import Flask, request, jsonify

from services.bookings_service.db import (
    init_bookings_table,
    fetch_booking,
    fetch_all_bookings,
    fetch_bookings_for_user,
    create_booking,
    update_booking_times,
    delete_booking,
    room_exists,
    has_conflict,
)
from services.bookings_service.models import Booking
from common.security import decode_access_token


app = Flask(__name__)

# Initialize DB tables once at startup
init_bookings_table()


# ─────────────────────────────────────────────
# Auth & RBAC helpers (mirroring users_service style)
# ─────────────────────────────────────────────

def get_current_user_payload():
    """
    Helper to read Authorization header, decode JWT, and return token payload.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1]
    payload = decode_access_token(token)
    return payload


def require_auth():
    """
    Helper to enforce authentication.
    Returns (payload, error_response) where error_response is a Flask response or None.
    """
    payload = get_current_user_payload()
    if not payload:
        return None, (jsonify({"error": "Unauthorized."}), 401)
    return payload, None


def is_admin(payload: dict) -> bool:
    return payload.get("role") == "admin"


def is_facility_manager(payload: dict) -> bool:
    return payload.get("role") == "facility_manager"


def is_admin_or_facility(payload: dict) -> bool:
    return payload.get("role") in {"admin", "facility_manager"}


def is_auditor(payload: dict) -> bool:
    return payload.get("role") == "auditor"


def is_human_user(payload: dict) -> bool:
    """
    Exclude 'service_account' from normal interactive operations.
    """
    return payload.get("role") in {
        "regular",
        "admin",
        "facility_manager",
        "moderator",
        "auditor",
    }


# ─────────────────────────────────────────────
# Utility: datetime parsing & validation
# ─────────────────────────────────────────────

def parse_iso_datetime(value: str) -> datetime:
    """
    Parse an ISO 8601 datetime string to a datetime object.
    Raises ValueError if invalid.
    """
    try:
        return datetime.fromisoformat(value)
    except Exception:
        raise ValueError(
            "Invalid datetime format. Use ISO format, e.g. '2025-11-19T15:30:00'."
        )


def ensure_future_start(start_time: datetime) -> bool:
    """
    Ensure that the booking start_time is in the future.
    """
    if start_time.tzinfo is not None:
        now = datetime.now(tz=start_time.tzinfo)
    else:
        now = datetime.utcnow()
    return start_time > now


# ─────────────────────────────────────────────
# 1. CREATE BOOKING
# ─────────────────────────────────────────────

@app.route("/bookings", methods=["POST"])
def create_booking_endpoint():
    """
    Create a new booking for the authenticated user.

    JSON body:
    {
        "room_id": 1,
        "start_time": "2025-11-20T10:00:00",
        "end_time": "2025-11-20T11:00:00"
    }
    """
    payload, error = require_auth()
    if error:
        return error

    if not is_human_user(payload):
        return jsonify({"error": "Service accounts cannot create bookings."}), 403

    user_id = int(payload["sub"])

    data = request.get_json() or {}
    room_id = data.get("room_id")
    start_time_str = data.get("start_time")
    end_time_str = data.get("end_time")

    if room_id is None or start_time_str is None or end_time_str is None:
        return jsonify({"error": "room_id, start_time, and end_time are required."}), 400

    if not isinstance(room_id, int) or room_id <= 0:
        return jsonify({"error": "room_id must be a positive integer."}), 400

    # Parse datetimes
    try:
        start_time = parse_iso_datetime(start_time_str)
        end_time = parse_iso_datetime(end_time_str)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # Logical check
    if end_time <= start_time:
        return jsonify({"error": "end_time must be strictly after start_time."}), 400

    # Enforce future-only bookings
    if not ensure_future_start(start_time):
        return jsonify({"error": "Bookings must start in the future."}), 400

    # Check that room exists
    if not room_exists(room_id):
        return jsonify({"error": "Room does not exist."}), 404

    # Check for conflicts
    if has_conflict(room_id, start_time, end_time):
        return jsonify({"error": "Room is already booked for the given time range."}), 409

    row = create_booking(user_id, room_id, start_time, end_time)
    booking = Booking(
        id=row["booking_id"],
        user_id=row["user_id"],
        room_id=row["room_id"],
        start_time=row["start_time"],
        end_time=row["end_time"],
        created_at=row["created_at"],
    )

    return jsonify({"booking": booking.to_dict()}), 201


# ─────────────────────────────────────────────
# 2. GET CURRENT USER'S BOOKINGS (HISTORY)
# ─────────────────────────────────────────────

@app.route("/bookings/me", methods=["GET"])
def get_my_bookings():
    """
    Get all bookings for the currently authenticated user.
    """
    payload, error = require_auth()
    if error:
        return error

    user_id = int(payload["sub"])
    rows = fetch_bookings_for_user(user_id)

    bookings = [
        Booking(
            id=row["booking_id"],
            user_id=row["user_id"],
            room_id=row["room_id"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            created_at=row["created_at"],
        ).to_dict()
        for row in rows
    ]

    return jsonify({"bookings": bookings}), 200


# ─────────────────────────────────────────────
# 3. ADMIN/FACILITY/AUDITOR: GET ALL BOOKINGS
# ─────────────────────────────────────────────

@app.route("/bookings", methods=["GET"])
def get_all_bookings_endpoint():
    """
    Get all bookings in the system.
    Accessible by admin, facility manager, and auditor.
    """
    payload, error = require_auth()
    if error:
        return error

    if not (is_admin_or_facility(payload) or is_auditor(payload)):
        return jsonify({"error": "Forbidden. Admin, facility manager or auditor only."}), 403

    rows = fetch_all_bookings()

    bookings = [
        Booking(
            id=row["booking_id"],
            user_id=row["user_id"],
            room_id=row["room_id"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            created_at=row["created_at"],
        ).to_dict()
        for row in rows
    ]

    return jsonify({"bookings": bookings}), 200


# ─────────────────────────────────────────────
# 4. UPDATE BOOKING (RESCHEDULE / CHANGE ROOM)
# ─────────────────────────────────────────────

@app.route("/bookings/<int:booking_id>", methods=["PUT"])
def update_booking_endpoint(booking_id: int):
    """
    Update an existing booking (room and/or time).

    Only the owner of the booking or an admin can do this.

    JSON body (any subset):
    {
        "room_id": 2,
        "start_time": "2025-11-20T12:00:00",
        "end_time": "2025-11-20T13:00:00"
    }
    """
    payload, error = require_auth()
    if error:
        return error

    current_user_id = int(payload["sub"])

    row = fetch_booking(booking_id)
    if not row:
        return jsonify({"error": "Booking not found."}), 404

    # Permission check:
    # - admin can update any booking
    # - non-admin can only update their own booking
    if not is_admin(payload) and row["user_id"] != current_user_id:
        return jsonify({"error": "Forbidden."}), 403

    data = request.get_json() or {}
    new_room_id = data.get("room_id")
    start_time_str = data.get("start_time")
    end_time_str = data.get("end_time")

    if new_room_id is not None:
        if not isinstance(new_room_id, int) or new_room_id <= 0:
            return jsonify({"error": "room_id must be a positive integer."}), 400

    # Parse datetimes if provided
    new_start_time = None
    new_end_time = None

    if start_time_str is not None:
        try:
            new_start_time = parse_iso_datetime(start_time_str)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    if end_time_str is not None:
        try:
            new_end_time = parse_iso_datetime(end_time_str)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    # Determine final times for conflict/future checks
    final_start = new_start_time or row["start_time"]
    final_end = new_end_time or row["end_time"]

    if final_end <= final_start:
        return jsonify({"error": "end_time must be strictly after start_time."}), 400

    if not ensure_future_start(final_start):
        return jsonify({"error": "Updated booking must start in the future."}), 400

    # Determine final room_id
    final_room_id = new_room_id if new_room_id is not None else row["room_id"]

    # Ensure room exists if changed
    if new_room_id is not None and not room_exists(final_room_id):
        return jsonify({"error": "Room does not exist."}), 404

    # Check conflicts (excluding this booking itself)
    if has_conflict(final_room_id, final_start, final_end, exclude_booking_id=booking_id):
        return jsonify({"error": "Room is already booked for the given time range."}), 409

    # Perform update
    updated_row = update_booking_times(
        booking_id,
        room_id=final_room_id if new_room_id is not None else None,
        start_time=new_start_time,
        end_time=new_end_time,
    )
    if not updated_row:
        return jsonify({"error": "Booking not found or nothing to update."}), 404

    booking = Booking(
        id=updated_row["booking_id"],
        user_id=updated_row["user_id"],
        room_id=updated_row["room_id"],
        start_time=updated_row["start_time"],
        end_time=updated_row["end_time"],
        created_at=updated_row["created_at"],
    )

    return jsonify({"booking": booking.to_dict()}), 200


# ─────────────────────────────────────────────
# 5. DELETE (CANCEL) BOOKING
# ─────────────────────────────────────────────

@app.route("/bookings/<int:booking_id>", methods=["DELETE"])
def delete_booking_endpoint(booking_id: int):
    """
    Delete (cancel) a booking.

    Only the owner or an admin can cancel.
    """
    payload, error = require_auth()
    if error:
        return error

    current_user_id = int(payload["sub"])

    row = fetch_booking(booking_id)
    if not row:
        return jsonify({"error": "Booking not found."}), 404

    # Permission check:
    # - admin can cancel any booking
    # - non-admin can only cancel their own booking
    if not is_admin(payload) and row["user_id"] != current_user_id:
        return jsonify({"error": "Forbidden."}), 403

    deleted = delete_booking(booking_id)
    if deleted == 0:
        return jsonify({"error": "Booking not found."}), 404

    return jsonify({"message": "Booking cancelled successfully."}), 200


# ─────────────────────────────────────────────
# 6. CHECK AVAILABILITY FOR A ROOM
# ─────────────────────────────────────────────

@app.route("/bookings/check", methods=["GET"])
def check_room_availability():
    """
    Check if a room is available in a given time range.

    Query params:
      room_id: int
      start_time: ISO datetime
      end_time: ISO datetime

    Example:
      /bookings/check?room_id=1&start_time=2025-11-20T10:00:00&end_time=2025-11-20T11:00:00
    """
    room_id_str = request.args.get("room_id")
    start_time_str = request.args.get("start_time")
    end_time_str = request.args.get("end_time")

    if not room_id_str or not start_time_str or not end_time_str:
        return jsonify({"error": "room_id, start_time, and end_time query params are required."}), 400

    try:
        room_id = int(room_id_str)
    except ValueError:
        return jsonify({"error": "room_id must be an integer."}), 400

    try:
        start_time = parse_iso_datetime(start_time_str)
        end_time = parse_iso_datetime(end_time_str)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if end_time <= start_time:
        return jsonify({"error": "end_time must be strictly after start_time."}), 400

    # For availability checks, you might allow past ranges (for analytics),
    # so we do NOT enforce future-only here.

    if not room_exists(room_id):
        return jsonify({"error": "Room does not exist."}), 404

    conflict = has_conflict(room_id, start_time, end_time)
    return jsonify({
        "room_id": room_id,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "available": not conflict
    }), 200


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # For development only; later via gunicorn/Docker
    app.run(host="0.0.0.0", port=5003, debug=True)
