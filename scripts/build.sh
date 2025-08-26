#!/bin/bash
# build.sh - Build script that works with both Podman and Docker

# Detect if we're using podman or docker
if command -v podman &> /dev/null; then
    CONTAINER_TOOL="podman"
    echo "Using Podman"
else
    CONTAINER_TOOL="docker"
    echo "Using Docker"
fi

# Build the image
echo "Building CDON Tracker image..."
$CONTAINER_TOOL build -t cdon-tracker:latest .

echo "Build complete!"
