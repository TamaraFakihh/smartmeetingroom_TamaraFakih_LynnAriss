FROM python:3.11-slim

WORKDIR /app

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy common module and reviews service
COPY common/ ./common/
COPY services/reviews_service/ ./services/reviews_service/

# Create data directory for database
RUN mkdir -p /app/data

# Expose port
EXPOSE 5004

# Run the application
CMD ["python", "-m", "services.reviews_service.app"]