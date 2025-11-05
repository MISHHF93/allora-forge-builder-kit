#!/usr/bin/env python3
"""
Test script to verify score and reward retrieval functionality.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from train import _query_ema_score, _query_reward_for_tx

def test_score_retrieval():
    """Test the score retrieval for our wallet and topic."""
    topic_id = 67
    wallet = "allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"
    
    print(f"Testing score retrieval for Topic {topic_id}, Wallet {wallet}")
    print("-" * 60)
    
    # Test EMA score retrieval
    try:
        score = _query_ema_score(topic_id, wallet, retries=3, delay_s=2.0, timeout=20)
        print(f"EMA Score: {score}")
    except Exception as e:
        print(f"EMA Score retrieval failed: {e}")
    
    print()
    
    # Test reward retrieval for recent transactions
    recent_tx_hashes = [
        "39152047040EDB1492B27793ED575E11A2DB8A4E378E366014250FFAB7A5978B",
        "76258F098112B9E1E867B9F5D61A0016EE500EF679E11DE0D7C767417D8CF7CF"
    ]
    
    print("Testing reward retrieval for recent transactions:")
    for tx_hash in recent_tx_hashes:
        try:
            reward = _query_reward_for_tx(wallet, tx_hash, retries=3, delay_s=2.0, timeout=20)
            print(f"  TX {tx_hash[:16]}...: {reward}")
        except Exception as e:
            print(f"  TX {tx_hash[:16]}... failed: {e}")

if __name__ == "__main__":
    test_score_retrieval()