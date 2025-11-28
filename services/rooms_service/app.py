import logging
import sys
import time
import uuid
from flask import Flask, jsonify, request, g
from datetime import datetime, timedelta
from psycopg2.errors import UniqueViolation
from services.rooms_service.models import Room
from services.rooms_service.db import (init_rooms_table,
                                       init_equipment_table,
                                       init_room_equipment_table,
                                       fetch_equipment_for_room,
                                       fetch_room,
                                       fetch_all_rooms,
                                       create_room,
                                       set_room_equipment,
                                       update_room,
                                       delete_room,
                                       fetch_bookings_for_room,
                                       update_room_availability,
                                       set_unset_out_of_service,
                                       fetch_user_contact
                                       )
from common.RBAC import (
    require_auth,
    is_human_user,
    is_admin,
    is_admin_or_facility,
    read_only,
    is_moderator,
    is_facility
)
from common.exeptions import *
from common.config import API_VERSION
from common.email_service import send_templated_email, EmailConfigurationError

app = Flask(__name__)

# ─────────────────────────────────────────
# Logging configuration (stdout for Docker)
# ─────────────────────────────────────────
logger = logging.getLogger("rooms_service")
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

# Simple in-memory cache for read-heavy endpoints
CACHE_TTL_SECONDS = 30
STATUS_CACHE_TTL_SECONDS = 15
_rooms_cache_all = {"data": None, "expires_at": None}
_room_cache_by_id = {}
_room_status_cache = {}

def _now_utc():
    return datetime.utcnow()

def _get_cached_all_rooms():
    entry = _rooms_cache_all
    if entry["data"] is not None and entry["expires_at"] and entry["expires_at"] > _now_utc():
        return entry["data"]
    return None

def _set_cached_all_rooms(data):
    _rooms_cache_all["data"] = data
    _rooms_cache_all["expires_at"] = _now_utc() + timedelta(seconds=CACHE_TTL_SECONDS)

def _get_cached_room(room_id: int):
    entry = _room_cache_by_id.get(room_id)
    if entry and entry["expires_at"] and entry["expires_at"] > _now_utc():
        return entry["data"]
    return None

def _set_cached_room(room_id: int, data):
    _room_cache_by_id[room_id] = {
        "data": data,
        "expires_at": _now_utc() + timedelta(seconds=CACHE_TTL_SECONDS),
    }

def _invalidate_room_cache(room_id: int | None = None):
    _rooms_cache_all["data"] = None
    _rooms_cache_all["expires_at"] = None
    if room_id is None:
        _room_cache_by_id.clear()
        _room_status_cache.clear()
    else:
        _room_cache_by_id.pop(room_id, None)
        _room_status_cache.pop(room_id, None)

def _get_cached_room_status(room_id: int):
    entry = _room_status_cache.get(room_id)
    if entry and entry["expires_at"] and entry["expires_at"] > _now_utc():
        return entry["data"]
    return None

def _set_cached_room_status(room_id: int, data):
    _room_status_cache[room_id] = {
        "data": data,
        "expires_at": _now_utc() + timedelta(seconds=STATUS_CACHE_TTL_SECONDS),
    }

# Initialize DB tables once at startup (Flask 3 has no before_first_request)
init_rooms_table()
init_equipment_table()
init_room_equipment_table()

# ─────────────────────────────────────────────
# 1. GET ALLL ROOMS
# ─────────────────────────────────────────────
@app.route(f"{API_VERSION}/rooms", methods=["GET"])
def get_all_rooms():
    """
    Fetch all rooms from the database.
    Returns a list of rooms with their details.
    """
    cached_rooms = _get_cached_all_rooms()
    if cached_rooms is not None:
        return jsonify({"rooms": cached_rooms}), 200

    rooms = fetch_all_rooms()
    if not rooms:
        raise SmartRoomExceptions(404, "Not Found", "No rooms found.")
    for i in range(len(rooms)):
        equipments = fetch_equipment_for_room(rooms[i]["room_id"])
        room_obj = Room.room_with_equipment_dict(rooms[i], equipments)
        rooms[i] = room_obj.to_dict()

    _set_cached_all_rooms(rooms)
    return jsonify({"rooms": rooms}), 200

# ─────────────────────────────────────────────
# 2. GET A ROOM BY ITS ID
# ─────────────────────────────────────────────
@app.route(f"{API_VERSION}/rooms/<int:room_id>", methods=["GET"])
def get_room(room_id):
    """
    Fetch a single room by its ID.
    Returns the room details if found.
    """
    payload, error = require_auth()
    if error:
        raise error
    
    if not is_human_user(payload):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Human user role required.")

    cached_room = _get_cached_room(room_id)
    if cached_room is not None:
        return jsonify({"room": cached_room}), 200
    
    room = fetch_room(room_id)
    if not room:
        raise SmartRoomExceptions(404, "Not Found", "Room not found. Make sure the ID is valid.")
    equipments = fetch_equipment_for_room(room_id)
    room_obj = Room.room_with_equipment_dict(room, equipments)

    room_dict = room_obj.to_dict()
    _set_cached_room(room_id, room_dict)
    return jsonify({"room": room_dict}), 200

# ─────────────────────────────────────────────
# 3. ADD NEW ROOM
# ─────────────────────────────────────────────
@app.route(f"{API_VERSION}/rooms", methods=["POST"])
def add_room():
    payload, error = require_auth()
    if error:
        raise error
    
    if not is_admin_or_facility(payload):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Admin or Facility Manager role required.")

    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    capacity = data.get("capacity")
    location = (data.get("location") or "").strip()
    equipment_entries = data.get("equipment") or []
    if not name:
        raise SmartRoomExceptions(400, "Bad Request", "Room name is required.")
    if not isinstance(capacity, int) or capacity <= 0:
        raise SmartRoomExceptions(400, "Bad Request", "The capacity must be a positive integer.")
    if not isinstance(equipment_entries, list) or not equipment_entries:
        raise SmartRoomExceptions(400, "Bad Request", "Please make sure that you have at least on equipment in the room.")
    cleaned_equipment = []
    for entry in equipment_entries:
        equipment_name = (entry.get("name") or "").strip()
        quantity = entry.get("quantity")
        if not equipment_name or not isinstance(quantity, int) or quantity <= 0:
            raise SmartRoomExceptions(400, "Bad Request", "Each equipment needs a name and positive quantity.")
        cleaned_equipment.append(
            {
                "name": equipment_name,
                "quantity": quantity,
            }
        )
    try:
        room_row = create_room(name, capacity, location)
    except UniqueViolation:
        raise SmartRoomExceptions(409, "Conflict", "Room name already exists choose another.")

    set_room_equipment(room_row["room_id"], cleaned_equipment)

    equipment_with_details = fetch_equipment_for_room(room_row["room_id"])
    room_obj = Room.room_with_equipment_dict(room_row, equipment_with_details)
    _invalidate_room_cache()
    raise SmartRoomExceptions(201, "Created", {"room": room_obj.to_dict()})

# ─────────────────────────────────────────────
# 4. UPDATE ROOM DETAILS
# ─────────────────────────────────────────────

@app.route(f"{API_VERSION}/rooms/update/<string:current_name>", methods=["PUT"])
def update_room_details(current_name):
    data = request.get_json() or {}
    new_name = data.get("name")
    capacity = data.get("capacity")
    location = data.get("location")
    equipments = data.get("equipment")

    payload, error = require_auth()
    if error:
        raise error
    
    if not is_admin_or_facility(payload):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Admin or Facility Manager role required.")

    if new_name is not None:
        new_name = new_name.strip()
        if not new_name:
            raise SmartRoomExceptions(400, "Bad Request", "Room name cannot be empty.")
    if capacity is not None:
        if not isinstance(capacity, int) or capacity <= 0:
            raise SmartRoomExceptions(400, "Bad Request", "The capacity must be a positive integer.")
    if location is not None:
        location = location.strip()

    updated_room = update_room(current_name, new_name=new_name, capacity=capacity, location=location)
    if not updated_room:
        raise SmartRoomExceptions(404, "Not Found", "Room not found or no fields to update.")

    if equipments is not None:
        if not isinstance(equipments, list):
            raise SmartRoomExceptions(400, "Bad Request", "Equipments must be provided as a list.")
        cleaned_equipment = []
        for e in equipments:
            equipment_name = (e.get("name") or "").strip()
            quantity = e.get("quantity")
            if not equipment_name or not isinstance(quantity, int) or quantity <= 0:
                raise SmartRoomExceptions(400, "Bad Request", "Each equipment needs a name and positive quantity.")
            cleaned_equipment.append(
                {
                    "name": equipment_name,
                    "quantity": quantity,
                }
            )
        set_room_equipment(updated_room["room_id"], cleaned_equipment)

    equipment_with_details = fetch_equipment_for_room(updated_room["room_id"])
    room_obj = Room.room_with_equipment_dict(updated_room, equipment_with_details)
    _invalidate_room_cache(updated_room["room_id"])
    return jsonify({"room": room_obj.to_dict()}), 200

# ─────────────────────────────────────────────
# 5. DELETE A ROOM
# ─────────────────────────────────────────────
@app.route(f"{API_VERSION}/rooms/<int:room_id>", methods=["DELETE"])
def delete_room_endpoint(room_id: int):
    """
    Delete a room and its equipment associations.
    """
    payload, error = require_auth()
    if error:
        raise error
    
    if not is_admin_or_facility(payload):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Admin or Facility Manager role required.")
    deleted = delete_room(room_id)
    if not deleted:
        raise SmartRoomExceptions(404, "Not Found", "Room not found.")
    _invalidate_room_cache(room_id)
    return jsonify({"message": "Room deleted successfully."}), 200

# ─────────────────────────────────────────────
# 6. RETRIEVE AVAILABLE ROOMS 
# ─────────────────────────────────────────────
@app.route(f"{API_VERSION}/rooms/<int:room_id>/status", methods=["GET"])
def get_room_status(room_id: int):
    """
    Returns all bookings for the room and computes available time intervals for the day.
    """

    payload, error = require_auth()
    if error:
        raise error
    
    if not read_only(payload):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Auditor or Regular role required.")  

    cached_status = _get_cached_room_status(room_id)
    if cached_status is not None:
        return jsonify(cached_status), 200
    
    # Verify room exists
    room = fetch_room(room_id)
    if not room:
        raise SmartRoomExceptions(404, "Not Found", "Room not found.")

    # Fetch all bookings for this room
    bookings = fetch_bookings_for_room(room_id) or []

    # Filter bookings for the current day
    today = datetime.now().date()
    start_of_day = datetime.combine(today, datetime.min.time())  # 00:00
    end_of_day = datetime.combine(today, datetime.max.time())    # 24:00

    booked_ranges = []
    for b in bookings:
        # Parse booking dict directly
        start_time = b.get("start_time")
        end_time = b.get("end_time")
        if start_time and end_time and start_time.date() == today and end_time.date() == today:
            booked_ranges.append((start_time, end_time))


    # Sort by start time
    booked_ranges.sort()

    # Compute availability intervals for the day
    availability_intervals = []
    current_start = start_of_day

    for b_start, b_end in booked_ranges:
        # Add interval before the current booking
        if b_start > current_start:
            availability_intervals.append({
                "start_time": current_start.isoformat(),
                "end_time": b_start.isoformat()
            })
        # Update current_start to the end of the current booking
        current_start = max(current_start, b_end)

    # Add final interval if room is free after the last booking
    if current_start < end_of_day:
        availability_intervals.append({
            "start_time": current_start.isoformat(),
            "end_time": end_of_day.isoformat()
        })

    response_payload = {
        "room_id": room_id,
        "room_name": room.get("room_name"),
        "room_available": len(availability_intervals) > 0,
        "bookings": [
            {
                "id": b.get("booking_id"),
                "user_id": b.get("user_id"),
                "room_id": b.get("room_id"),
                "start_time": b.get("start_time").isoformat() if b.get("start_time") else None,
                "end_time": b.get("end_time").isoformat() if b.get("end_time") else None,
                "created_at": b.get("created_at").isoformat() if b.get("created_at") else None
            }
            for b in bookings
            if b.get("start_time") and b.get("start_time").date() == today
        ],
        "availability_intervals": availability_intervals
    }

    _set_cached_room_status(room_id, response_payload)
    return jsonify(response_payload), 200

# ─────────────────────────────────────────────
# 7. TOGGLE ROOM AVAILABILITY
# ─────────────────────────────────────────────
@app.route(f"{API_VERSION}/rooms/<int:room_id>/toggle_availability", methods=["PATCH"])
def toggle_room_availability(room_id):
    """
    Toggle the availability of a room.
    """
    payload, error = require_auth()
    if error:
        raise error

    if not is_admin(payload):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Admin or Facility Manager role required.")

    # Fetch the room
    room = fetch_room(room_id)
    if not room:
        raise SmartRoomExceptions(404, "Not Found", "Room not found.")

    # Toggle availability
    new_availability = not room["is_available"]
    update_room_availability(room_id, new_availability)

    _invalidate_room_cache(room_id)
    return jsonify({
        "message": f"Room {room_id} availability toggled.",
        "room_id": room_id,
        "is_available": new_availability
    }), 200

# ─────────────────────────────────────────────
# 8. SET/UNSET ROOM OUT OF SERVICE
# ─────────────────────────────────────────────
@app.route(f"{API_VERSION}/rooms/out_of_service/<int:room_id>", methods=["POST"])
def set_unset_out_of_service_endpoint(room_id):
    payload, error = require_auth()
    if error:
        raise error    
    if not is_facility(payload):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Facility role required.")

    data = request.get_json() or {}
    is_out_of_service = data.get("is_out_of_service")
    if is_out_of_service is None:
        raise SmartRoomExceptions(400, "Bad Request", "is_out_of_service field is required.")

    updated_room = set_unset_out_of_service(room_id, is_out_of_service)
    if not updated_room:
        raise SmartRoomExceptions(404, "Not Found", "Room not found.")

    status = "out of service" if is_out_of_service else "in service"

    if is_out_of_service:
        bookings = fetch_bookings_for_room(room_id) or []
        now = datetime.now()
        for booking_row in bookings:
            # Parse booking dict directly
            booking_id = booking_row.get("booking_id")
            user_id = booking_row.get("user_id")
            start_time = booking_row.get("start_time")
            end_time = booking_row.get("end_time")
            
            if not start_time or start_time <= now:
                continue

            user_contact = fetch_user_contact(user_id)
            if not user_contact:
                app.logger.warning(
                    "Room %s marked out of service but user %s contact missing for booking %s.",
                    room_id,
                    user_id,
                    booking_id,
                )
                continue

            user_email = user_contact.get("email")
            if not user_email:
                app.logger.warning(
                    "Room %s out of service; email missing for user %s (booking %s).",
                    room_id,
                    user_id,
                    booking_id,
                )
                continue

            start_display = start_time.strftime("%A, %B %d, %Y at %I:%M %p")
            end_display = end_time.strftime("%A, %B %d, %Y at %I:%M %p") if end_time else ""

            context = {
                "first_name": user_contact.get("first_name", ""),
                "last_name": user_contact.get("last_name", ""),
                "email": user_email,
                "room_name": updated_room.get("room_name") or f"Room {room_id}",
                "start_time": start_display,
                "end_time": end_display,
                "booking_id": str(booking_id),
            }

            try:
                status_code, message_id = send_templated_email(
                    to_email=user_email,
                    subject="Room unavailable for your upcoming booking",
                    template_name="RoomOutOfService.html",
                    context=context,
                )
                if status_code != 202:
                    app.logger.warning(
                        "Out-of-service email returned status %s for booking %s",
                        status_code,
                        booking_id,
                    )
                else:
                    app.logger.info(
                        "Out-of-service email sent for booking %s (message_id=%s)",
                        booking_id,
                        message_id,
                    )
            except EmailConfigurationError as cfg_err:
                app.logger.warning(
                    "Out-of-service email skipped due to configuration issue: %s",
                    cfg_err,
                )
            except Exception as email_err:
                app.logger.exception(
                    "Failed to send out-of-service email for booking %s: %s",
                    booking_id,
                    email_err,
                )

    _invalidate_room_cache(room_id)
    return jsonify({
        "message": f"Room {room_id} has been marked as {status}.",
        "room": updated_room
    }), 200

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # For development only; later we'll run via gunicorn or Docker
    app.run(host="0.0.0.0", port=5002, debug=True)
