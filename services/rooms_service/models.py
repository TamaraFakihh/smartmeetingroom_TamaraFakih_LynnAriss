from dataclasses import dataclass
from typing import List


@dataclass
class Room:
    id: int
    name: str
    location: str
    capacity: int
    equipment: List[dict] = None

    def to_dict(self) -> dict:
        """
        Return a dict representation of the Room.
        """
        return {
            "room_id": self.id,
            "name": self.name,
            "location": self.location,
            "capacity": self.capacity,
            "equipment": self.equipment,
        }
    
    @staticmethod
    def room_with_equipment_dict(room_data, equipment_data):
        # Create a Room object with both room and equipment data
        return Room(
            id=room_data["room_id"],
            name=room_data["room_name"],
            location=room_data["location"],
            capacity=room_data["capacity"],
            equipment=equipment_data  
        )   
