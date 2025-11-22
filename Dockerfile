# Allora Competition Pipeline Dockerfile
# Build: docker build -t allora-pipeline:latest .
# Run: docker run --env-file .env -v $(pwd)/logs:/app/logs allora-pipeline:latest

FROM python:3.12.1-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create logs directory
RUN mkdir -p /app/logs

# Health check: verify pipeline is running
HEALTHCHECK --interval=5m --timeout=30s --start-period=30s --retries=3 \
    CMD test -f /app/logs/submission.log || exit 1

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Run the competition submission pipeline
# Use --once flag to run a single cycle (suitable for scheduled cron jobs)
# Remove --once flag and comment out the exit to run continuously in a container
CMD ["python", "-u", "competition_submission.py"]

# Alternative: run a single submission per container execution
# CMD ["python", "-u", "competition_submission.py", "--once"]
