#!/bin/bash
#
# Allora Submission Daemon - Setup and Management Script
# Manages the long-lived prediction submission daemon until December 15, 2025
#
# Usage:
#   ./daemon_manager.sh start         - Start the daemon via systemd
#   ./daemon_manager.sh stop          - Stop the daemon
#   ./daemon_manager.sh restart       - Restart the daemon
#   ./daemon_manager.sh status        - Check daemon status
#   ./daemon_manager.sh logs          - Follow live logs
#   ./daemon_manager.sh install       - Install systemd unit file
#   ./daemon_manager.sh supervisord   - Run via supervisord instead
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="allora-submission"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SUPERVISOR_CONF="$SCRIPT_DIR/supervisord.conf"
LOG_DIR="$SCRIPT_DIR/logs"
SUBMISSION_LOG="$SCRIPT_DIR/logs/submission.log"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

print_header() {
    echo "========================================================================="
    echo "$1"
    echo "========================================================================="
}

check_requirements() {
    echo "Checking requirements..."
    
    # Check Python venv
    if [ ! -d "$SCRIPT_DIR/.venv" ]; then
        echo "❌ Python virtual environment not found at $SCRIPT_DIR/.venv"
        echo "   Run: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
        return 1
    fi
    
    # Check critical files
    if [ ! -f "$SCRIPT_DIR/submit_prediction.py" ]; then
        echo "❌ submit_prediction.py not found"
        return 1
    fi
    
    if [ ! -f "$SCRIPT_DIR/model.pkl" ]; then
        echo "❌ model.pkl not found - run 'python train.py' first"
        return 1
    fi
    
    if [ ! -f "$SCRIPT_DIR/features.json" ]; then
        echo "❌ features.json not found - run 'python train.py' first"
        return 1
    fi
    
    # Check environment variables
    if [ -z "$ALLORA_WALLET_ADDR" ]; then
        echo "❌ ALLORA_WALLET_ADDR not set"
        return 1
    fi
    
    if [ -z "$MNEMONIC" ]; then
        echo "❌ MNEMONIC not set"
        return 1
    fi
    
    echo "✅ All requirements met"
    return 0
}

install_systemd() {
    print_header "Installing systemd unit file"
    
    if ! check_requirements; then
        return 1
    fi
    
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then
        echo "❌ Must run as root (use: sudo ./daemon_manager.sh install)"
        return 1
    fi
    
    # Copy service file
    echo "Copying service file to $SERVICE_FILE..."
    cp "$SCRIPT_DIR/allora-submission.service" "$SERVICE_FILE"
    chmod 644 "$SERVICE_FILE"
    
    # Reload systemd
    echo "Reloading systemd daemon..."
    systemctl daemon-reload
    
    echo "✅ Systemd unit installed"
    echo "   Start with: sudo systemctl start $SERVICE_NAME"
    echo "   Enable at boot: sudo systemctl enable $SERVICE_NAME"
    echo "   Check status: sudo systemctl status $SERVICE_NAME"
    echo "   View logs: sudo journalctl -u $SERVICE_NAME -f"
}

start_systemd() {
    print_header "Starting submission daemon via systemd"
    
    if ! check_requirements; then
        return 1
    fi
    
    if [ "$EUID" -ne 0 ]; then
        echo "❌ Must run as root (use: sudo ./daemon_manager.sh start)"
        return 1
    fi
    
    systemctl start "$SERVICE_NAME"
    sleep 1
    systemctl status "$SERVICE_NAME"
}

stop_systemd() {
    print_header "Stopping submission daemon"
    
    if [ "$EUID" -ne 0 ]; then
        echo "❌ Must run as root (use: sudo ./daemon_manager.sh stop)"
        return 1
    fi
    
    systemctl stop "$SERVICE_NAME"
    echo "✅ Daemon stopped"
}

restart_systemd() {
    print_header "Restarting submission daemon"
    
    if [ "$EUID" -ne 0 ]; then
        echo "❌ Must run as root (use: sudo ./daemon_manager.sh restart)"
        return 1
    fi
    
    systemctl restart "$SERVICE_NAME"
    sleep 1
    systemctl status "$SERVICE_NAME"
}

status_systemd() {
    print_header "Submission daemon status"
    systemctl status "$SERVICE_NAME" || true
}

enable_boot() {
    print_header "Enabling daemon at system boot"
    
    if [ "$EUID" -ne 0 ]; then
        echo "❌ Must run as root"
        return 1
    fi
    
    systemctl enable "$SERVICE_NAME"
    echo "✅ Daemon will auto-start on system reboot"
}

follow_logs() {
    print_header "Following submission logs (Ctrl+C to exit)"
    echo "Switching to journalctl for systemd logs..."
    
    if [ "$EUID" -ne 0 ]; then
        echo "Trying without sudo (may have limited output)..."
        journalctl -u "$SERVICE_NAME" -f || tail -f "$SUBMISSION_LOG"
    else
        journalctl -u "$SERVICE_NAME" -f
    fi
}

start_supervisord() {
    print_header "Starting daemon via supervisord"
    
    if ! check_requirements; then
        return 1
    fi
    
    if ! command -v supervisord &> /dev/null; then
        echo "❌ supervisord not found. Install with: pip install supervisor"
        return 1
    fi
    
    echo "Starting supervisord with config: $SUPERVISOR_CONF"
    supervisord -c "$SUPERVISOR_CONF"
    
    sleep 2
    echo "Starting submission program..."
    supervisorctl -c "$SUPERVISOR_CONF" start allora-submission
    
    echo "✅ Daemon started via supervisord"
    echo "   Check status: supervisorctl -c $SUPERVISOR_CONF status"
    echo "   Tail logs: supervisorctl -c $SUPERVISOR_CONF tail allora-submission"
}

# Health check
health_check() {
    print_header "Daemon health check"
    
    echo "1. Checking submission log for recent activity..."
    if [ -f "$SUBMISSION_LOG" ]; then
        echo "Last 5 log entries:"
        tail -5 "$SUBMISSION_LOG" || echo "  (log file empty)"
    else
        echo "❌ Submission log not found"
        return 1
    fi
    
    echo ""
    echo "2. Checking for running process..."
    if pgrep -f "submit_prediction.py --continuous" > /dev/null; then
        echo "✅ submit_prediction.py process is running"
        pgrep -f "submit_prediction.py --continuous"
    else
        echo "❌ submit_prediction.py process not found"
    fi
    
    echo ""
    echo "3. Checking submission CSV..."
    if [ -f "$SCRIPT_DIR/submission_log.csv" ]; then
        lines=$(wc -l < "$SCRIPT_DIR/submission_log.csv")
        echo "✅ $lines lines in submission_log.csv"
        tail -1 "$SCRIPT_DIR/submission_log.csv" || echo "  (empty)"
    else
        echo "ℹ️  submission_log.csv not yet created"
    fi
}

# Main dispatcher
case "${1:-status}" in
    install)
        install_systemd
        ;;
    start)
        start_systemd
        ;;
    stop)
        stop_systemd
        ;;
    restart)
        restart_systemd
        ;;
    status)
        status_systemd
        ;;
    logs)
        follow_logs
        ;;
    enable)
        enable_boot
        ;;
    health)
        health_check
        ;;
    supervisord)
        start_supervisord
        ;;
    *)
        echo "Allora Submission Daemon Manager"
        echo ""
        echo "Usage: $0 {install|start|stop|restart|status|logs|enable|health|supervisord}"
        echo ""
        echo "Commands:"
        echo "  install              Install systemd unit file (requires sudo)"
        echo "  start                Start the daemon (requires sudo)"
        echo "  stop                 Stop the daemon (requires sudo)"
        echo "  restart              Restart the daemon (requires sudo)"
        echo "  status               Show daemon status"
        echo "  logs                 Follow live submission logs"
        echo "  enable               Enable auto-start on system boot (requires sudo)"
        echo "  health               Check daemon health and recent activity"
        echo "  supervisord          Start daemon via supervisord (alternative to systemd)"
        echo ""
        echo "Examples:"
        echo "  # Install and start via systemd:"
        echo "  sudo ./daemon_manager.sh install"
        echo "  sudo ./daemon_manager.sh start"
        echo "  sudo ./daemon_manager.sh enable"
        echo ""
        echo "  # Monitor with logs:"
        echo "  ./daemon_manager.sh logs"
        echo "  ./daemon_manager.sh health"
        echo ""
        echo "  # Alternative: use supervisord"
        echo "  ./daemon_manager.sh supervisord"
        exit 0
        ;;
esac
