#!/bin/bash
# Allora Forge Kit Daemon Management Script

DAEMON_SCRIPT="daemon.py"
PID_FILE="daemon.pid"
LOG_FILE="logs/daemon.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

check_pid() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            return 0  # Process is running
        else
            warning "PID file exists but process $PID is not running. Cleaning up."
            rm -f "$PID_FILE"
            return 1  # Process not running
        fi
    else
        return 1  # No PID file
    fi
}

start_daemon() {
    log "Starting Allora Forge Kit Daemon..."

    # Check if already running
    if check_pid; then
        PID=$(cat "$PID_FILE")
        error "Daemon is already running (PID: $PID)"
        exit 1
    fi

    # Start the daemon
    nohup python "$DAEMON_SCRIPT" > /dev/null 2>&1 &
    DAEMON_PID=$!

    # Wait a moment for startup
    sleep 2

    # Check if process is still running
    if ps -p "$DAEMON_PID" > /dev/null 2>&1; then
        echo $DAEMON_PID > "$PID_FILE"
        success "Daemon started successfully (PID: $DAEMON_PID)"
        log "Log file: $LOG_FILE"
        log "PID file: $PID_FILE"
    else
        error "Failed to start daemon"
        exit 1
    fi
}

stop_daemon() {
    log "Stopping Allora Forge Kit Daemon..."

    if ! check_pid; then
        warning "Daemon is not running"
        return
    fi

    PID=$(cat "$PID_FILE")
    log "Sending SIGTERM to process $PID..."

    # Send SIGTERM first
    kill -TERM "$PID"

    # Wait up to 30 seconds for graceful shutdown
    for i in {1..30}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            success "Daemon stopped gracefully"
            rm -f "$PID_FILE"
            return
        fi
        sleep 1
    done

    # Force kill if still running
    warning "Daemon didn't stop gracefully, sending SIGKILL..."
    kill -KILL "$PID" 2>/dev/null
    sleep 1

    if ! ps -p "$PID" > /dev/null 2>&1; then
        success "Daemon force-killed"
    else
        error "Failed to kill daemon process"
    fi

    rm -f "$PID_FILE"
}

status_daemon() {
    if check_pid; then
        PID=$(cat "$PID_FILE")
        success "Daemon is running (PID: $PID)"

        # Show recent log entries
        if [ -f "$LOG_FILE" ]; then
            echo ""
            echo "Recent log entries:"
            tail -10 "$LOG_FILE" | sed 's/^/  /'
        fi
    else
        warning "Daemon is not running"
    fi
}

restart_daemon() {
    log "Restarting Allora Forge Kit Daemon..."
    stop_daemon
    sleep 2
    start_daemon
}

show_help() {
    echo "Allora Forge Kit Daemon Management Script"
    echo ""
    echo "Usage: $0 {start|stop|restart|status}"
    echo ""
    echo "Commands:"
    echo "  start   - Start the daemon"
    echo "  stop    - Stop the daemon gracefully"
    echo "  restart - Restart the daemon"
    echo "  status  - Show daemon status and recent logs"
    echo ""
    echo "Files:"
    echo "  Daemon script: $DAEMON_SCRIPT"
    echo "  PID file: $PID_FILE"
    echo "  Log file: $LOG_FILE"
}

# Main script logic
case "${1:-}" in
    start)
        start_daemon
        ;;
    stop)
        stop_daemon
        ;;
    restart)
        restart_daemon
        ;;
    status)
        status_daemon
        ;;
    *)
        show_help
        exit 1
        ;;
esac