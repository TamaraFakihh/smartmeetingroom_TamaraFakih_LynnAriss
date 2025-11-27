from flask import Flask, request, jsonify
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

@app.errorhandler(SmartRoomExceptions)
def handle_smart_room_exception(e):
    return jsonify(e.to_dict()), e.status_code

# Initialize DB tables once at startup
init_reviews_table()
init_reports_table()

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

# ─────────────────────────────────────────────
# 9. HIDE/UNHIDE A REVIEW
# ─────────────────────────────────────────────
@app.route(f"{API_VERSION}/reviews/hide/<int:review_id>", methods=["PATCH"])
def hide_review_endpoint(review_id):
    """
    Hide or unhide a review. Moderator access only.
    """
    payload, error = require_auth()
    if error:
        raise error

    # Ensure the user is a moderator
    if not is_moderator(payload):
        raise SmartRoomExceptions(403, "Forbidden", "Unauthorized. Moderator role required.")

    # Get the request data
    data = request.get_json() or {}
    is_hidden = data.get("is_hidden")

    if is_hidden is None:
        raise SmartRoomExceptions(400, "Bad Request", "The 'is_hidden' field is required.")

    # Update the review's hidden status
    updated_review = hide_review(review_id, is_hidden)
    if not updated_review:
        raise SmartRoomExceptions(404, "Not Found", "Review not found.")

    status = "hidden" if is_hidden else "visible"
    return jsonify({
        "message": f"Review {review_id} has been marked as {status}.",
        "review": updated_review
    }), 200

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # For development only; later we'll run via gunicorn or Docker
    app.run(host="0.0.0.0", port=5003, debug=True)