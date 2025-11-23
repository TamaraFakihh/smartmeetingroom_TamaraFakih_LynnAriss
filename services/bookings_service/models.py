from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Booking:
    """
    Dataclass representing a booking entity.
    """
    id: Optional[int]
    user_id: int
    room_id: int
    start_time: datetime
    end_time: datetime
    created_at: datetime

    def to_dict(self) -> dict:
        """
        Convert the Booking object to a JSON-serializable dict.
        """
        return {
            "booking_id": self.id,
            "user_id": self.user_id,
            "room_id": self.room_id,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @staticmethod
    def from_dict(data: dict) -> "Booking":
        """
        Create a Booking object from a dictionary.
        """
        def parse_dt(value):
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value)
                except ValueError:
                    return None
            return value

        return Booking(
            id=data.get("booking_id"),
            user_id=data["user_id"],
            room_id=data["room_id"],
            start_time=parse_dt(data["start_time"]),
            end_time=parse_dt(data["end_time"]),
            created_at=parse_dt(data["created_at"]),
        )