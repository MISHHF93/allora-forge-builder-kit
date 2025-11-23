# 🚀 RPC Failover & Leaderboard Submission Quick Reference

**Last Updated**: November 23, 2025  
**Status**: ✅ Active & Monitoring

---

## 📊 Quick Status Check

```bash
# Check latest submission status
cat latest_submission.json | jq '{timestamp: .timestamp, status: .status, tx_hash: .tx_hash, rpc: .rpc_endpoint}'

# Count successful submissions in CSV
grep -c '"success' submission_log.csv

# View recent submission errors
grep "ERROR\|FAILED" logs/submission.log | tail -10

# Check RPC endpoint health (from logs)
grep "RPC ENDPOINT HEALTH REPORT" -A 5 logs/submission.log | tail -7
```

**Output Example**:
```json
{
  "timestamp": "2025-11-23T04:10:16.981583+00:00",
  "status": "success",
  "tx_hash": "FD1A2B3C4D5E6F...",
  "rpc": "Primary"
}
```

---

## 🔄 RPC Endpoints Configuration

**Primary** (Official Allora Testnet)
- URL: https://allora-rpc.testnet.allora.network/
- Type: Full node
- Status: ✅ Active

**Fallback #1** (AllThatNode)
- URL: https://allora-testnet-rpc.allthatnode.com:1317/
- Type: RPC provider
- Status: ⚠️ Monitor (if failing, disable)

**Fallback #2** (ChandraStation)
- URL: https://allora.api.chandrastation.com/
- Type: RPC provider
- Status: ⚠️ Monitor (if failing, disable)

---

## 🔧 How RPC Failover Works

1. **Query Attempt #1**: Primary endpoint
   ```
   → Success? ✅ Use it, continue
   → Failure? ❌ Mark as failed (1/3), try next
   ```

2. **Query Attempt #2**: Fallback #1
   ```
   → Success? ✅ Use it, reset Primary's failure count
   → Failure? ❌ Mark as failed (1/3), try next
   ```

3. **Query Attempt #3**: Fallback #2
   ```
   → Success? ✅ Use it, reset others' failure counts
   → Failure? ❌ Mark as failed (1/3), reset all
   ```

4. **Cycle Complete**: Loop restarts with Primary

**Failure Limits**: Each endpoint gets 3 failures before being permanently skipped until reset

**Reset Trigger**: All endpoints exhausted → Reset failure counts to 0 → Start over

---

## 📝 CSV Submission Log Format

**File**: `submission_log.csv`

**10 Columns**:
```
Timestamp    | ISO 8601 timestamp of submission attempt
Topic ID     | Should always be 67 (BTC/USD 7-day)
Prediction   | Log-return value (-1.0 to +1.0 range typical)
Worker       | Wallet address (allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma)
Block Height | Unfulfilled nonce block height
Proof        | JSON-serialized inference proof
Signature    | Base64-encoded bundle signature
Status       | Result code (success, failed_no_nonce, cli_error, etc)
TX Hash      | Transaction hash if submitted (else empty)
RPC Endpoint | Which endpoint was used (Primary, AllThatNode, ChandraStation)
```

**Query Examples**:
```bash
# Find all successful submissions
grep "success" submission_log.csv

# Find all failures
grep "failed\|error\|ERROR" submission_log.csv

# Count by RPC endpoint
cut -d',' -f10 submission_log.csv | sort | uniq -c

# Show last 5 submissions
tail -5 submission_log.csv
```

---

## 🎯 Status Codes

### Success Codes
- `success` - Submitted successfully, standard status
- `success_confirmed` - Submitted AND confirmed on-chain
- `success_pending_confirmation` - Submitted, awaiting confirmation

### Failure Codes
- `failed_no_nonce` - No unfulfilled nonce available (not a failure, expected)
- `failed_no_sequence` - Cannot get account sequence from chain
- `failed_invalid_response` - RPC returned invalid JSON/HTML
- `cli_error: <reason>` - CLI submission failed with error
- `error: submission_timeout` - Submission timed out (120s)
- `error: <exception>` - Unexpected error during submission

### RPC Endpoint Failures
- `RPC endpoint marked failed: {endpoint_name}` - Endpoint exceeded 3 failures
- Response codes: `INVALID_JSON`, `CLI_ERROR`, `TIMEOUT`

---

## 💻 Daemon Command Reference

**Start daemon**:
```bash
python submit_prediction.py --daemon
```

**Or with nohup** (survives terminal close):
```bash
nohup python submit_prediction.py --daemon > /tmp/daemon.log 2>&1 &
```

**Monitor live**:
```bash
tail -f logs/submission.log
```

**Check process**:
```bash
ps aux | grep submit_prediction.py
```

**Graceful shutdown**:
```bash
pkill -SIGTERM -f "submit_prediction.py --daemon"
```

**Force kill** (emergency only):
```bash
pkill -9 -f submit_prediction.py
```

---

## 🔍 Transaction Verification

**Get latest transaction hash**:
```bash
cat latest_submission.json | jq -r .tx_hash
```

**Query on-chain** (using RPC REST API):
```bash
curl https://allora-rpc.testnet.allora.network/cosmos/tx/v1beta1/txs/{TX_HASH}
```

**Expected response**:
```json
{
  "tx": {
    "body": {
      "messages": [
        {
          "@type": "/allora.emissions.v1.MsgInsertWorkerPayload",
          "sender": "allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma",
          "worker_data": {...}
        }
      ]
    }
  },
  "tx_response": {
    "code": 0,  ← Should be 0 for success
    "txhash": "FD1A2B3C...",
    "height": "6645115"
  }
}
```

**Verify**:
- ✅ `code` == 0 (success)
- ✅ `txhash` matches your tx_hash
- ✅ `sender` matches your wallet address
- ✅ Message type is `MsgInsertWorkerPayload`

---

## 🧪 Testing RPC Endpoints Directly

**Test Primary Endpoint**:
```bash
curl -s https://allora-rpc.testnet.allora.network/status | jq '.result.node_info | {id, listen_addr, version}'
```

**Expected**: JSON response with node info, not HTML error

**Test Account Sequence Query** (requires allorad CLI):
```bash
allorad query auth account allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma \
  --node https://allora-rpc.testnet.allora.network/ \
  --output json
```

**Expected**: JSON with account sequence number

**Test Unfulfilled Nonce Query**:
```bash
allorad query emissions unfulfilled-worker-nonces 67 \
  --node https://allora-rpc.testnet.allora.network/ \
  --output json
```

**Expected**: JSON list of unfulfilled nonces (or empty array if all fulfilled)

---

## 📈 Performance Metrics

**Track these over time**:

```bash
# Success rate
SUCCESS=$(grep -c "success" submission_log.csv)
TOTAL=$(grep -c "^2025" submission_log.csv)
echo "Success rate: $(( SUCCESS * 100 / TOTAL ))%"

# Most used RPC endpoint
echo "Most used endpoint:"
cut -d',' -f10 submission_log.csv | sort | uniq -c | sort -rn | head -1

# Failures by type
echo "Failures by type:"
grep "^2025" submission_log.csv | grep -v "success" | cut -d',' -f8 | sort | uniq -c

# Average response time (from logs)
grep "Submitting via" logs/submission.log | wc -l
```

---

## 🚨 Alert Conditions

**⚠️ Check immediately if you see**:

1. **All RPC endpoints marked failed**
   ```
   ❌ Resetting failed RPC endpoints - all exceeded retry limit
   ```
   → RPC endpoints unreachable, possible network outage
   → Solution: Check endpoint status, switch to manual testing

2. **Invalid JSON responses**
   ```
   ❌ Received HTML response instead of JSON
   ❌ Empty response received
   ```
   → RPC endpoint returning error page, likely down
   → Solution: Endpoint will auto-failover, monitor if persists

3. **No submissions for 2+ hours**
   ```
   (No SUBMISSION CYCLE or HEARTBEAT in logs for 2+ hours)
   ```
   → Daemon may have crashed or hung
   → Solution: Check process status, restart if needed

4. **Wallet or mnemonic errors**
   ```
   ❌ ALLORA_WALLET_ADDR not set
   ❌ Failed to create wallet from mnemonic
   ```
   → Environment variables missing or corrupted
   → Solution: Verify .env file, restart daemon

5. **Model validation failures**
   ```
   ❌ CRITICAL: Model validation failed. Cannot proceed with submission.
   ```
   → Model corrupted or incompatible
   → Solution: Retrain with `python train.py`

---

## 📊 Leaderboard Update Verification

**Manual check procedure**:

1. **Get latest submission hash**:
   ```bash
   TX=$(cat latest_submission.json | jq -r .tx_hash)
   echo $TX
   ```

2. **Query on Allora chain**:
   ```bash
   curl -s https://allora-rpc.testnet.allora.network/cosmos/tx/v1beta1/txs/$TX | jq .tx_response.code
   ```
   → Should return `0` (success)

3. **Extract prediction from transaction**:
   ```bash
   curl -s https://allora-rpc.testnet.allora.network/cosmos/tx/v1beta1/txs/$TX | jq '.tx_response | {height, txhash, code}'
   ```

4. **Visit leaderboard**:
   - URL: https://app.allora.network/leaderboard/prediction-market-btcusd
   - Find your wallet: `allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma`
   - Verify score reflects recent submission timestamp

5. **If not updated**:
   - Hard refresh: `Ctrl+F5` (Windows) or `Cmd+Shift+R` (Mac)
   - Wait 5 minutes (leaderboard may cache)
   - Check if transaction code was 0 (success)
   - Verify topic_id is 67 in submission logs

---

## 🔐 Security Notes

- **Never commit mnemonic** - Use .env file only
- **Rotate wallet regularly** - If compromised, create new one
- **Monitor gas spending** - Check transaction fees in logs
- **Whitelist RPC endpoints** - Only use official/trusted providers
- **Audit CSV logs** - Verify all submissions match on-chain records

---

## 📞 Support Checklist

If daemon isn't working, verify in order:

- [ ] Daemon process running: `ps aux | grep submit_prediction.py`
- [ ] Recent logs exist: `ls -lh logs/submission.log`
- [ ] Model file exists: `ls -lh model.pkl`
- [ ] Features file exists: `ls -lh features.json`
- [ ] Environment set: `echo $ALLORA_WALLET_ADDR`
- [ ] RPC reachable: `curl https://allora-rpc.testnet.allora.network/status`
- [ ] CLI available: `which allorad` or `which allora`
- [ ] Recent CSV entry: `tail -1 submission_log.csv`
- [ ] Heartbeat in logs: `grep HEARTBEAT logs/submission.log | tail -1`
- [ ] No ERROR in recent logs: `grep ERROR logs/submission.log | tail -5`

---

## 🎯 Expected Behavior Timeline

**Minute 0**: Daemon starts, loads config
**Minute 1**: First heartbeat
**Minute 2-5**: Fetch data, generate features, predict
**Minute 5-10**: Submit to chain via Primary RPC
**Minute 10**: Log to CSV, update latest_submission.json
**Minute 11-60**: Sleep/wait
**Minute 60**: Second heartbeat (every hour)
**Hour 1-3**: Next submission cycle (hourly)
**Dec 15, 2025 00:00:00 UTC**: Automatic shutdown

---

**Questions?** Check logs at `logs/submission.log` or run status commands above.

**Status**: ✅ PRODUCTION READY - Monitor and enjoy your submissions!
