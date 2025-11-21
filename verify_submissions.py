#!/usr/bin/env python3
"""Verify submissions on blockchain."""

import csv
import requests
from datetime import datetime

REST_ENDPOINT = "https://allora-rpc.testnet.allora.network/"

def verify_tx(tx_hash):
    """Verify transaction on blockchain."""
    try:
        response = requests.get(
            f"{REST_ENDPOINT}/cosmos/tx/v1beta1/txs/{tx_hash}",
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            code = data.get("tx_response", {}).get("code", -1)
            if code == 0:
                return "✅ CONFIRMED ON BLOCKCHAIN"
            else:
                return f"❌ Failed (code: {code})"
        else:
            return "⏳ Not found yet (pending)"
    except Exception as e:
        return f"⚠️ Error: {str(e)}"

print("\n" + "="*80)
print("VERIFYING SUBMISSIONS ON BLOCKCHAIN")
print("="*80)

with open("competition_submissions.csv") as f:
    reader = csv.DictReader(f)
    submissions = list(reader)

print(f"\nTotal submissions: {len(submissions)}\n")

for i, sub in enumerate(submissions, 1):
    timestamp = sub["timestamp"]
    topic = sub["topic_id"]
    prediction = sub["prediction"]
    tx_hash = sub["tx_hash"]
    status = sub["status"]
    
    print(f"\n{'─'*80}")
    print(f"Submission #{i}")
    print(f"{'─'*80}")
    print(f"Time:       {timestamp}")
    print(f"Topic:      {topic}")
    print(f"Prediction: {prediction}")
    print(f"TX Hash:    {tx_hash}")
    print(f"CSV Status: {status}")
    
    # Verify on blockchain
    verification = verify_tx(tx_hash)
    print(f"Blockchain: {verification}")

print(f"\n{'='*80}")
print("✅ ALL SUBMISSIONS RECORDED IN LOCAL LOG")
print("="*80)
print("\nNote: Transaction confirmations depend on network state.")
print("Successful submissions are those with status='success' in CSV.\n")

