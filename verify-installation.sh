#!/bin/bash
# verify-installation.sh - Verify that the installation is complete and working

echo "======================================"
echo "CDON Tracker Installation Verification"
echo "======================================"
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check functions
check_command() {
    if command -v $1 &> /dev/null; then
        echo -e "${GREEN}✓${NC} $1 is installed"
        return 0
    else
        echo -e "${RED}✗${NC} $1 is not installed"
        return 1
    fi
}

check_file() {
    if [ -f "$1" ]; then
        echo -e "${GREEN}✓${NC} $1 exists"
        return 0
    else
        echo -e "${RED}✗${NC} $1 is missing"
        return 1
    fi
}

check_dir() {
    if [ -d "$1" ]; then
        echo -e "${GREEN}✓${NC} $1 directory exists"
        return 0
    else
        echo -e "${YELLOW}!${NC} $1 directory missing (will be created on first run)"
        return 0
    fi
}

echo "Checking system requirements..."
echo "--------------------------------"

# Detect OS and container tool
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "Operating System: macOS"
    TOOL="podman"
    COMPOSE="podman-compose"
else
    echo "Operating System: Linux"
    TOOL="docker"
    COMPOSE="docker-compose"
fi

check_command $TOOL
check_command $COMPOSE
check_command python3

echo ""
echo "Checking project files..."
echo "-------------------------"

check_file "Dockerfile"
check_file "docker-compose.yml"
check_file "requirements.txt"
check_file "cdon_scraper.py"
check_file "monitor.py"
check_file ".env.example"

echo ""
echo "Checking directories..."
echo "-----------------------"

check_dir "data"
check_dir "config"
check_dir "scripts"
check_dir "backups"

echo ""
echo "Checking configuration..."
echo "-------------------------"

if [ -f ".env" ]; then
    echo -e "${GREEN}✓${NC} .env file exists"
    
    # Check if email is configured
    if grep -q "EMAIL_ENABLED=true" .env 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Email notifications configured"
    else
        echo -e "${YELLOW}!${NC} Email notifications not enabled (optional)"
    fi
    
    # Check if Discord is configured
    if grep -q "DISCORD_WEBHOOK=https://" .env 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Discord notifications configured"
    else
        echo -e "${YELLOW}!${NC} Discord notifications not configured (optional)"
    fi
else
    echo -e "${YELLOW}!${NC} .env file not found (will use defaults)"
    echo "   Run: cp .env.example .env"
fi

echo ""
echo "Checking container status..."
echo "----------------------------"

# Check if Podman machine is running (macOS only)
if [[ "$OSTYPE" == "darwin"* ]]; then
    if podman machine list 2>/dev/null | grep -q "Running"; then
        echo -e "${GREEN}✓${NC} Podman machine is running"
    else
        echo -e "${YELLOW}!${NC} Podman machine not running"
        echo "   Run: podman machine start"
    fi
fi

# Check if containers are running
if $COMPOSE ps 2>/dev/null | grep -q "Up"; then
    echo -e "${GREEN}✓${NC} Containers are running"
    echo ""
    echo "Running containers:"
    $COMPOSE ps
else
    echo -e "${YELLOW}!${NC} No containers running"
    echo "   Run: ./quickstart.sh to start"
fi

echo ""
echo "======================================"
echo "Verification Summary"
echo "======================================"

if [ -f "quickstart.sh" ]; then
    echo -e "${GREEN}Ready to go!${NC}"
    echo ""
    echo "Quick start commands:"
    echo "  ./quickstart.sh         - Set up and start everything"
    echo "  $COMPOSE run --rm crawler  - Run initial crawl"
    echo "  $COMPOSE logs -f          - View logs"
    echo "  $COMPOSE down             - Stop all services"
    echo ""
    echo "Web dashboard will be available at: http://localhost:8080"
else
    echo -e "${RED}Missing quickstart.sh!${NC}"
fi

echo ""
echo "For more information, see README.md"
