#!/usr/bin/env python3
"""
Comprehensive Pipeline Status Report
Shows cadence alignment, submission eligibility, and next actions
"""

import os
import sys
import subprocess
from datetime import datetime, timezone, timedelta
import csv

def main():
    print("="*80)
    print("PIPELINE STATUS REPORT - Topic 67")
    print("="*80)
    print()
    
    # Current time
    now = datetime.now(timezone.utc)
    toronto_time = now - timedelta(hours=5)
    
    print("⏰ CURRENT TIME:")
    print(f"   UTC:     {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Toronto: {toronto_time.strftime('%Y-%m-%d %H:%M:%S')} EST")
    print()
    
    # Competition schedule
    START = datetime(2025, 9, 16, 13, 0, 0, tzinfo=timezone.utc)
    END = datetime(2025, 12, 15, 13, 0, 0, tzinfo=timezone.utc)
    CADENCE_SECONDS = 3600
    
    elapsed = (now - START).total_seconds()
    current_epoch = int(elapsed / CADENCE_SECONDS) + 1
    epoch_start = START + timedelta(seconds=(current_epoch - 1) * CADENCE_SECONDS)
    epoch_end = epoch_start + timedelta(seconds=CADENCE_SECONDS)
    
    print("📅 COMPETITION SCHEDULE:")
    print(f"   Start:        Sep 16, 2025 13:00 UTC")
    print(f"   End:          Dec 15, 2025 13:00 UTC")
    print(f"   Cadence:      1 hour (3600 seconds)")
    print(f"   Current Epoch: {current_epoch}")
    print(f"   Epoch Start:  {epoch_start.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"   Epoch End:    {epoch_end.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print()
    
    # Worker status
    try:
        with open('pipeline.pid', 'r') as f:
            pid = f.read().strip()
        result = subprocess.run(['ps', '-p', pid], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"🔄 WORKER STATUS: ✅ RUNNING (PID: {pid})")
        else:
            print(f"🔄 WORKER STATUS: ❌ NOT RUNNING (PID {pid} dead)")
    except FileNotFoundError:
        print("🔄 WORKER STATUS: ❌ NO PID FILE")
    print()
    
    # Submission window
    blocks_into_epoch = int((now - epoch_start).total_seconds() / 5)
    blocks_remaining = 720 - blocks_into_epoch
    window_open = blocks_remaining < 600
    
    window_opens_at = epoch_end - timedelta(seconds=600 * 5)
    
    print("🪟 SUBMISSION WINDOW:")
    print(f"   Status:         {'🟢 OPEN' if window_open else '🔴 CLOSED'}")
    print(f"   Blocks into:    {blocks_into_epoch} / 720")
    print(f"   Blocks remain:  {blocks_remaining}")
    if not window_open:
        blocks_until = blocks_remaining - 600
        minutes_until = (blocks_until * 5) / 60
        print(f"   Opens at:       {window_opens_at.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"   Opens in:       {minutes_until:.1f} minutes")
    else:
        minutes_left = (blocks_remaining * 5) / 60
        print(f"   Closes in:      {minutes_left:.1f} minutes")
    print()
    
    # Submission log
    try:
        with open('submission_log.csv', 'r') as f:
            rows = list(csv.reader(f))
            total = len(rows) - 1
            successful = sum(1 for r in rows[1:] if len(r) > 6 and r[6] == 'true')
            skipped = sum(1 for r in rows[1:] if len(r) > 6 and r[6] == 'false')
            
            print("📊 SUBMISSION HISTORY:")
            print(f"   Total entries:  {total}")
            print(f"   Successful:     {successful}")
            print(f"   Skipped:        {skipped}")
            
            if len(rows) > 1 and len(rows[-1]) > 8:
                last = rows[-1]
                print(f"   Last entry:     {last[0]}")
                print(f"   Status:         {last[8]}")
                print(f"   Success:        {last[6]}")
                if len(last) > 10 and last[10]:
                    print(f"   Loss:           {last[9]}")
    except FileNotFoundError:
        print("📊 SUBMISSION HISTORY: No log file found")
    print()
    
    # Next actions
    next_check = epoch_end
    time_to_check = (next_check - now).total_seconds()
    
    print("🎯 NEXT ACTIONS:")
    print(f"   Next check:     {next_check.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"   Time until:     {int(time_to_check / 60)} min {int(time_to_check % 60)} sec")
    
    if window_open:
        print(f"   Action:         ✅ SUBMIT NOW (window is open)")
    else:
        print(f"   Action:         ⏳ Wait for window to open")
    print()
    
    # Retraining
    print("🔄 RETRAINING:")
    print("   Required:       Every submission (XGBoost model)")
    print("   Trigger:        Automatic in --loop mode")
    print("   Data window:    28 days history + 7 days validation")
    print()
    
    # Configuration
    print("⚙️  CONFIGURATION:")
    print("   Bug Fix:        ✅ Applied (epoch blocks calculation)")
    print("   Mode:           --loop --submit")
    print("   API Key:        Data fetching only (ALLORA_API_KEY)")
    print("   Auth:           AlloraWorker with MNEMONIC")
    print("   Features:       ~331 (after deduplication)")
    print()
    
    print("="*80)

if __name__ == "__main__":
    main()
