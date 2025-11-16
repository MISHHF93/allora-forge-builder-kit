#!/bin/bash
echo "=== CONTINUOUS LOOP STATUS ==="
echo ""
echo "Process Status:"
ps aux | grep "train.py --loop" | grep -v grep | awk '{print "  PID: "$2", CPU: "$3"%, MEM: "$4"%, Runtime: "$10}'
echo ""
echo "Last 5 Log Entries:"
tail -5 pipeline_run.log | sed 's/^/  /'
echo ""
echo "Submission History:"
tail -3 submission_log.csv | column -t -s, | sed 's/^/  /'
echo ""
echo "Next scheduled run: Check pipeline_run.log for alignment message"
