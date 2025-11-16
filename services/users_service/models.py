from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    id: Optional[int]
    first_name: str
    last_name: str
    username: str
    email: str
    password_hash: str
    role: str = "regular"

    def to_public_dict(self) -> dict:
        """
        Return a dict safe to send in API responses.
        Excludes password_hash.
        """
        return {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "username": self.username,
            "email": self.email,
            "role": self.role,
        }
