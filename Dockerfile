# ==============================================================================
# Production Dockerfile for Real Estate Hunter & Scraper Pipeline
# ==============================================================================
FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Warsaw

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tzdata \
    ca-certificates \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first for optimal Docker layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy application source code
COPY . /app

# Ensure directories for SQLite database, reports, and logs exist
RUN mkdir -p /app/data /app/logs && chmod -R 777 /app/data /app/logs

# Expose web dashboard port
EXPOSE 8080

# Default healthcheck verifying the live dashboard API
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8080/api/config || exit 1

# Default command starts the live interactive web dashboard
CMD ["python", "main.py", "dashboard", "--host", "0.0.0.0", "--port", "8080", "--no-open"]