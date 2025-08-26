#!/bin/bash
# backup.sh - Backup database and configuration

BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Create backup directory
mkdir -p $BACKUP_DIR

# Detect container tool
if command -v podman &> /dev/null; then
    TOOL="podman"
else
    TOOL="docker"
fi

# Backup database
if [ -f ./data/cdon_movies.db ]; then
    cp ./data/cdon_movies.db "$BACKUP_DIR/cdon_movies_$TIMESTAMP.db"
    echo "Database backed up to $BACKUP_DIR/cdon_movies_$TIMESTAMP.db"
fi

# Create tar archive of all data
tar -czf "$BACKUP_DIR/cdon_backup_$TIMESTAMP.tar.gz" ./data ./config .env 2>/dev/null

echo "Full backup created: $BACKUP_DIR/cdon_backup_$TIMESTAMP.tar.gz"

# Optional: Keep only last 7 backups
find $BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete
echo "Old backups cleaned up (keeping last 7 days)"
