#!/bin/bash
# run-dev.sh - Development runner for macOS with Podman

# Check if podman is installed
if ! command -v podman &> /dev/null; then
    echo "Podman is not installed. Please install it first:"
    echo "brew install podman"
    exit 1
fi

# Initialize podman machine if not running (macOS specific)
if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! podman machine list | grep -q "Running"; then
        echo "Starting Podman machine..."
        podman machine init --cpus 2 --memory 4096 --disk-size 20 || true
        podman machine start
    fi
fi

# Create data directory if it doesn't exist
mkdir -p ./data ./config

# Stop existing containers
podman-compose down 2>/dev/null || true

# Start services with development overrides
echo "Starting CDON Tracker in development mode..."
podman-compose -f docker-compose.yml -f docker-compose.override.yml up -d web monitor

echo "Services started!"
echo "Web dashboard: http://localhost:8080"
echo "Logs: podman-compose logs -f"

# Optional: Run initial crawl
read -p "Do you want to run an initial crawl? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    podman-compose run --rm crawler
fi
