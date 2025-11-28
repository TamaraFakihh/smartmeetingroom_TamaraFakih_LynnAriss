FROM python:3.11-slim

WORKDIR /app

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy common module and bookings service
COPY common/ ./common/
COPY services/bookings_service/ ./services/bookings_service/

# Create data directory for database
RUN mkdir -p /app/data

# Expose port
EXPOSE 5003

# Run the application
CMD ["python", "-m", "services.bookings_service.app"]
