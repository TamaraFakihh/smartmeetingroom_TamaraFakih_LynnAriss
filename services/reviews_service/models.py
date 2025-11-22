from datetime import datetime

class Review:
    def __init__(self, review_id: int, room_id: int, user_id: int, rating: int, comment: str, created_at: datetime):
        self.review_id = review_id
        self.room_id = room_id
        self.user_id = user_id
        self.rating = rating
        self.comment = comment
        self.created_at = created_at

    def to_dict(self):
        """
        Convert the Review object to a dictionary for JSON serialization.
        """
        return {
            "review_id": self.review_id,
            "room_id": self.room_id,
            "user_id": self.user_id,
            "rating": self.rating,
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

    @staticmethod
    def from_dict(data: dict):
        """
        Create a Review object from a dictionary.
        Handles cases where created_at is already a datetime object or None.
        """
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif isinstance(created_at, datetime):
            created_at = created_at  # Use as is if it's already a datetime object
        else:
            created_at = None  # Set to None if it's not a valid datetime or string

        return Review(
            review_id=data.get("review_id"),
            room_id=data.get("room_id"),
            user_id=data.get("user_id"),
            rating=data.get("rating"),
            comment=data.get("comment"),
            created_at=created_at
        )