#!/usr/bin/env python3
"""
Allora Network Submission Window Analysis
Comprehensive investigation of submission timing patterns
"""

import json
import subprocess
import time
from datetime import datetime, timezone

def query_allorad(args, timeout=20):
    """Query allorad with error handling"""
    cmd = ["allorad"] + args + ["--node", "https://allora-rpc.testnet.allora.network", "--output", "json"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return json.loads(result.stdout.strip())
        else:
            print(f"Error: {result.stderr}")
            return None
    except Exception as e:
        print(f"Query failed: {e}")
        return None

def analyze_submission_windows():
    """Analyze submission windows and timing"""
    print("=== ALLORA SUBMISSION WINDOW ANALYSIS ===\n")
    
    # Get current status
    status = query_allorad(["status"])
    if status:
        current_block = int(status["sync_info"]["latest_block_height"])
        block_time = status["sync_info"]["latest_block_time"]
        print(f"Current Block Height: {current_block}")
        print(f"Current Block Time: {block_time}")
    else:
        print("Failed to get status")
        return
    
    # Get topic 67 details
    topic_info = query_allorad(["q", "emissions", "topic", "67"])
    if topic_info:
        topic = topic_info["topic"]
        print(f"\n=== TOPIC 67 CONFIGURATION ===")
        print(f"ID: {topic['id']}")
        print(f"Metadata: {topic['metadata']}")
        print(f"Epoch Length: {topic['epoch_length']} blocks")
        print(f"Last Ended Epoch: {topic['epoch_last_ended']}")
        print(f"Ground Truth Lag: {topic['ground_truth_lag']} blocks")
        print(f"Worker Submission Window: {topic['worker_submission_window']} blocks")
        print(f"Effective Revenue: {topic_info.get('effective_revenue', 'N/A')}")
        print(f"Weight: {topic_info.get('weight', 'N/A')}")
        
        # Calculate timing
        epoch_length = int(topic["epoch_length"])
        last_epoch = int(topic["epoch_last_ended"])
        submission_window = int(topic["worker_submission_window"])
        ground_truth_lag = int(topic["ground_truth_lag"])
        
        # Current epoch calculation
        blocks_since_last_epoch = current_block - last_epoch
        current_epoch_progress = blocks_since_last_epoch % epoch_length
        next_epoch_start = last_epoch + ((blocks_since_last_epoch // epoch_length) + 1) * epoch_length
        
        print(f"\n=== TIMING ANALYSIS ===")
        print(f"Blocks since last epoch ended: {blocks_since_last_epoch}")
        print(f"Current epoch progress: {current_epoch_progress}/{epoch_length} blocks")
        print(f"Next epoch starts at block: {next_epoch_start}")
        print(f"Blocks until next epoch: {next_epoch_start - current_block}")
        
        # Submission window analysis
        submission_start = next_epoch_start - submission_window
        submission_end = next_epoch_start
        
        print(f"\n=== SUBMISSION WINDOW ANALYSIS ===")
        print(f"Submission window: {submission_window} blocks")
        print(f"Submission window starts at block: {submission_start}")
        print(f"Submission window ends at block: {submission_end}")
        
        if current_block >= submission_start and current_block < submission_end:
            print("🟢 CURRENTLY IN SUBMISSION WINDOW!")
            print(f"   Blocks remaining in window: {submission_end - current_block}")
        elif current_block < submission_start:
            print("🟡 Submission window not yet open")
            print(f"   Blocks until window opens: {submission_start - current_block}")
        else:
            print("🔴 Submission window has closed")
            print(f"   Blocks since window closed: {current_block - submission_end}")
        
        # Time estimates (assuming ~2.5s per block)
        block_time_seconds = 2.5
        if current_block < submission_start:
            time_until_window = (submission_start - current_block) * block_time_seconds
            print(f"   Estimated time until window opens: {time_until_window/60:.1f} minutes")
        elif current_block >= submission_start and current_block < submission_end:
            time_remaining = (submission_end - current_block) * block_time_seconds
            print(f"   Estimated time remaining in window: {time_remaining/60:.1f} minutes")
    
    # Check if topic is active
    active_check = query_allorad(["q", "emissions", "is-topic-active", "67"])
    if active_check:
        is_active = active_check.get("is_active", False)
        print(f"\n=== TOPIC STATUS ===")
        print(f"Topic 67 is active: {is_active}")
    
    # Get unfulfilled nonces
    unfulfilled_worker = query_allorad(["q", "emissions", "unfulfilled-worker-nonces", "67"])
    if unfulfilled_worker:
        worker_nonces = unfulfilled_worker.get("nonces", {})
        print(f"Unfulfilled worker nonces: {len(worker_nonces)}")
    
    unfulfilled_reputer = query_allorad(["q", "emissions", "unfulfilled-reputer-nonces", "67"])
    if unfulfilled_reputer:
        reputer_nonces = unfulfilled_reputer.get("nonces", [])
        print(f"Unfulfilled reputer nonces: {len(reputer_nonces)}")
        
        if reputer_nonces and isinstance(reputer_nonces, list):
            # Analyze reputer nonce pattern
            try:
                heights = [int(n["reputer_nonce"]["block_height"]) for n in reputer_nonces[-10:]]
                if len(heights) >= 2:
                    differences = [heights[i] - heights[i-1] for i in range(1, len(heights))]
                    avg_diff = sum(differences) / len(differences)
                    print(f"Average block difference between reputer nonces: {avg_diff:.1f}")
                    print(f"Recent reputer nonce heights: {heights[-5:]}")
            except (KeyError, TypeError, ValueError) as e:
                print(f"Could not analyze reputer nonces: {e}")

def monitor_submission_window(duration_minutes=10):
    """Monitor submission window status for a period"""
    print(f"\n=== MONITORING SUBMISSION WINDOW FOR {duration_minutes} MINUTES ===")
    
    start_time = time.time()
    end_time = start_time + (duration_minutes * 60)
    
    while time.time() < end_time:
        # Quick check
        status = query_allorad(["status"])
        if status:
            current_block = int(status["sync_info"]["latest_block_height"])
            block_time = status["sync_info"]["latest_block_time"]
            
            topic_info = query_allorad(["q", "emissions", "topic", "67"])
            if topic_info:
                topic = topic_info["topic"]
                epoch_length = int(topic["epoch_length"])
                last_epoch = int(topic["epoch_last_ended"])
                submission_window = int(topic["worker_submission_window"])
                
                blocks_since_last_epoch = current_block - last_epoch
                current_epoch_progress = blocks_since_last_epoch % epoch_length
                next_epoch_start = last_epoch + ((blocks_since_last_epoch // epoch_length) + 1) * epoch_length
                
                submission_start = next_epoch_start - submission_window
                submission_end = next_epoch_start
                
                status_emoji = "🔴"
                if current_block >= submission_start and current_block < submission_end:
                    status_emoji = "🟢"
                elif current_block < submission_start:
                    status_emoji = "🟡"
                
                print(f"{datetime.now().strftime('%H:%M:%S')} Block: {current_block} | Epoch: {current_epoch_progress}/{epoch_length} | Window: {submission_start}-{submission_end} {status_emoji}")
        
        time.sleep(30)  # Check every 30 seconds

if __name__ == "__main__":
    analyze_submission_windows()
    
    # Ask if user wants to monitor
    response = input("\nWould you like to monitor the submission window for 10 minutes? (y/n): ")
    if response.lower().startswith('y'):
        monitor_submission_window()