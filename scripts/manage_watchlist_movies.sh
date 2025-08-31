#!/bin/bash

# Simple script to backup and restore watchlist movies for development
# Usage: ./manage_watchlist_movies.sh [backup|restore]

set -e  # Exit on any error

# Configuration
BACKUP_FILE="watchlist_movies.txt"
API_URL="http://localhost:8080"
DB_PATH=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Find database path
find_database() {
    # Try container path first
    if [ -f "/app/data/cdon_movies.db" ]; then
        DB_PATH="/app/data/cdon_movies.db"
        log_info "Found database at: $DB_PATH"
        return
    fi
    
    # Try local path
    if [ -f "./data/cdon_movies.db" ]; then
        DB_PATH="./data/cdon_movies.db"
        log_info "Found database at: $DB_PATH"
        return
    fi
    
    # Try relative to script location
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -f "$SCRIPT_DIR/data/cdon_movies.db" ]; then
        DB_PATH="$SCRIPT_DIR/data/cdon_movies.db"
        log_info "Found database at: $DB_PATH"
        return
    fi
    
    log_error "Could not find database file. Tried:"
    log_error "  - /app/data/cdon_movies.db"
    log_error "  - ./data/cdon_movies.db"
    log_error "  - $SCRIPT_DIR/data/cdon_movies.db"
    exit 1
}

# Backup watchlist movies
backup_watchlist_movies() {
    log_info "Starting backup of watchlist movies..."
    
    find_database
    
    # Check if database exists and is readable
    if [ ! -r "$DB_PATH" ]; then
        log_error "Cannot read database at: $DB_PATH"
        exit 1
    fi
    
    # Query watchlist movies and save product_ids
    sqlite3 "$DB_PATH" "
        SELECT m.product_id 
        FROM watchlist w 
        JOIN movies m ON w.movie_id = m.id 
        ORDER BY w.added_at;
    " > "$BACKUP_FILE"
    
    local count=$(wc -l < "$BACKUP_FILE")
    
    if [ "$count" -eq 0 ]; then
        log_warn "No watchlist movies found in database"
        rm -f "$BACKUP_FILE"
    else
        log_info "Successfully backed up $count watchlist movies to: $BACKUP_FILE"
    fi
}

# Check if API is available
check_api() {
    log_info "Checking if API is available at $API_URL..."
    
    if ! curl -s -f "$API_URL/api/stats" > /dev/null; then
        log_error "API is not available at $API_URL"
        log_error "Please make sure the web dashboard is running:"
        log_error "  task docker-dev  (or)  task web"
        exit 1
    fi
    
    log_info "API is available"
}

# Restore watchlist movies
restore_watchlist_movies() {
    log_info "Starting restore of watchlist movies..."
    
    # Check if backup file exists
    if [ ! -f "$BACKUP_FILE" ]; then
        log_error "Backup file not found: $BACKUP_FILE"
        log_error "Run './manage_watchlist_movies.sh backup' first"
        exit 1
    fi
    
    check_api
    
    local total=$(wc -l < "$BACKUP_FILE")
    if [ "$total" -eq 0 ]; then
        log_warn "Backup file is empty"
        exit 0
    fi
    
    log_info "Restoring $total watchlist movies..."
    
    local success_count=0
    local error_count=0
    local line_number=0
    
    while IFS= read -r product_id; do
        line_number=$((line_number + 1))
        
        # Skip empty lines
        if [ -z "$product_id" ]; then
            continue
        fi
        
        echo -n "[$line_number/$total] Adding to watchlist: $product_id... "
        
        # Call API to add movie to watchlist
        response=$(curl -s -X POST "$API_URL/api/watchlist" \
            -H "Content-Type: application/json" \
            -d "{\"product_id\":\"$product_id\"}" \
            -w "%{http_code}")
        
        # Extract HTTP status code (last 3 characters)
        http_code="${response: -3}"
        response_body="${response%???}"
        
        if [ "$http_code" = "200" ]; then
            echo -e "${GREEN}✓${NC}"
            success_count=$((success_count + 1))
        else
            echo -e "${RED}✗ (HTTP $http_code)${NC}"
            error_count=$((error_count + 1))
        fi
        
        # Small delay to avoid overwhelming the API
        sleep 0.1
    done < "$BACKUP_FILE"
    
    log_info "Restore completed:"
    log_info "  Success: $success_count"
    if [ "$error_count" -gt 0 ]; then
        log_warn "  Errors:  $error_count"
    fi
}

# Show usage
show_usage() {
    echo "Usage: $0 [backup|restore]"
    echo ""
    echo "Commands:"
    echo "  backup   - Export watchlist movies to $BACKUP_FILE"
    echo "  restore  - Import watchlist movies from $BACKUP_FILE (requires web dashboard running)"
    echo ""
    echo "Examples:"
    echo "  $0 backup   # Save current watchlist movies"
    echo "  $0 restore  # Restore watchlist movies after database reset"
}

# Main script
case "${1:-}" in
    "backup")
        backup_watchlist_movies
        ;;
    "restore")
        restore_watchlist_movies
        ;;
    *)
        show_usage
        exit 1
        ;;
esac