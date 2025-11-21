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
