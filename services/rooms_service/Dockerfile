FROM python:3.11-slim

WORKDIR /app

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy common module and rooms service
COPY common/ ./common/
COPY services/rooms_service/ ./services/rooms_service/

# Create data directory for database
RUN mkdir -p /app/data

# Expose port
EXPOSE 5002

# Run the application
CMD ["python", "-m", "services.rooms_service.app"]