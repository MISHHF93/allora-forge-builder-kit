#!/bin/bash
# Robust launch script for autonomous Allora pipeline
# Monitors and restarts the pipeline if it fails

PIPELINE_CMD="python submit_prediction.py --continuous"
LOG_FILE="pipeline.log"
PID_FILE="pipeline.pid"

echo "Starting robust Allora pipeline..."

# Function to start pipeline
start_pipeline() {
    echo "Launching pipeline..."
    nohup $PIPELINE_CMD > $LOG_FILE 2>&1 &
    PID=$!
    echo $PID > $PID_FILE
    echo "Pipeline started with PID: $PID"
}

# Function to check if pipeline is running
is_running() {
    if [ -f $PID_FILE ]; then
        PID=$(cat $PID_FILE)
        if ps -p $PID > /dev/null; then
            return 0
        fi
    fi
    return 1
}

# Start pipeline
start_pipeline

# Monitor loop
while true; do
    if ! is_running; then
        echo "$(date): Pipeline not running, restarting..."
        start_pipeline
    fi
    sleep 60  # Check every minute
done &

MONITOR_PID=$!
echo "Monitor started with PID: $MONITOR_PID"

echo "Monitoring logs with tail -f submission_log.csv"
tail -f submission_log.csv &

echo "Monitoring system with htop"
htop