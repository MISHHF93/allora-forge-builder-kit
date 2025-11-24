#!/usr/bin/env python3
"""
ALLORA SUBMISSION PIPELINE: ENV & WALLET CONFIGURATION GUIDE
==============================================================

This guide addresses the three common configuration issues:
1. "Failed to create wallet from mnemonic: Invalid mnemonic length"
2. "Query failed and lookup allora-testnet-rpc.allthatnode.com: no such host"
3. RPC endpoint resolution and failover strategy

SECTION 1: MNEMONIC VALIDATION & WALLET CREATION
=================================================

Issue: "Failed to create wallet from mnemonic: Invalid mnemonic length"

Root Causes:
a) Mnemonic has wrong word count (not 12 or 24 words)
b) Mnemonic words are not in BIP39 word list
c) Mnemonic has extra whitespace or encoding issues
d) Copy-paste corruption (non-breaking spaces, special chars)

Validation Checklist:
✓ Count words: should be 12 or 24
✓ All words lowercase (BIP39 standard)
✓ No extra spaces between words (single space only)
✓ No special characters or Unicode
✓ Each word is in BIP39 word list

Example Valid Mnemonic (24 words):
tiger salmon health level chase shift type enough glue cliff rubber pitch alert arrest novel goose doll sweet tired carbon visit custom soul random

Format in .env:
MNEMONIC=tiger salmon health level chase shift type enough glue cliff rubber pitch alert arrest novel goose doll sweet tired carbon visit custom soul random

IMPORTANT: Do NOT use quotes around the mnemonic value in .env


SECTION 2: .ENV FILE PARSING
=============================

Issue: Environment variables not being read correctly

Common .env Format Errors:
❌ MNEMONIC="tiger salmon health..." (quoted - NO!)
❌ MNEMONIC='tiger salmon health...' (quoted - NO!)
❌ MNEMONIC = tiger salmon... (spaces around = sign)
❌ ALLORA_WALLET_ADDR = allo1... (spaces around = sign)
✅ MNEMONIC=tiger salmon health... (no quotes, no spaces around =)
✅ ALLORA_WALLET_ADDR=allo1... (no quotes, no spaces around =)

How dotenv.load_dotenv() Works:
1. Reads file line by line
2. Splits on first '=' character
3. Left side = variable name
4. Right side = value (with optional quotes stripped)
5. Whitespace matters: VAR=value not VAR = value

Loading in Code:
from dotenv import load_dotenv
import os

load_dotenv()  # Must be called before os.getenv()
mnemonic = os.getenv("MNEMONIC", "").strip()  # Strip is defensive
wallet = os.getenv("ALLORA_WALLET_ADDR", "").strip()


SECTION 3: RPC ENDPOINT CONFIGURATION & FAILOVER
=================================================

Issue: "Query failed and lookup allora-testnet-rpc.allthatnode.com: no such host"

Root Cause: DNS lookup failure OR endpoint temporarily down

The Allora testnet uses these RPC endpoints (in order of priority):

1. PRIMARY: https://allora-rpc.testnet.allora.network/
   - Official Allora testnet RPC
   - Most reliable
   - Recommended default

2. FALLBACK 1: https://allora-testnet-rpc.allthatnode.com:1317/
   - AllThatNode public RPC
   - Alternative if primary is down
   - May have stricter rate limits

3. FALLBACK 2: https://allora.api.chandrastation.com/
   - ChandraStation public RPC
   - Third-tier backup
   - Last resort

Fallover Strategy Implemented in submit_prediction.py:
=======================================================

1. Try Primary endpoint
2. On error: mark as failed, try AllThatNode
3. On error: mark as failed, try ChandraStation
4. On error: mark as failed, log warning, skip submission for this cycle
5. After all 3 endpoints fail, reset counters and retry next cycle

The daemon never stops—it gracefully skips submissions when all endpoints fail.

Testing Connectivity:
bash
# Test primary
curl -I https://allora-rpc.testnet.allora.network/

# Test fallback 1
curl -I https://allora-testnet-rpc.allthatnode.com:1317/

# Test fallback 2  
curl -I https://allora.api.chandrastation.com/


SECTION 4: TROUBLESHOOTING GUIDE
=================================

Symptom 1: "Invalid mnemonic length"
─────────────────────────────────
Step 1: Count words in your mnemonic
python3 -c "mnemonic='YOUR_MNEMONIC_HERE'; print(len(mnemonic.split()))"

Expected: 12 or 24
If not: Error is in mnemonic format

Step 2: Check for extra spaces
python3 -c "
mnemonic = '''YOUR_MNEMONIC_HERE'''
words = mnemonic.split()
print(f'Word count: {len(words)}')
print(f'Words: {words}')
"

Step 3: Verify each word is in BIP39 list
(Beyond scope here, but tools exist: pip install mnemonic)

Step 4: Try with test mnemonic (if you have one)
python3 -c "
from allora_sdk import LocalWallet
test_mnemonic = 'legal winner thank year wave sausage worth useful legal winner thank yellow'
wallet = LocalWallet.from_mnemonic(test_mnemonic)
print(f'Wallet created: {wallet.address}')
"


Symptom 2: "No such host" for RPC endpoint
──────────────────────────────────────
Step 1: Check DNS resolution
nslookup allora-rpc.testnet.allora.network
nslookup allora-testnet-rpc.allthatnode.com

Step 2: Try curl to endpoint
curl -v https://allora-rpc.testnet.allora.network/

Step 3: Check network connectivity
ping -c 3 8.8.8.8  # Google DNS

Step 4: Check AWS security groups (if on AWS)
- Ensure outbound HTTPS (443) is allowed
- Ensure outbound DNS (53) is allowed
- Run: netstat -an | grep ESTABLISHED

Step 5: Use primary endpoint as fallback in .env
RPC_URL=https://allora-rpc.testnet.allora.network/
RPC_ENDPOINT=grpc+https://allora-rpc.testnet.allora.network/


Symptom 3: Pipeline runs but says "No unfulfilled nonce"
───────────────────────────────────────
This is NOT an error—it's expected!

Explanation:
- Allora assigns nonces to worker wallets for each topic
- Nonce = "unfulfilled request waiting for prediction"
- If worker already submitted for all available nonces, next cycle skips
- This is normal, not a bug

What happens:
- Daemon queries unfulfilled nonces for topic 67
- Gets empty list (all nonces fulfilled)
- Logs: "No unfulfilled nonce available, skipping submission"
- Records in CSV: status=skipped_no_nonce
- Sleeps 1 hour
- Next cycle: new nonces may have arrived

Expected log line:
"⚠️  No unfulfilled nonce available, skipping submission"


SECTION 5: MINIMAL WORKING .env EXAMPLE
========================================

ALLORA_API_KEY=UP-YOUR_API_KEY_HERE
TIINGO_API_KEY=YOUR_TIINGO_API_KEY
ALLORA_WALLET_ADDR=allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma
TOPIC_ID=67
MNEMONIC=tiger salmon health level chase shift type enough glue cliff rubber pitch alert arrest novel goose doll sweet tired carbon visit custom soul random
RPC_URL=https://allora-rpc.testnet.allora.network/
CHAIN_ID=allora-testnet-1
RPC_ENDPOINT=grpc+https://allora-rpc.testnet.allora.network/
WEBSOCKET_ENDPOINT=wss://allora-rpc.testnet.allora.network/websocket
FAUCET_URL=https://faucet.testnet.allora.network
FEE_DENOM=uallo
FEE_MIN_GAS_PRICE=0.0001
LOG_PATH=logs/submission.log
SUBMISSION_INTERVAL=3600

Notes:
- Each line is: VARIABLE_NAME=value
- No spaces around =
- No quotes around values
- Values can have spaces (like mnemonic)
- Case-sensitive (use uppercase for env vars)


SECTION 6: VERIFICATION COMMANDS
=================================

# Run diagnostic script
python3 diagnose_env_wallet.py

# Test .env is loaded correctly
python3 -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('MNEMONIC'))"

# Test wallet creation
python3 -c "
from dotenv import load_dotenv
import os
from allora_sdk import LocalWallet

load_dotenv()
mnemonic = os.getenv('MNEMONIC')
wallet = LocalWallet.from_mnemonic(mnemonic)
print(f'✅ Wallet created: {wallet.address}')
"

# Test model loads
python3 -c "import pickle; m = pickle.load(open('model.pkl', 'rb')); print(f'Model: {type(m).__name__}')"

# Test features load
python3 -c "import json; f = json.load(open('features.json')); print(f'Features: {len(f)} columns')"

# Run single submission cycle (no nonce submission)
python3 submit_prediction.py --once

# Run with dry-run (simulate submission)
python3 submit_prediction.py --once --dry-run

# Run daemon
nohup python3 submit_prediction.py --daemon > logs/submission.log 2>&1 &


SECTION 7: COMPARISON: EXPECTED vs ACTUAL BEHAVIOR
====================================================

Expected Behavior (Correct Setup):
──────────────────────────────────
1. ✅ Daemon starts
2. ✅ Loads model and features
3. ✅ Fetches latest 168h BTC/USD data
4. ✅ Generates features
5. ✅ Runs prediction
6. ✅ Queries unfulfilled nonces
7. ✅ If nonce available: submits to blockchain
8. ✅ If no nonce: skips submission (normal)
9. ✅ Logs to CSV and JSON status files
10. ✅ Sleeps 1 hour
11. ✅ Repeats from step 2

CSV Entry (skipped):
2025-11-24T05:00:00.000245+00:00,67,-0.02522540,allo1...,0,,,skipped_no_nonce,,N/A

CSV Entry (successful):
2025-11-24T06:00:00.123456+00:00,67,-0.01234567,allo1...,123,{...},signature_here,success,tx_hash,Primary


Error Behavior (Incorrect Setup):
─────────────────────────────────
❌ "Failed to create wallet from mnemonic: Invalid mnemonic length"
   → Check mnemonic word count is 12 or 24
   → Check no extra whitespace
   → Verify mnemonic is in BIP39 word list

❌ "Query failed and lookup allora-testnet-rpc.allthatnode.com: no such host"
   → Check network connectivity
   → Check AWS security groups (if on AWS)
   → Check DNS resolution
   → Daemon will failover to next endpoint (retry)

❌ "MNEMONIC not set"
   → Check .env file exists
   → Check MNEMONIC line has correct format
   → Run: python3 -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('MNEMONIC'))"

❌ "ALLORA_WALLET_ADDR not set"
   → Check .env file has this line
   → Check format: ALLORA_WALLET_ADDR=allo1...
   → No quotes, no spaces around =


SUMMARY
=======

The three main issues you encountered:

1. Mnemonic validation:
   ✓ Must be 12 or 24 words
   ✓ Words separated by single spaces
   ✓ All words in BIP39 list
   ✓ No extra whitespace or special chars
   → Solution: Verify mnemonic with diagnose_env_wallet.py

2. .env file parsing:
   ✓ Format: VARIABLE_NAME=value
   ✓ No quotes around values
   ✓ No spaces around = sign
   ✓ Must call load_dotenv() before os.getenv()
   → Solution: Review .env file format against examples

3. RPC endpoints:
   ✓ Three endpoints configured with automatic failover
   ✓ Daemon continues if endpoints fail
   ✓ Next cycle retries automatically
   ✓ Gracefully skips submissions when all RPC fail
   → Solution: Built-in, no config needed

Run this to verify everything:
python3 diagnose_env_wallet.py

Then run the pipeline:
nohup python3 submit_prediction.py --daemon > logs/submission.log 2>&1 &

Monitor:
tail -f logs/submission.log
"""

if __name__ == "__main__":
    import subprocess
    import os
    
    # If run directly, run diagnostic
    if "diagnose" in os.path.basename(__file__):
        print(__doc__)
    else:
        # Run the diagnostic script
        result = subprocess.run([
            "python3", 
            os.path.join(os.path.dirname(__file__), "diagnose_env_wallet.py")
        ])
        exit(result.returncode)
