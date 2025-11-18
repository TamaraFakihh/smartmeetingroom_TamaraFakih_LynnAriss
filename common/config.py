import os
from dotenv import load_dotenv

# Load variables from .env in development (optional but convenient)
load_dotenv()

# Example: postgresql://user:password@localhost:5432/smart_meeting_db
# DATABASE_URL = os.getenv(
#     "DATABASE_URL",
#     "postgresql://postgres:MyStrongPass123!@localhost:5433/smart_meeting_db"
# )

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:MyStrongPass123!@localhost:5433/smart_meeting_db"
)


# Secret key for JWT – in real deployment this should be strong and stored safely
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change_this_in_production")

# Token expiry in minutes (example)
JWT_EXP_MINUTES = int(os.getenv("JWT_EXP_MINUTES", "60"))
