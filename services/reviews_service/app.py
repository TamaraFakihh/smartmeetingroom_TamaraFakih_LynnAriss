from flask import Flask, request, jsonify
from services.reviews_service.db import (
    init_reviews_table,
    create_review,
    fetch_review_by_id,
    update_review,
    delete_review,
    fetch_review_by_room_id,
    report_review,
    init_reports_table,
    report_review,

)
from services.reviews_service.models import Review
from services.users_service.app import require_auth
app = Flask(__name__)

# Initialize DB tables once at startup
init_reviews_table()
init_reports_table()

# ─────────────────────────────────────────────
# 1. SUBMIT A REVIEW
# ─────────────────────────────────────────────

@app.route("/reviews", methods=["POST"])
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
        return error

    user_id = int(payload["sub"])

    data = request.get_json() or {}
    room_id = data.get("room_id")
    rating = data.get("rating")
    comment = data.get("comment", "").strip()

    # Validate inputs
    if not room_id or not rating:
        return jsonify({"error": "room_id and rating are required."}), 400
    if not (1 <= rating <= 5):
        return jsonify({"error": "Rating must be between 1 and 5."}), 400

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
@app.route("/reviews/update/<int:review_id>", methods=["PUT"])
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
        return error

    user_id = int(payload["sub"])

    # Fetch existing review to verify ownership
    existing_review_data = fetch_review_by_id(review_id)
    if not existing_review_data:
        return jsonify({"error": "Review not found."}), 404
    if existing_review_data["user_id"] != user_id:
        return jsonify({"error": "Unauthorized to update this review."}), 403

    data = request.get_json() or {}
    rating = data.get("rating")
    comment = data.get("comment")

    # Validate inputs
    if rating is not None and not (1 <= rating <= 5):
        return jsonify({"error": "Rating must be between 1 and 5."}), 400

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
@app.route("/reviews/<int:review_id>", methods=["DELETE"])
def delete_review_endpoint(review_id):
    """
    Delete an existing review.
    """
    payload, error = require_auth()
    if error:
        return error

    user_id = int(payload["sub"])

    # Fetch existing review to verify ownership
    existing_review_data = fetch_review_by_id(review_id)
    if not existing_review_data:
        return jsonify({"error": "Review not found."}), 404
    if existing_review_data["user_id"] != user_id:
        return jsonify({"error": "Unauthorized to delete this review."}), 403

    # Delete review
    delete_review(review_id)

    return jsonify({"message": "Review deleted successfully."}), 200

# ─────────────────────────────────────────────
# 4. GET REVIEWS FOR A ROOM
# ─────────────────────────────────────────────
@app.route("/reviews/<int:room_id>", methods=["GET"])
def reviews_by_room_id(room_id):
    """
    Fetch all reviews for a specific meeting room.
    """
    reviews_data = fetch_review_by_room_id(room_id)

    # Convert reviews to a list of dictionaries
    reviews = [Review.from_dict(review).to_dict() for review in reviews_data]

    return jsonify({
        "room_id": room_id,
        "reviews": reviews
    }), 200

# ─────────────────────────────────────────────
# 5. REPORT AN INAPPROPRIATE REVIEW
# ─────────────────────────────────────────────
@app.route("/reviews/report/<int:review_id>", methods=["POST"])
def report_review_endpoint(review_id):
    """
    Report an inappropriate review.
    """
    payload, error = require_auth()
    if error:
        return error

    reporter_user_id = int(payload["sub"])
    data = request.get_json() or {}
    reason = data.get("reason", "").strip()

    if not reason:
        return jsonify({"error": "Reason for reporting is required."}), 400

    # Fetch the review directly
    existing_review = fetch_review_by_id(review_id)
    if not existing_review:
        return jsonify({"error": "The review does not exist."}), 404

    # Insert the report
    report_data = report_review(review_id, reporter_user_id, reason)

    return jsonify({
        "message": f"Review {review_id} has been reported.",
        "report": report_data
    }), 201

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # For development only; later we'll run via gunicorn or Docker
    app.run(host="0.0.0.0", port=5003, debug=True)