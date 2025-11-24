# RPC Endpoints Configuration - Quick Reference

## What Changed
✅ RPC endpoints now configurable as a **list** (not hardcoded)  
✅ Supports **2 formats**: comma-separated or JSON array  
✅ **Automatic fallback** to 3 hardcoded defaults  

## Current Configuration

```dotenv
RPC_ENDPOINTS=https://allora-rpc.testnet.allora.network/,https://allora-testnet-rpc.allthatnode.com:1317/,https://allora.api.chandrastation.com/
```

✅ **Status**: 3 endpoints configured (comma-separated)

---

## How to Configure

### Option 1: Comma-Separated (Simplest) ✅ RECOMMENDED
```dotenv
RPC_ENDPOINTS=https://endpoint1.com/,https://endpoint2.com/,https://endpoint3.com/
```

### Option 2: JSON Array Format
```dotenv
RPC_ENDPOINTS=["https://endpoint1.com/","https://endpoint2.com/","https://endpoint3.com/"]
```

### Option 3: Use Hardcoded Defaults (Do Nothing)
```dotenv
# Just don't set RPC_ENDPOINTS - code uses 3 built-in defaults
```

---

## URL Format Rules

✅ **Must be HTTPS**  
✅ **Must end with** `/` (auto-added if missing)  
✅ **Port numbers OK**: `https://example.com:1317/`  

---

## How Failover Works

```
Request 1: Endpoint-1 ✅
Request 2: Endpoint-2 (round-robin)
Request 3: If Endpoint-1 fails → skip it
After 3 failures per endpoint → disable it
All endpoints disabled → reset & try again
```

---

## Verify Configuration

```bash
# Test endpoints
python3 diagnose_env_wallet.py

# Should show:
# ✅ Loaded 3 RPC endpoints from .env (comma-separated)
# ✅ Custom-1: Responsive (200)
# etc.
```

---

## Change Endpoints

```bash
# 1. Stop daemon
pkill -f "submit_prediction.py --daemon"

# 2. Edit .env
nano .env

# 3. Update RPC_ENDPOINTS line
# 4. Restart daemon
nohup python3 submit_prediction.py --daemon > logs/submission.log 2>&1 &

# 5. Verify
python3 diagnose_env_wallet.py
```

---

## Check RPC Usage in Logs

```bash
# See which endpoints loaded
tail logs/submission.log | grep "RPC endpoints"

# Monitor failures
tail -f logs/submission.log | grep "endpoint"

# Count failures
grep "marked failed" logs/submission.log | wc -l
```

---

## Common Issues

**Q: "All RPC endpoints exceeded retry limit"**  
A: All 3 endpoints failed 3 times. Check connectivity:
```bash
curl -I https://allora-rpc.testnet.allora.network/
```

**Q: RPC_ENDPOINTS not being loaded?**  
A: Verify format:
```bash
grep "RPC_ENDPOINTS" .env
python3 diagnose_env_wallet.py
```

**Q: Want to add more endpoints?**  
A: Just add to comma-separated list:
```dotenv
RPC_ENDPOINTS=https://ep1/,https://ep2/,https://ep3/,https://ep4/
```

---

## Files Modified

| File | Change |
|------|--------|
| `submit_prediction.py` | Load RPC endpoints from .env |
| `.env` | Added RPC_ENDPOINTS variable |
| `diagnose_env_wallet.py` | Display RPC endpoints info |
| `RPC_CONFIGURATION_GUIDE.md` | Full configuration guide |
| `RPC_ENHANCEMENT_SUMMARY.md` | Detailed change summary |

---

## Testing

```bash
# Test diagnostic
python3 diagnose_env_wallet.py

# Test single submission
python3 submit_prediction.py --once

# Verify daemon still works
ps aux | grep "submit_prediction.*daemon"
tail -20 logs/submission.log
```

---

## Status: ✅ PRODUCTION READY

- RPC endpoints configurable via `.env`
- Automatic failover working
- Fallback to defaults if none specified
- Backward compatible (no breaking changes)
- Enhanced logging for debugging
- Diagnostic tool shows endpoint status

---

For detailed guide: See `RPC_CONFIGURATION_GUIDE.md`  
For change details: See `RPC_ENHANCEMENT_SUMMARY.md`
