#!/bin/bash
# Neo4j Docker Management Scripts
# Make this file executable: chmod +x neo4j-manage.sh

set -Eeuo pipefail

# Logging
log_error() {
    echo -e "\033[0;31m[ERROR]\033[0m $*" >&2
}

log_info() {
    echo -e "\033[0;32m[INFO]\033[0m $*"
}

# Configuration
CONTAINER_NAME="neo4j"
NEO4J_VERSION="2025.09.0-enterprise"
NEO4J_USER="neo4j"
BACKUP_DIR="$HOME/database/data_config/neo4j/data/backups"
DATABASE_NAME="neo4j"

# Load .env
if [ -f ".env" ]; then
    set -a
    source .env
    set +a

    if [ -z "${NEO4J_PASSWORD:-}" ]; then
        log_error "NEO4J_PASSWORD is empty in .env"
        exit 1
    fi
else
    log_error ".env file not found. Please create it with NEO4J_PASSWORD variable."
    exit 1
fi

NEO4J_BASE_DIR="$HOME/database/data_config/neo4j"
NEO4J_DATA_DIR="${NEO4J_BASE_DIR}/data"
NEO4J_LOGS_DIR="${NEO4J_BASE_DIR}/logs"
NEO4J_IMPORT_DIR="${NEO4J_BASE_DIR}/import"
NEO4J_PLUGINS_DIR="${NEO4J_BASE_DIR}/plugins"
NEO4J_CONF_DIR="${NEO4J_BASE_DIR}/conf"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper function for colored output
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Function: Start Neo4j
start_neo4j() {
    log_info "Starting Neo4j container..."
    
    if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        docker start ${CONTAINER_NAME}
        log_info "Neo4j container started"
    else
        log_info "Creating new Neo4j container..."
        # Create directories if they don't exist
        log_info "Creating data directories at: ${NEO4J_BASE_DIR}"
        mkdir -p "${NEO4J_DATA_DIR}" "${NEO4J_LOGS_DIR}" "${NEO4J_IMPORT_DIR}" "${NEO4J_PLUGINS_DIR}"

        docker run -d \
            --name ${CONTAINER_NAME} \
            --user=$(id -u):$(id -g) \
            --restart unless-stopped \
            -p 7245:7474 \
            -p 7269:7687 \
            -e NEO4J_AUTH=neo4j/${NEO4J_PASSWORD} \
            -e NEO4J_ACCEPT_LICENSE_AGREEMENT=yes \
            -e NEO4J_EDITION=ENTERPRISE \
            -e NEO4J_server_default__listen__address=0.0.0.0 \
            -e NEO4J_server_bolt_listen__address=0.0.0.0:7687 \
            -e NEO4J_server_http_listen__address=0.0.0.0:7474 \
            -e NEO4J_server_memory_pagecache_size=24G \
            -e NEO4J_server_memory_heap_initial__size=24G \
            -e NEO4J_server_memory_heap_max__size=24G \
            -e NEO4J_initial_dbms_default__database=${DATABASE_NAME} \
            -e NEO4J_PLUGINS='["apoc"]' \
            -e NEO4J_dbms_security_procedures_unrestricted="apoc.*" \
            -e NEO4J_dbms_security_procedures_allowlist="apoc.*" \
            -v "${NEO4J_DATA_DIR}:/data" \
            -v "${NEO4J_LOGS_DIR}:/logs" \
            -v "${NEO4J_IMPORT_DIR}:/var/lib/neo4j/import" \
            -v "${NEO4J_PLUGINS_DIR}:/plugins" \
            -v "${NEO4J_CONF_DIR}:/conf" \
            neo4j:${NEO4J_VERSION}
        
        log_info "Neo4j container created and started"
        log_info "Web interface: http://localhost:7245"
        log_info "Bolt connection: bolt://localhost:7269"
    fi
}

# Function: Stop Neo4j gracefully
stop_neo4j() {
    log_info "Stopping Neo4j container gracefully..."
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        docker stop ${CONTAINER_NAME}
        log_info "Neo4j container stopped"
    else
        log_warn "Neo4j container is not running"
    fi
}

# Function: Create dump file
# Following the 3-step process:
# 1. Stop database via cypher-shell
# 2. Dump database
# 3. Start database via cypher-shell
dump_database() {
    log_info "Creating database dump..."
    
    # Ensure backup directory exists
    mkdir -p "${BACKUP_DIR}"
    
    # Generate timestamp for backup file
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    DUMP_FILE="${DATABASE_NAME}_${TIMESTAMP}.dump"
    
    # Check if container is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        log_error "Neo4j container is not running. Please start it first."
        return 1
    fi
    
    # Step 1: Stop database
    log_info "Step 1: Stopping database '${DATABASE_NAME}' via cypher-shell..."
    docker exec -it ${CONTAINER_NAME} cypher-shell -u ${NEO4J_USER} -p ${NEO4J_PASSWORD} -d system "STOP DATABASE ${DATABASE_NAME};" || {
        log_error "Failed to stop database. It may already be stopped."
    }
    sleep 2
    
    # Step 2: Dump database
    log_info "Step 2: Dumping database '${DATABASE_NAME}' to ${DUMP_FILE}..."
    docker exec -it ${CONTAINER_NAME} neo4j-admin database dump ${DATABASE_NAME} --to-path=/data/backups/
    
    # Copy dump file to backup directory on host
    sudo docker cp ${CONTAINER_NAME}:/data/backups/${DATABASE_NAME}.dump \
        "${BACKUP_DIR}/${DUMP_FILE}"

    # Fix permissions
    sudo chown $(whoami):$(whoami) "${BACKUP_DIR}/${DUMP_FILE}"
    sudo chmod 644 "${BACKUP_DIR}/${DUMP_FILE}"
    
    # Step 3: Start database
    log_info "Step 3: Starting database '${DATABASE_NAME}' via cypher-shell..."
    docker exec -it ${CONTAINER_NAME} cypher-shell -u ${NEO4J_USER} -p ${NEO4J_PASSWORD} -d system "START DATABASE ${DATABASE_NAME};" || {
        log_error "Failed to start database"
        return 1
    }
    
    log_info "Dump created successfully: \"${BACKUP_DIR}/${DUMP_FILE}\""
    log_info "File size: $(du -h "${BACKUP_DIR}/${DUMP_FILE}" | cut -f1)"
    
    echo "${BACKUP_DIR}/${DUMP_FILE}"
}

# Function: Load dump file
# Following the 4-step process:
# 1. Move dump file to import directory
# 2. Stop database
# 3. Load the database dump
# 4. Start database
load_dump() {
    local DUMP_FILE=$1
    
    if [ -z "$DUMP_FILE" ]; then
        log_error "Usage: $0 load <dump-file>"
        log_error "Example: $0 load ./backups/neo4j_20251216.dump"
        return 1
    fi
    
    if [ ! -f "$DUMP_FILE" ]; then
        log_error "Dump file not found: $DUMP_FILE"
        return 1
    fi
    
    log_info "Loading dump file: $DUMP_FILE"
    
    # Check if container is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        log_error "Neo4j container is not running. Please start it first."
        return 1
    fi
    
    # Step 1: Move dump file to import directory
    log_info "Step 1: Copying dump file to import directory..."
    local DUMP_FILENAME=$(basename "$DUMP_FILE")
    sudo cp "$DUMP_FILE" "${NEO4J_IMPORT_DIR}/${DATABASE_NAME}.dump"
    sudo chmod 644 "${NEO4J_IMPORT_DIR}/${DATABASE_NAME}.dump"
    
    # Step 2: Stop database
    log_info "Step 2: Stopping database '${DATABASE_NAME}' via cypher-shell..."
    docker exec -it ${CONTAINER_NAME} cypher-shell -u ${NEO4J_USER} -p ${NEO4J_PASSWORD} -d system "STOP DATABASE ${DATABASE_NAME};" || {
        log_error "Failed to stop database. It may already be stopped."
    }
    sleep 2
    
    # Step 3: Load the database dump
    log_info "Step 3: Loading database dump (this may take a while)..."
    docker exec -it ${CONTAINER_NAME} neo4j-admin database load ${DATABASE_NAME} --from-path=/var/lib/neo4j/import --overwrite-destination=true
    
    if [ $? -ne 0 ]; then
        log_error "Failed to load database dump"
        log_info "Check logs with: $0 logs"
        return 1
    fi
    
    # Step 4: Start database
    log_info "Step 4: Starting database '${DATABASE_NAME}' via cypher-shell..."
    docker exec -it ${CONTAINER_NAME} cypher-shell -u ${NEO4J_USER} -p ${NEO4J_PASSWORD} -d system "START DATABASE ${DATABASE_NAME};" || {
        log_error "Failed to start database"
        return 1
    }
    
    log_info "Dump loaded successfully"
    log_info "Neo4j should be accessible at http://localhost:7245"
}

# Function: Empty Neo4j database and recreate
# Following the 5-step process:
# 1. Stop container
# 2. Remove database files
# 3. Start container
# 4. Recreate neo4j database
# 5. Restart container
empty_database() {
    log_warn "WARNING: This will permanently delete all data in the Neo4j database!"
    read -p "Are you sure you want to continue? (yes/no): " confirm
    
    if [ "$confirm" != "yes" ]; then
        log_info "Operation cancelled"
        return 0
    fi
    
    # Step 1: Stop container
    log_info "Step 1: Stopping Neo4j container..."
    docker stop ${CONTAINER_NAME}
    sleep 2
    
    # Step 2: Remove database files
    log_info "Step 2: Removing database files..."
    sudo rm -rf "${NEO4J_DATA_DIR}/databases/${DATABASE_NAME}"/*
    
    # Step 3: Start container
    log_info "Step 3: Starting Neo4j container..."
    docker start ${CONTAINER_NAME}
    sleep 10
    
    # Step 4: Recreate neo4j database
    log_info "Step 4: Recreating '${DATABASE_NAME}' database..."
    docker exec -it ${CONTAINER_NAME} cypher-shell -u ${NEO4J_USER} -p ${NEO4J_PASSWORD} -d system "CREATE DATABASE ${DATABASE_NAME};" || {
        log_warn "Database may already exist or creation failed"
    }
    sleep 2
    
    # Verify database creation
    log_info "Verifying database creation..."
    docker exec -it ${CONTAINER_NAME} cypher-shell -u ${NEO4J_USER} -p ${NEO4J_PASSWORD} -d system "SHOW DATABASES;"
    
    # Step 5: Restart container
    log_info "Step 5: Restarting Neo4j container..."
    docker restart ${CONTAINER_NAME}
    sleep 10
    
    log_info "Database emptied and recreated successfully"
    log_info "Neo4j should be accessible at http://localhost:7245"
}

# Function: Show Neo4j logs
show_logs() {
    local LINES=${1:-50}
    log_info "Showing last ${LINES} lines of Neo4j logs..."
    docker logs ${CONTAINER_NAME} --tail=${LINES}
}

# Function: Check database status
check_database_status() {
    log_info "Checking database status..."
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        log_error "Neo4j container is not running"
        return 1
    fi
    
    log_info "Connecting to system database..."
    docker exec -it ${CONTAINER_NAME} cypher-shell -u ${NEO4J_USER} -p ${NEO4J_PASSWORD} -d system "SHOW DATABASES;"
}

# Function: Fix permissions for docker configuration
fix_permissions() {
    log_info "Fixing permissions on Neo4j directories..."
    
    # Stop and remove container if exists
    if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        log_info "Stopping and removing existing container..."
        docker stop ${CONTAINER_NAME} 2>/dev/null || true
        docker rm ${CONTAINER_NAME} 2>/dev/null || true
    fi
    
    # Fix ownership
    log_info "Fixing ownership..."
    sudo chown -R $(id -u):$(id -g) "${NEO4J_DATA_DIR}"
    sudo chown -R $(id -u):$(id -g) "${NEO4J_LOGS_DIR}"
    sudo chown -R $(id -u):$(id -g) "${NEO4J_IMPORT_DIR}"
    sudo chown -R $(id -u):$(id -g) "${NEO4J_PLUGINS_DIR}"
    sudo chown -R $(id -u):$(id -g) "${NEO4J_CONF_DIR}"
    
    # Set proper permissions
    log_info "Setting permissions..."
    chmod -R 755 "${NEO4J_PLUGINS_DIR}"
    chmod -R 755 "${NEO4J_DATA_DIR}"
    chmod -R 755 "${NEO4J_LOGS_DIR}"
    chmod -R 755 "${NEO4J_IMPORT_DIR}"
    chmod -R 755 "${NEO4J_CONF_DIR}"
    
    log_info "Permissions fixed successfully"
    log_info "You can now run: $0 start"
}

# Function: Reset authentication
reset_auth() {
    log_warn "Resetting Neo4j authentication..."
    
    # Stop and remove container
    if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        log_info "Stopping and removing container..."
        docker stop ${CONTAINER_NAME} 2>/dev/null || true
        docker rm ${CONTAINER_NAME} 2>/dev/null || true
    fi
    
    # Remove auth files
    log_info "Removing authentication files..."
    sudo rm -rf "${NEO4J_DATA_DIR}/dbms/auth"*
    
    log_info "Authentication reset complete"
    log_info "Run '$0 start' to create a new container with fresh authentication"
}

# Function: Transfer dump to remote server
transfer_dump() {
    local DUMP_FILE=$1
    local REMOTE_HOST=$2
    local REMOTE_PATH=${3:-"$BACKUP_DIR"}
    
    if [ -z "$DUMP_FILE" ] || [ -z "$REMOTE_HOST" ]; then
        log_error "Usage: $0 transfer <dump-file> <remote-host> [remote-path]"
        log_error "Example: $0 transfer ./neo4j-backups/neo4j_20251212.dump.gz user@remote-server ~/backups"
        return 1
    fi
    
    if [ ! -f "$DUMP_FILE" ]; then
        log_error "Dump file not found: $DUMP_FILE"
        return 1
    fi
    
    log_info "Transferring $DUMP_FILE to ${REMOTE_HOST}:${REMOTE_PATH}"
    
    scp "$DUMP_FILE" "${REMOTE_HOST}:${REMOTE_PATH}/"
    
    log_info "Transfer completed successfully"
}

# Function: List backups
list_backups() {
    log_info "Available backups in ${BACKUP_DIR}:"
    if [ -d "$BACKUP_DIR" ]; then
        local found=false
        if ls "${BACKUP_DIR}"/*.dump.gz 2>/dev/null; then
            found=true
        fi
        if ls "${BACKUP_DIR}"/*.dump 2>/dev/null; then
            found=true
        fi
        if [ "$found" = false ]; then
            log_warn "No backups found"
        fi
    else
        log_warn "Backup directory does not exist"
    fi
}

# Function: Show status
status() {
    log_info "Neo4j Container Status:"
    docker ps -a --filter "name=${CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    
    echo ""
    log_info "Volume Information:"
    log_info "Data directory: ${NEO4J_DATA_DIR}"
    log_info "Logs directory: ${NEO4J_LOGS_DIR}"
    log_info "Import directory: ${NEO4J_IMPORT_DIR}"
    log_info "Plugins directory: ${NEO4J_PLUGINS_DIR}"
    
    echo ""
    list_backups
}

# Main command handler
case "${1:-}" in
    start)
        start_neo4j
        ;;
    stop)
        stop_neo4j
        ;;
    restart)
        stop_neo4j
        sleep 2
        start_neo4j
        ;;
    dump)
        dump_database
        ;;
    load)
        load_dump "$2"
        ;;
    empty)
        empty_database
        ;;
    logs)
        show_logs "$2"
        ;;
    check|check-status)
        check_database_status
        ;;
    fix-permissions)
        fix_permissions
        ;;
    reset-auth)
        reset_auth
        ;;
    transfer)
        transfer_dump "$2" "$3" "$4"
        ;;
    list)
        list_backups
        ;;
    status)
        status
        ;;
    *)
        echo "Neo4j Docker Management Script"
        echo ""
        echo "Usage: $0 {command} [options]"
        echo ""
        echo "Container Management:"
        echo "  start              - Start Neo4j container"
        echo "  stop               - Stop Neo4j container"
        echo "  restart            - Restart Neo4j container"
        echo ""
        echo "Backup & Restore:"
        echo "  dump               - Create database dump (3-step: stop DB, dump, start DB)"
        echo "  load <file>        - Load dump file into database (4-step process)"
        echo "  transfer <file> <host> [path] - Transfer dump to remote server"
        echo "  list               - List available backups"
        echo ""
        echo "Database Operations:"
        echo "  empty              - Empty database and recreate (WARNING: deletes all data!)"
        echo ""
        echo "Debug & Maintenance:"
        echo "  logs [lines]       - Show Neo4j logs (default: 50 lines)"
        echo "  check              - Check database status via cypher-shell"
        echo "  fix-permissions    - Fix directory permissions and ownership"
        echo "  reset-auth         - Reset Neo4j authentication"
        echo "  status             - Show container and backup status"
        echo ""
        echo "Examples:"
        echo "  $0 start"
        echo "  $0 dump"
        echo "  $0 load ./backups/neo4j_20251216.dump"
        echo "  $0 logs 100"
        echo "  $0 check"
        echo "  $0 empty"
        echo "  $0 fix-permissions"
        exit 1
        ;;
esac