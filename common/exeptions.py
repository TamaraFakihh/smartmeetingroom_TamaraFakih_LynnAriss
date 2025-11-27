


class SmartRoomExceptions(Exception):
    def __init__(self, status_code: int, error: str, details: str = None):
        self.error = error
        self.status_code = status_code
        self.details = details

    def to_dict(self) -> dict:
        """Convert exception to dictionary for JSON response"""
        response = {
            "error": self.error,
            "status_code": self.status_code,
        }
        if self.details:
            response["details"] = self.details
        return response