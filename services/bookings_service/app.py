import logging
import sys
import time
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, g

from services.bookings_service.db import (
    init_bookings_table,
    fetch_booking,
    fetch_all_bookings,
    fetch_bookings_for_user,
    fetch_user_contact,
    fetch_room_details,
    create_booking,
    update_booking_times,
    delete_booking,
    room_exists,
    has_conflict,
)
from services.bookings_service.models import Booking
from common.exeptions import *
from common.RBAC import (
    require_auth,
    is_human_user,
    is_admin,
    is_admin_or_facility,
    is_auditor,
)
from common.config import API_VERSION
from common.email_service import send_templated_email, EmailConfigurationError

app = Flask(__name__)

# ─────────────────────────────────────────
# Logging configuration (stdout for Docker)
# ─────────────────────────────────────────
logger = logging.getLogger("bookings_service")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)
logger.propagate = False
app.logger = logger

@app.errorhandler(SmartRoomExceptions)
def handle_smart_room_exception(e):
    return jsonify(e.to_dict()), e.status_code

@app.before_request
def start_audit_logging():
    g.request_id = str(uuid.uuid4())
    g.start_time = time.time()
    app.logger.info(
        "REQUEST",
        extra={
            "request_id": g.request_id,
            "method": request.method,
            "path": request.path,
            "remote_addr": request.remote_addr,
            "user_agent": request.user_agent.string,
        },
    )

@app.after_request
def end_audit_logging(response):
    duration = time.time() - g.get("start_time", time.time())
    app.logger.info(
        "RESPONSE",
        extra={
            "request_id": g.get("request_id"),
            "status_code": response.status_code,
            "path": request.path,
            "duration_ms": int(duration * 1000),
        },
    )
    response.headers["X-Request-ID"] = g.get("request_id", "")
    return response

# Initialize DB tables once at startup
init_bookings_table()

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

@app.route(f"{API_VERSION}/bookings", methods=["POST"])
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
        raise SmartRoomExceptions(status_code=403, details="Service accounts cannot create bookings.", error="Forbidden")

    user_id = int(payload["sub"])

    data = request.get_json() or {}
    room_id = data.get("room_id")
    start_time_str = data.get("start_time")
    end_time_str = data.get("end_time")

    if room_id is None or start_time_str is None or end_time_str is None:
        raise SmartRoomExceptions(status_code=400, details="room_id, start_time, and end_time are required.", error="Bad Request")

    if not isinstance(room_id, int) or room_id <= 0:
        raise SmartRoomExceptions(status_code=400, details="room_id must be a positive integer.", error="Bad Request")

    # Parse datetimes
    try:
        start_time = parse_iso_datetime(start_time_str)
        end_time = parse_iso_datetime(end_time_str)
    except ValueError as e:
        raise SmartRoomExceptions(400, "Bad Request", str(e))

    # Logical check
    if end_time <= start_time:
        raise SmartRoomExceptions(400, "Bad Request", "end_time must be strictly after start_time." )

    # Enforce future-only bookings
    if not ensure_future_start(start_time):
        raise SmartRoomExceptions(400, "Bad Request", "Bookings must start in the future.")
    # Check that room exists
    if not room_exists(room_id):
        raise SmartRoomExceptions(404, "Not Found", "Room does not exist.")

    # Check for conflicts
    if has_conflict(room_id, start_time, end_time):
        raise SmartRoomExceptions(409, "Conflict", "Room is already booked for the given time range.")
    row = create_booking(user_id, room_id, start_time, end_time)
    booking = Booking(
        id=row["booking_id"],
        user_id=row["user_id"],
        room_id=row["room_id"],
        start_time=row["start_time"],
        end_time=row["end_time"],
        created_at=row["created_at"],
    )

    user_contact = fetch_user_contact(user_id)
    if not user_contact:
        app.logger.warning(
            "Booking %s created but user %s contact details missing; skipping email.",
            booking.id,
            user_id,
        )
    else:
        room_details = fetch_room_details(room_id) or {}
        user_email = user_contact.get("email")
        if not user_email:
            app.logger.warning(
                "Booking %s created but email missing for user %s; skipping email.",
                booking.id,
                user_id,
            )
        else:
            start_display = booking.start_time.strftime("%A, %B %d, %Y at %I:%M %p")
            end_display = booking.end_time.strftime("%A, %B %d, %Y at %I:%M %p")

            context = {
                "first_name": user_contact.get("first_name", ""),
                "last_name": user_contact.get("last_name", ""),
                "email": user_email,
                "room_name": room_details.get("name") or f"Room {room_id}",
                "room_location": room_details.get("location") or "",
                "start_time": start_display,
                "end_time": end_display,
                "booking_id": str(booking.id),
            }

            try:
                status_code, message_id = send_templated_email(
                    to_email=user_email,
                    subject="Your Smart Meeting Rooms booking is confirmed",
                    template_name="BookingConfirmation.html",
                    context=context,
                )
                if status_code != 202:
                    app.logger.warning(
                        "Booking email returned status %s for booking %s",
                        status_code,
                        booking.id,
                    )
                else:
                    app.logger.info(
                        "Booking email sent for booking %s (message_id=%s)",
                        booking.id,
                        message_id,
                    )
            except EmailConfigurationError as cfg_err:
                app.logger.warning(
                    "Booking email skipped due to configuration issue: %s",
                    cfg_err,
                )
            except Exception as email_err:
                app.logger.exception(
                    "Failed to send booking email for booking %s: %s",
                    booking.id,
                    email_err,
                )

    return jsonify({"booking": booking.to_dict()}), 201


# ─────────────────────────────────────────────
# 2. GET CURRENT USER'S BOOKINGS (HISTORY)
# ─────────────────────────────────────────────

@app.route(f"{API_VERSION}/bookings/me", methods=["GET"])
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

@app.route(f"{API_VERSION}/bookings", methods=["GET"])
def get_all_bookings_endpoint():
    """
    Get all bookings in the system.
    Accessible by admin, facility manager, and auditor.
    """
    payload, error = require_auth()
    if error:
        return error

    if not (is_admin_or_facility(payload) or is_auditor(payload)):
        raise SmartRoomExceptions(403, "Forbidden", "Admin, facility manager or auditor only.")

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

@app.route(f"{API_VERSION}/bookings/<int:booking_id>", methods=["PUT"])
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
        raise SmartRoomExceptions(404, "Not Found", "Booking not found.")

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
            raise SmartRoomExceptions(400, "Bad Request", "room_id must be a positive integer.")

    # Parse datetimes if provided
    new_start_time = None
    new_end_time = None

    if start_time_str is not None:
        try:
            new_start_time = parse_iso_datetime(start_time_str)
        except ValueError as e:
            raise SmartRoomExceptions(400, "Bad Request", str(e))

    if end_time_str is not None:
        try:
            new_end_time = parse_iso_datetime(end_time_str)
        except ValueError as e:
            raise SmartRoomExceptions(400, "Bad Request", str(e))

    # Determine final times for conflict/future checks
    final_start = new_start_time or row["start_time"]
    final_end = new_end_time or row["end_time"]

    if final_end <= final_start:
        raise SmartRoomExceptions(400, "Bad Request", "end_time must be strictly after start_time.")

    if not ensure_future_start(final_start):
        raise SmartRoomExceptions(400, "Bad Request", "Updated booking must start in the future.")

    # Determine final room_id
    final_room_id = new_room_id if new_room_id is not None else row["room_id"]

    # Ensure room exists if changed
    if new_room_id is not None and not room_exists(final_room_id):
        raise SmartRoomExceptions(404, "Not Found", "Room does not exist.")

    # Check conflicts (excluding this booking itself)
    if has_conflict(final_room_id, final_start, final_end, exclude_booking_id=booking_id):
        raise SmartRoomExceptions(409, "Conflict", "Room is already booked for the given time range.")
    # Perform update
    updated_row = update_booking_times(
        booking_id,
        room_id=final_room_id if new_room_id is not None else None,
        start_time=new_start_time,
        end_time=new_end_time,
    )
    if not updated_row:
        raise SmartRoomExceptions(404, "Not Found", "Booking not found or nothing to update.")

    booking = Booking(
        id=updated_row["booking_id"],
        user_id=updated_row["user_id"],
        room_id=updated_row["room_id"],
        start_time=updated_row["start_time"],
        end_time=updated_row["end_time"],
        created_at=updated_row["created_at"],
    )

    user_contact = fetch_user_contact(booking.user_id)
    if not user_contact:
        app.logger.warning(
            "Booking %s updated but user %s contact details missing; skipping email.",
            booking.id,
            booking.user_id,
        )
    else:
        user_email = user_contact.get("email")
        if not user_email:
            app.logger.warning(
                "Booking %s updated but email missing for user %s; skipping email.",
                booking.id,
                booking.user_id,
            )
        else:
            room_details = fetch_room_details(booking.room_id) or {}
            start_display = booking.start_time.strftime("%A, %B %d, %Y at %I:%M %p")
            end_display = booking.end_time.strftime("%A, %B %d, %Y at %I:%M %p")

            updated_by = "you"
            if current_user_id != booking.user_id:
                updated_by = payload.get("role", "an administrator")

            context = {
                "first_name": user_contact.get("first_name", ""),
                "last_name": user_contact.get("last_name", ""),
                "email": user_email,
                "room_name": room_details.get("name") or f"Room {booking.room_id}",
                "room_location": room_details.get("location") or "",
                "start_time": start_display,
                "end_time": end_display,
                "booking_id": str(booking.id),
                "updated_by": updated_by,
            }

            try:
                status_code, message_id = send_templated_email(
                    to_email=user_email,
                    subject="Your Smart Meeting Rooms booking was updated",
                    template_name="BookingUpdated.html",
                    context=context,
                )
                if status_code != 202:
                    app.logger.warning(
                        "Booking update email returned status %s for booking %s",
                        status_code,
                        booking.id,
                    )
                else:
                    app.logger.info(
                        "Booking update email sent for booking %s (message_id=%s)",
                        booking.id,
                        message_id,
                    )
            except EmailConfigurationError as cfg_err:
                app.logger.warning(
                    "Booking update email skipped due to configuration issue: %s",
                    cfg_err,
                )
            except Exception as email_err:
                app.logger.exception(
                    "Failed to send booking update email for booking %s: %s",
                    booking.id,
                    email_err,
                )

    return jsonify({"booking": booking.to_dict()}), 200


# ─────────────────────────────────────────────
# 5. DELETE (CANCEL) BOOKING
# ─────────────────────────────────────────────

@app.route(f"{API_VERSION}/bookings/<int:booking_id>", methods=["DELETE"])
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
        raise SmartRoomExceptions(404, "Not Found", "Booking not found.")

    # Permission check:
    # - admin can cancel any booking
    # - non-admin can only cancel their own booking
    if not is_admin(payload) and row["user_id"] != current_user_id:
        raise SmartRoomExceptions(403, "Forbidden", "You do not have permission to cancel this booking.")

    deleted = delete_booking(booking_id)
    if deleted == 0:
        raise SmartRoomExceptions(404, "Not Found", "Booking not found.")

    user_contact = fetch_user_contact(row["user_id"])
    if not user_contact:
        app.logger.warning(
            "Booking %s cancelled but user %s contact details missing; skipping email.",
            booking_id,
            row["user_id"],
        )
    else:
        user_email = user_contact.get("email")
        if not user_email:
            app.logger.warning(
                "Booking %s cancelled but email missing for user %s; skipping email.",
                booking_id,
                row["user_id"],
            )
        else:
            room_details = fetch_room_details(row["room_id"]) or {}
            start_display = row["start_time"].strftime("%A, %B %d, %Y at %I:%M %p")
            end_display = row["end_time"].strftime("%A, %B %d, %Y at %I:%M %p")

            context = {
                "first_name": user_contact.get("first_name", ""),
                "last_name": user_contact.get("last_name", ""),
                "email": user_email,
                "room_name": room_details.get("name") or f"Room {row['room_id']}",
                "room_location": room_details.get("location") or "",
                "start_time": start_display,
                "end_time": end_display,
                "booking_id": str(row["booking_id"]),
            }

            try:
                status_code, message_id = send_templated_email(
                    to_email=user_email,
                    subject="Your Smart Meeting Rooms booking was cancelled",
                    template_name="BookingCancelled.html",
                    context=context,
                )
                if status_code != 202:
                    app.logger.warning(
                        "Booking cancellation email returned status %s for booking %s",
                        status_code,
                        booking_id,
                    )
                else:
                    app.logger.info(
                        "Booking cancellation email sent for booking %s (message_id=%s)",
                        booking_id,
                        message_id,
                    )
            except EmailConfigurationError as cfg_err:
                app.logger.warning(
                    "Booking cancellation email skipped due to configuration issue: %s",
                    cfg_err,
                )
            except Exception as email_err:
                app.logger.exception(
                    "Failed to send booking cancellation email for booking %s: %s",
                    booking_id,
                    email_err,
                )

    return jsonify({"message": "Booking cancelled successfully."}), 200


# ─────────────────────────────────────────────
# 6. CHECK AVAILABILITY FOR A ROOM
# ─────────────────────────────────────────────

@app.route(f"{API_VERSION}/bookings/check", methods=["GET"])
def check_room_availability():
    """
    Check if a room is available in a given time range.

    Query params:
      room_id: int
      start_time: ISO datetime
      end_time: ISO datetime
    """
    
    room_id_str = request.args.get("room_id")
    start_time_str = request.args.get("start_time")
    end_time_str = request.args.get("end_time")

    if not room_id_str or not start_time_str or not end_time_str:
        raise SmartRoomExceptions(400, "Bad Request", "room_id, start_time, and end_time query params are required.")

    try:
        room_id = int(room_id_str)
    except ValueError:
        raise SmartRoomExceptions(400, "Bad Request", "room_id must be an integer.")

    try:
        start_time = parse_iso_datetime(start_time_str)
        end_time = parse_iso_datetime(end_time_str)
    except ValueError as e:
        raise SmartRoomExceptions(400, "Bad Request", str(e))

    if end_time <= start_time:
        raise SmartRoomExceptions(400, "Bad Request", "end_time must be strictly after start_time.")

    # For availability checks, you might allow past ranges (for analytics),
    # so we do NOT enforce future-only here.

    if not room_exists(room_id):
        raise SmartRoomExceptions(404, "Not Found", "Room does not exist.")

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
