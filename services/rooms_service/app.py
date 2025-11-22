from flask import Flask, jsonify, request
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
                                       fetch_available_rooms,
                                       fetch_bookings_for_room

                                       )



app = Flask(__name__)

# Initialize DB tables once at startup (Flask 3 has no before_first_request)
init_rooms_table()
init_equipment_table()
init_room_equipment_table()

# ─────────────────────────────────────────────
# 1. GET ALLL ROOMS
# ─────────────────────────────────────────────
@app.route("/rooms", methods=["GET"])
def get_all_rooms():
    """
    Fetch all rooms from the database.
    Returns a list of rooms with their details.
    """
    rooms = fetch_all_rooms()
    if not rooms:
        return jsonify({"error": "No rooms found."}), 404
    for i in range(len(rooms)):
        equipments = fetch_equipment_for_room(rooms[i]["room_id"])
        room_obj = Room.room_with_equipment_dict(rooms[i], equipments)
        rooms[i] = room_obj.to_dict()

    return jsonify({"rooms": rooms}), 200

# ─────────────────────────────────────────────
# 2. GET A ROOM BY ITS ID
# ─────────────────────────────────────────────
@app.route("/rooms/<int:room_id>", methods=["GET"])
def get_room(room_id):
    """
    Fetch a single room by its ID.
    Returns the room details if found.
    """
    room = fetch_room(room_id)
    if not room:
        return jsonify({"error": "Room not found mnake sure the id is valid."}), 404
    equipments = fetch_equipment_for_room(room_id)
    room_obj = Room.room_with_equipment_dict(room, equipments)

    return jsonify({"room": room_obj.to_dict()}), 200

# ─────────────────────────────────────────────
# 3. ADD NEW ROOM
# ─────────────────────────────────────────────
@app.route("/rooms", methods=["POST"])
def add_room():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    capacity = data.get("capacity")
    location = (data.get("location") or "").strip()
    equipment_entries = data.get("equipment") or []
    if not name:
        return jsonify({"error": "Room name is required."}), 400
    if not isinstance(capacity, int) or capacity <= 0:
        return jsonify({"error": "The capacity must be a positive integer."}), 400
    if not isinstance(equipment_entries, list) or not equipment_entries:
        return jsonify({"error": "Please make sure that you have at least on equipment in the room."}), 400

    cleaned_equipment = []
    for entry in equipment_entries:
        equipment_name = (entry.get("name") or "").strip()
        quantity = entry.get("quantity")
        if not equipment_name or not isinstance(quantity, int) or quantity <= 0:
            return jsonify({"error": "Each equipment needs a name and positive quantity."}), 400
        cleaned_equipment.append(
            {
                "name": equipment_name,
                "quantity": quantity,
            }
        )
    try:
        room_row = create_room(name, capacity, location)
    except UniqueViolation:
        return jsonify({"error": "Room name already exists choose another."}), 409

    set_room_equipment(room_row["room_id"], cleaned_equipment)

    equipment_with_details = fetch_equipment_for_room(room_row["room_id"])
    room_obj = Room.room_with_equipment_dict(room_row, equipment_with_details)
    return jsonify({"room": room_obj.to_dict()}), 201

# ─────────────────────────────────────────────
# 4. UPDATE ROOM DETAILS
# ─────────────────────────────────────────────

@app.route("/rooms/update/<string:current_name>", methods=["PUT"])
def update_room_details(current_name):
    data = request.get_json() or {}
    new_name = data.get("name")
    capacity = data.get("capacity")
    location = data.get("location")
    equipments = data.get("equipment")

    if new_name is not None:
        new_name = new_name.strip()
        if not new_name:
            return jsonify({"error": "Room name cannot be empty."}), 400
    if capacity is not None:
        if not isinstance(capacity, int) or capacity <= 0:
            return jsonify({"error": "The capacity must be a positive integer."}), 400
    if location is not None:
        location = location.strip()

    updated_room = update_room(current_name, new_name=new_name, capacity=capacity, location=location)
    if not updated_room:
        return jsonify({"error": "Room not found or no fields to update."}), 404

    if equipments is not None:
        if not isinstance(equipments, list):
            return jsonify({"error": "Equipments must be provided as a list."}), 400
        cleaned_equipment = []
        for e in equipments:
            equipment_name = (e.get("name") or "").strip()
            quantity = e.get("quantity")
            if not equipment_name or not isinstance(quantity, int) or quantity <= 0:
                return jsonify({"error": "Each equipment needs a name and positive quantity."}), 400
            cleaned_equipment.append(
                {
                    "name": equipment_name,
                    "quantity": quantity,
                }
            )
        set_room_equipment(updated_room["room_id"], cleaned_equipment)

    equipment_with_details = fetch_equipment_for_room(updated_room["room_id"])
    room_obj = Room.room_with_equipment_dict(updated_room, equipment_with_details)
    return jsonify({"room": room_obj.to_dict()}), 200

# ─────────────────────────────────────────────
# 5. DELETE A ROOM
# ─────────────────────────────────────────────
@app.route("/rooms/<int:room_id>", methods=["DELETE"])
def delete_room_endpoint(room_id: int):
    """
    Delete a room and its equipment associations.
    """
    deleted = delete_room(room_id)
    if not deleted:
        return jsonify({"error": "Room not found."}), 404
    return jsonify({"message": "Room deleted successfully."}), 200

# ─────────────────────────────────────────────
# 6. RETRIEVE AVAILABLE ROOMS 
# ─────────────────────────────────────────────
@app.route("/rooms/<int:room_id>/status", methods=["GET"])
def get_room_status(room_id: int):
    """
    Returns all bookings for the room and computes available time intervals for the day.
    """
    # Verify room exists
    room = fetch_room(room_id)
    if not room:
        return jsonify({"error": "Room not found."}), 404

    # Fetch all bookings for this room
    bookings = fetch_bookings_for_room(room_id) or []

    def parse_dt(value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except Exception:
                return None
        return None

    def booking_to_dict(r):
        start = parse_dt(r.get("start_time"))
        end = parse_dt(r.get("end_time"))
        created = parse_dt(r.get("created_at"))
        return {
            "booking_id": r.get("booking_id"),
            "user_id": r.get("user_id"),
            "room_id": r.get("room_id"),
            "start_time": start.isoformat() if start else None,
            "end_time": end.isoformat() if end else None,
            "created_at": created.isoformat() if created else None,
        }

    # Filter bookings for the current day
    today = datetime.now().date()
    start_of_day = datetime.combine(today, datetime.min.time())  # 00:00
    end_of_day = datetime.combine(today, datetime.max.time())    # 24:00

    booked_ranges = []
    for b in bookings:
        start = parse_dt(b.get("start_time"))
        end = parse_dt(b.get("end_time"))
        if start and end and start.date() == today and end.date() == today:
            booked_ranges.append((start, end))

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

    return jsonify({
        "room_id": room_id,
        "room_name": room.get("room_name"),
        "room_available": len(availability_intervals) > 0,
        "bookings": [booking_to_dict(r) for r in bookings if parse_dt(r.get("start_time")).date() == today],
        "availability_intervals": availability_intervals
    }), 200

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # For development only; later we'll run via gunicorn or Docker
    app.run(host="0.0.0.0", port=5002, debug=True)