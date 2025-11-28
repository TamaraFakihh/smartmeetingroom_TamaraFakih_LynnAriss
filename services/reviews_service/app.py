import logging
import sys
import time
import uuid
import os
from flask import Flask, request, jsonify, g
from services.reviews_service.db import (
    init_reviews_table,
    create_review,
    fetch_review_by_id,
    update_review,
    delete_review,
    fetch_review_by_room_id,
    init_reports_table,
    report_review,
    flag_unflag_review,
    fetch_all_reports,
    hide_review,
    fetch_all_reviews,
)
from services.reviews_service.models import Review
from common.RBAC import (
    require_auth,
    is_regular,
    is_moderator,
    is_admin,
    read_only,

)
from common.exeptions import *
from common.config import API_VERSION

app = Flask(__name__)

# ─────────────────────────────────────────
# Logging configuration (stdout for Docker)
# ─────────────────────────────────────────
logger = logging.getLogger("reviews_service")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)
log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(log_dir, exist_ok=True)
LOG_FILE_PATH = os.path.join(log_dir, "reviews_service.log")
file_handler = logging.FileHandler(LOG_FILE_PATH)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
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
init_reviews_table()
init_reports_table()

def _tail_log(file_path: str, max_lines: int) -> list[str]:
    """
    Return the last max_lines lines from the given log file.
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            return lines[-max_lines:]
    except FileNotFoundError:
        return []

# ─────────────────────────────────────────────
# 1. SUBMIT A REVIEW
# ─────────────────────────────────────────────

@app.route(f"{API_VERSION}/reviews", methods=["POST"])
def submit_review():
    """
    Submit a review for a meeting room.

    JSON body:
    {
        "room_id": 1,
        "rating": 5,
        "comment": "Great room!"
    }
    """
    payload, error = require_auth()
    if error:
        raise error
    if not is_regular(payload):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Regular user role required.")
    
    user_id = int(payload["sub"])

    data = request.get_json() or {}
    room_id = data.get("room_id")
    rating = data.get("rating")
    comment = data.get("comment", "").strip()

    # Validate inputs
    if not room_id or not rating:
        raise SmartRoomExceptions(400, "Bad Request", "room_id and rating are required.")
    if not (1 <= rating <= 5):
        raise SmartRoomExceptions(400, "Bad Request", "Rating must be between 1 and 5.")

    # Create review
    review_data = create_review(room_id, user_id, rating, comment)
    review = Review.from_dict(review_data)

    return jsonify({
        "message": "Review submitted successfully.",
        "review": review.to_dict()
    }), 201

# ─────────────────────────────────────────────
# 2. UPDATE A REVIEW
# ─────────────────────────────────────────────
@app.route(f"{API_VERSION}/reviews/update/<int:review_id>", methods=["PUT"])
def update_review_details(review_id):
    """
    Update an existing review.

    JSON body can include any of:
    {
        "rating": 4,
        "comment": "Updated comment"
    }
    """
    payload, error = require_auth()
    if error:
        raise error
    if not is_regular(payload):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Regular user role required.")
    
    user_id = int(payload["sub"])

    # Fetch existing review to verify ownership
    existing_review_data = fetch_review_by_id(review_id)
    if not existing_review_data:
        raise SmartRoomExceptions(404, "Not Found", "Review not found.")
    if existing_review_data["user_id"] != user_id:
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized to update this review.")

    data = request.get_json() or {}
    rating = data.get("rating")
    comment = data.get("comment")

    # Validate inputs
    if rating is not None and not (1 <= rating <= 5):
        raise SmartRoomExceptions(400, "Bad Request", "Rating must be between 1 and 5.")

    # Update review
    updated_review_data = update_review(review_id, rating, comment)
    updated_review = Review.from_dict(updated_review_data)

    return jsonify({
        "message": "Review updated successfully.",
        "review": updated_review.to_dict()
    }), 200

# ─────────────────────────────────────────────
# 3.DELETE A REVIEW
# ─────────────────────────────────────────────
@app.route(f"{API_VERSION}/reviews/<int:review_id>", methods=["DELETE"])
def delete_review_endpoint(review_id):
    """
    Delete an existing review.
    """
    payload, error = require_auth()
    if error:
        raise error
    if (not is_regular(payload) and existing_review_data["user_id"] != user_id):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. You can only delete your own reviews.")
    if not (is_admin(payload) or is_moderator(payload)):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized to delete this review. Only admins or moderators can delete reviews.")
    
    user_id = int(payload["sub"])

    # Fetch existing review to verify ownership
    existing_review_data = fetch_review_by_id(review_id)
    if not existing_review_data:
        raise SmartRoomExceptions(404, "Not Found", "Review not found.")

    # Delete review
    delete_review(review_id)

    return jsonify({"message": "Review deleted successfully."}), 200

# ─────────────────────────────────────────────
# 4. GET REVIEWS FOR A ROOM
# ─────────────────────────────────────────────
@app.route(f"{API_VERSION}/reviews/<int:room_id>", methods=["GET"])
def reviews_by_room_id(room_id):
    """
    Fetch all reviews for a specific meeting room.
    """
    
    reviews_data = fetch_review_by_room_id(room_id)
    payload, error = require_auth()
    if error:
        raise error
    if not read_only(payload) and not is_admin(payload) :
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Read-only roles required.")
    # Convert reviews to a list of dictionaries
    reviews = [Review.from_dict(review).to_dict() for review in reviews_data]

    return jsonify({
        "room_id": room_id,
        "reviews": reviews
    }), 200

# ─────────────────────────────────────────────
# 5. REPORT AN INAPPROPRIATE REVIEW
# ─────────────────────────────────────────────
@app.route(f"{API_VERSION}/reviews/report/<int:review_id>", methods=["POST"])
def report_review_endpoint(review_id):
    """
    Report an inappropriate review.
    """
    payload, error = require_auth()
    if error:
        raise error

    reporter_user_id = int(payload["sub"])
    data = request.get_json() or {}
    reason = data.get("reason", "").strip()

    if not reason:
        raise SmartRoomExceptions(400, "Bad Request", "Reason for reporting is required.")

    # Fetch the review directly
    existing_review = fetch_review_by_id(review_id)
    if not existing_review:
        raise SmartRoomExceptions(404, "Not Found", "The review does not exist.")

    # Insert the report
    report_data = report_review(review_id, reporter_user_id, reason)

    return jsonify({
        "message": f"Review {review_id} has been reported.",
        "report": report_data
    }), 201

# ─────────────────────────────────────────────
# 6. FLAG REVIEW 
# ─────────────────────────────────────────────
@app.route(f"{API_VERSION}/reviews/flag/<int:review_id>", methods=["POST"])
def flag_review(review_id):
    payload, error = require_auth()
    if error:
        raise error    
    if not (is_admin(payload) or is_moderator(payload)):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Admin or Moderator role required.")
        # Fetch the review to ensure it exists
    review = fetch_review_by_id(review_id)
    if not review:
        raise SmartRoomExceptions(404, "Not Found", "Review not found.")
    
    updated_flag= flag_unflag_review(review_id, True)
    return jsonify({
        "message": f"Review {review_id} has been flagged as inappropriate.",
        "review": updated_flag
    }), 200

# ─────────────────────────────────────────────
# 7. UNFLAG REVIEW 
# ─────────────────────────────────────────────
@app.route(f"{API_VERSION}/reviews/unflag/<int:review_id>", methods=["POST"])
def unflag_review(review_id):
    payload, error = require_auth()
    if error:
        raise error    
    if not (is_admin(payload) or is_moderator(payload)):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Admin or Moderator role required.")
        # Fetch the review to ensure it exists
    review = fetch_review_by_id(review_id)
    if not review:
        raise SmartRoomExceptions(404, "Not Found", "Review not found.")
    
    updated_flag= flag_unflag_review(review_id, False)
    return jsonify({
        "message": f"Review {review_id} has been unflagged.",
        "review": updated_flag
    }), 200

# ─────────────────────────────────────────────
# 8. GET ALL REPORTS 
# ─────────────────────────────────────────────
@app.route(f"{API_VERSION}/reviews/reports", methods=["GET"])
def get_all_reports():
    """
    Fetch all reported reviews.
    """
    payload, error = require_auth()
    if error:
        raise error    
    if not is_moderator(payload):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Moderator role required.")
    
    # Fetch all reports
    reports_data = fetch_all_reports()
    
    return jsonify({
        "reports": reports_data
    }), 200

# �"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?
# 9b. ADMIN: GET ALL REVIEWS
# �"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?�"?

@app.route(f"{API_VERSION}/reviews", methods=["GET"])
def get_all_reviews_endpoint():
    """
    Admin-only endpoint to fetch all non-hidden reviews.
    """
    payload, error = require_auth()
    if error:
        raise error

    if not is_admin(payload):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Admin role required.")

    reviews_data = fetch_all_reviews()
    reviews = [Review.from_dict(review).to_dict() for review in reviews_data]

    return jsonify({"reviews": reviews}), 200

# ─────────────────────────────────────────────
# 9. HIDE/UNHIDE A REVIEW
# ─────────────────────────────────────────────
@app.route(f"{API_VERSION}/reviews/hide/<int:review_id>", methods=["PATCH"])
def hide_review_endpoint(review_id):
    """
    Hide or unhide a review.
    - Regular users can hide their own reviews (cannot unhide once hidden).
    - Admins/Moderators can hide or unhide any review.
    """
    payload, error = require_auth()
    if error:
        raise error

    requester_id = int(payload["sub"])

    review = fetch_review_by_id(review_id)
    if not review:
        raise SmartRoomExceptions(404, "Not Found", "Review not found.")

    # Get the request data
    data = request.get_json() or {}
    is_hidden = data.get("is_hidden")

    if is_hidden is None:
        raise SmartRoomExceptions(400, "Bad Request", "The 'is_hidden' field is required.")

    # Regular users: can hide only their own review, cannot unhide
    if is_regular(payload):
        if review["user_id"] != requester_id:
            raise SmartRoomExceptions(403, "Forbidden", "You can only hide your own reviews.")
        if is_hidden is False:
            raise SmartRoomExceptions(403, "Forbidden", "You cannot unhide a review.")
    else:
        # Admins/Moderators can hide/unhide any review
        if not (is_moderator(payload) or is_admin(payload)):
            raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Admin or Moderator role required.")

    # Update the review's hidden status
    updated_review = hide_review(review_id, is_hidden)

    status = "hidden" if is_hidden else "visible"
    return jsonify({
        "message": f"Review {review_id} has been marked as {status}.",
        "review": updated_review
    }), 200

# ─────────────────────────────────────────────
# 10. ADMIN: VIEW SERVICE AUDIT LOGS (TAIL)
# ─────────────────────────────────────────────

@app.route(f"{API_VERSION}/ops/logs", methods=["GET"])
def get_service_logs():
    """
    Return the last N lines from the service log. Admin only.
    """
    payload, error = require_auth()
    if error:
        raise error

    if not is_admin(payload):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Admin role required.")

    max_lines = request.args.get("lines", default=200, type=int)
    max_lines = max(1, min(max_lines or 200, 1000))
    lines = _tail_log(LOG_FILE_PATH, max_lines)
    return jsonify({"lines": lines}), 200

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # For development only; later we'll run via gunicorn or Docker
    app.run(host="0.0.0.0", port=5003, debug=True)
