#!/bin/bash
# quickstart.sh - Quick setup and start script

echo "================================"
echo "CDON Blu-ray Tracker Quick Start"
echo "================================"
echo ""

# Detect OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "📱 Detected macOS"
    TOOL="podman"
    COMPOSE="podman-compose"
else
    echo "🐧 Detected Linux"
    TOOL="docker"
    COMPOSE="docker-compose"
fi

# Check if tool is installed
if ! command -v $TOOL &> /dev/null; then
    echo "❌ $TOOL is not installed!"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "Install with: brew install podman podman-compose"
    else
        echo "Install with: curl -fsSL https://get.docker.com | sh"
    fi
    exit 1
fi

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p data config backups

# Copy env file if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file..."
    cp .env.example .env
    echo "   ➡️  Edit .env to add email/Discord notifications (optional)"
fi

# Make scripts executable
echo "🔧 Setting permissions..."
chmod +x scripts/*.sh

# Start Podman machine if on macOS
if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! podman machine list | grep -q "Running"; then
        echo "🚀 Starting Podman machine..."
        podman machine init --cpus 2 --memory 4096 --disk-size 20 2>/dev/null || true
        podman machine start
    fi
fi

# Build the container
echo "🔨 Building container..."
$TOOL build -t cdon-tracker:latest .

# Start services
echo "🎬 Starting services..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    $COMPOSE -f docker-compose.yml -f docker-compose.override.yml up -d
else
    $COMPOSE up -d
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "🌐 Web dashboard: http://localhost:8080"
echo ""
echo "Next steps:"
echo "1. Run initial crawl: $COMPOSE run --rm crawler"
echo "2. View logs: $COMPOSE logs -f"
echo "3. Stop services: $COMPOSE down"
echo ""
echo "📖 See README.md for more information"
