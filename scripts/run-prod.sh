#!/bin/bash
# run-prod.sh - Production runner for Linux VPS with Docker

# Ensure we're using docker
if ! command -v docker &> /dev/null; then
    echo "Docker is not installed. Please install Docker first."
    exit 1
fi

# Create necessary directories
mkdir -p ./data ./config ./ssl

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | xargs)
fi

# Stop existing containers
docker-compose down

# Pull latest images or rebuild
docker-compose build

# Start services with production configuration
echo "Starting CDON Tracker in production mode..."
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

echo "Services started!"
echo "Web dashboard: http://localhost:8080"
echo "Monitor logs: docker-compose logs -f monitor"
echo "Web logs: docker-compose logs -f web"
