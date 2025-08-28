#!/bin/bash
# migrate-to-vps.sh - Helper script to migrate from dev to production

echo "CDON Tracker Migration Script"
echo "=============================="

# Check for required files
if [ ! -f ./data/cdon_movies.db ]; then
    echo "Error: No database found at ./data/cdon_movies.db"
    exit 1
fi

# Get VPS details
read -p "Enter your VPS IP/hostname: " VPS_HOST
read -p "Enter your VPS username: " VPS_USER
read -p "Enter target directory on VPS [/opt/cdon-tracker]: " VPS_DIR
VPS_DIR=${VPS_DIR:-/opt/cdon-tracker}

# Create migration package
echo "Creating migration package..."
MIGRATION_PACKAGE="cdon-migration-$(date +%Y%m%d).tar.gz"

tar -czf $MIGRATION_PACKAGE \
    Dockerfile \
    docker-compose.yml \
    docker-compose.prod.yml \
    requirements.txt \
    cdon_scraper.py \
    listing_crawler.py \
    product_parser.py \
    monitor.py \
    nginx.conf \
    scripts/run-prod.sh \
    scripts/backup.sh \
    data/ \
    .env.example

echo "Package created: $MIGRATION_PACKAGE"

# Transfer to VPS
echo "Transferring to VPS..."
scp $MIGRATION_PACKAGE $VPS_USER@$VPS_HOST:/tmp/

# Setup on VPS
echo "Setting up on VPS..."
ssh $VPS_USER@$VPS_HOST << EOF
    # Create directory
    sudo mkdir -p $VPS_DIR
    sudo chown $VPS_USER:$VPS_USER $VPS_DIR
    
    # Extract package
    cd $VPS_DIR
    tar -xzf /tmp/$MIGRATION_PACKAGE
    
    # Set permissions
    chmod +x scripts/run-prod.sh scripts/backup.sh
    
    # Install Docker if not present
    if ! command -v docker &> /dev/null; then
        echo "Installing Docker..."
        curl -fsSL https://get.docker.com | sh
        sudo usermod -aG docker $VPS_USER
    fi
    
    # Install docker-compose if not present
    if ! command -v docker-compose &> /dev/null; then
        echo "Installing Docker Compose..."
        sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-Linux-x86_64" -o /usr/local/bin/docker-compose
        sudo chmod +x /usr/local/bin/docker-compose
    fi
    
    echo "Setup complete on VPS!"
    echo "Next steps:"
    echo "1. SSH to your VPS: ssh $VPS_USER@$VPS_HOST"
    echo "2. cd $VPS_DIR"
    echo "3. cp .env.example .env and edit with your settings"
    echo "4. ./scripts/run-prod.sh"
EOF

echo "Migration complete!"
