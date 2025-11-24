# RPC Endpoint Configuration Guide

## Overview

Your Allora daemon now supports **flexible RPC endpoint configuration** with automatic failover, allowing you to use custom endpoints or leverage the built-in defaults.

## Configuration Methods

### Method 1: Comma-Separated List (Recommended)

Add to `.env`:

```dotenv
RPC_ENDPOINTS=https://endpoint1.com/,https://endpoint2.com/,https://endpoint3.com/
```

**Features:**
- ✅ Simple and readable
- ✅ Easy to add/remove endpoints
- ✅ Automatic failover between endpoints
- ✅ No JSON parsing required

**Example:**

```dotenv
RPC_ENDPOINTS=https://allora-rpc.testnet.allora.network/,https://allora-testnet-rpc.allthatnode.com:1317/,https://allora.api.chandrastation.com/
```

### Method 2: JSON Array Format

Add to `.env`:

```dotenv
RPC_ENDPOINTS=["https://endpoint1.com/","https://endpoint2.com/","https://endpoint3.com/"]
```

**Features:**
- ✅ Structured format
- ✅ Compatible with JSON tools
- ✅ Good for programmatic generation

**Example:**

```dotenv
RPC_ENDPOINTS=["https://allora-rpc.testnet.allora.network/","https://allora-testnet-rpc.allthatnode.com:1317/","https://allora.api.chandrastation.com/"]
```

### Method 3: Default Hardcoded Endpoints

If `RPC_ENDPOINTS` is not set in `.env`, the code uses these defaults:

```python
[
    {"url": "https://allora-rpc.testnet.allora.network/", "name": "Primary"},
    {"url": "https://allora-testnet-rpc.allthatnode.com:1317/", "name": "AllThatNode"},
    {"url": "https://allora.api.chandrastation.com/", "name": "ChandraStation"},
]
```

**When used:** Only if `RPC_ENDPOINTS` is empty or not set

## Current Configuration Status

Your current `.env` has:

```dotenv
RPC_ENDPOINTS=https://allora-rpc.testnet.allora.network/,https://allora-testnet-rpc.allthatnode.com:1317/,https://allora.api.chandrastation.com/
```

✅ **Status:** 3 RPC endpoints configured (comma-separated)

## URL Format Requirements

### Trailing Slashes
- **Required:** All URLs must end with `/`
- **Automatic:** The code normalizes URLs (adds `/` if missing)

### Supported URL Types
- ✅ REST endpoints: `https://example.com/`
- ✅ gRPC over HTTPS: `https://example.com:9090/`
- ✅ Custom ports: `https://example.com:1317/`

### Examples of Valid URLs
```
https://allora-rpc.testnet.allora.network/
https://allora-testnet-rpc.allthatnode.com:1317/
https://allora.api.chandrastation.com/
https://custom-endpoint:8080/
```

## How Failover Works

### Endpoint Selection Process

1. **First Call:** Daemon selects the first working endpoint
2. **Round-Robin:** Each subsequent call rotates to the next endpoint
3. **Failure Tracking:** Tracks failures per endpoint (max 3 failures)
4. **Auto-Skip:** After 3 failures, endpoint is skipped
5. **Reset:** When all endpoints fail, failure counters reset

### Example Flow

```
Request 1: Endpoint-1 ✅ (success)
Request 2: Endpoint-2 → Endpoint-3 ✅ (endpoint-2 failed)
Request 3: Endpoint-1 ✅ (rotates back)
Request 4: Endpoint-3 ✅ (endpoint-2 still disabled)

After endpoint-2 recovers from failures:
Request 5: Endpoint-1 ✅ (endpoint-2 re-enabled)
```

### Failure Tracking Log Messages

```
⚠️  RPC endpoint marked failed: Endpoint-1
   Failures: 1/3
   Error: Connection timeout
```

```
❌ RPC endpoint DISABLED: Endpoint-1
   URL: https://...
   Failures: 3/3 (disabled)
   Error: Previous connection errors
```

```
✅ RPC endpoint recovered: Endpoint-1
```

## Diagnosis and Monitoring

### Verify RPC Endpoints

Run the diagnostic script:

```bash
python3 diagnose_env_wallet.py
```

**Output shows:**
- ✅ Which endpoints are configured
- ✅ Source (from .env or defaults)
- ✅ Connectivity status for each endpoint
- ✅ Whether endpoints are reachable

### Check Daemon RPC Usage

View logs:

```bash
tail -100 logs/submission.log | grep "RPC\|endpoint"
```

**Look for:**
- `Selected RPC endpoint:` → Which endpoint was chosen
- `marked failed:` → Endpoint had issues
- `recovered:` → Endpoint is working again

### Monitor Endpoint Health

Count failures in logs:

```bash
grep "marked failed" logs/submission.log | wc -l
grep "DISABLED" logs/submission.log | wc -l
grep "recovered" logs/submission.log | wc -l
```

## Common Issues and Solutions

### Issue: "All RPC endpoints have exceeded retry limit"

**Cause:** All 3 endpoints failed 3 times each

**Solution:**
1. Check network connectivity: `curl -I https://endpoint-url/`
2. Verify endpoint is responding
3. Check endpoint status page
4. Add a working backup endpoint to `RPC_ENDPOINTS`

**Fix:**

```bash
# Test endpoints
curl -I https://allora-rpc.testnet.allora.network/
curl -I https://allora-testnet-rpc.allthatnode.com:1317/
curl -I https://allora.api.chandrastation.com/

# If one works, the daemon will recover automatically on next cycle
```

### Issue: Slow endpoint causing timeouts

**Cause:** Endpoint is responding slowly (>30s)

**Solution:** Add faster endpoint with higher priority

```dotenv
# Put faster endpoint first
RPC_ENDPOINTS=https://fast-endpoint/,https://allora-rpc.testnet.allora.network/,https://allora-testnet-rpc.allthatnode.com:1317/
```

### Issue: Need to switch to different RPC provider

**Solution:** Update `.env`:

```bash
# Stop daemon
pkill -f "submit_prediction.py --daemon"

# Edit .env
nano .env

# Update RPC_ENDPOINTS line with new endpoints

# Restart daemon
nohup python3 submit_prediction.py --daemon > logs/submission.log 2>&1 &
```

## Testing RPC Configuration

### Test Endpoints Manually

```bash
# Test with curl
curl -s https://allora-rpc.testnet.allora.network/ | head -20

# Test with Python
python3 -c "
import requests
url = 'https://allora-rpc.testnet.allora.network/'
r = requests.get(url, timeout=5)
print(f'Status: {r.status_code}')
print(f'Response length: {len(r.text)} chars')
"
```

### Test RPC with allorad CLI

```bash
# Test query with specific endpoint
allorad query emissions unfulfilled-worker-nonces 67 \
  --node https://allora-rpc.testnet.allora.network/ \
  --output json

# Test with different endpoint
allorad query emissions unfulfilled-worker-nonces 67 \
  --node https://allora-testnet-rpc.allthatnode.com:1317/ \
  --output json
```

## Best Practices

### 1. Always Use HTTPS
```dotenv
# ✅ Good
RPC_ENDPOINTS=https://secure-endpoint/

# ❌ Bad (insecure)
RPC_ENDPOINTS=http://insecure-endpoint/
```

### 2. Use Trailing Slashes
```dotenv
# ✅ Good
RPC_ENDPOINTS=https://endpoint.com/

# ❌ Bad (missing slash - but auto-corrected)
RPC_ENDPOINTS=https://endpoint.com
```

### 3. Diversify Endpoints
```dotenv
# ✅ Good (3 different providers)
RPC_ENDPOINTS=https://official-rpc/,https://provider1-rpc/,https://provider2-rpc/

# ❌ Bad (all same provider)
RPC_ENDPOINTS=https://provider1-rpc/,https://provider1-backup1/,https://provider1-backup2/
```

### 4. Test Before Deployment
```bash
# Run diagnostic before starting daemon
python3 diagnose_env_wallet.py

# Test with --once before --daemon
python3 submit_prediction.py --once

# Only then start daemon
nohup python3 submit_prediction.py --daemon > logs/submission.log 2>&1 &
```

### 5. Monitor Regularly
```bash
# Check daemon status
ps aux | grep "submit_prediction.*--daemon"

# Monitor RPC failures
tail -f logs/submission.log | grep "RPC\|endpoint"

# Weekly health check
python3 diagnose_env_wallet.py
```

## Advanced Configuration

### Custom Endpoint Priority

The daemon uses round-robin selection, so **order matters**:

```dotenv
# Option 1: Primary endpoint first (preferred)
RPC_ENDPOINTS=https://main-endpoint/,https://backup1/,https://backup2/

# Option 2: Fastest endpoint first
RPC_ENDPOINTS=https://fast-provider/,https://standard-provider/,https://slow-provider/
```

### Dynamic Endpoint Updates

To add/remove endpoints:

1. Stop daemon: `pkill -f "submit_prediction.py --daemon"`
2. Update `.env`
3. Restart daemon: `nohup python3 submit_prediction.py --daemon > logs/submission.log 2>&1 &`

**Daemon will load new endpoints on restart.**

### Performance Tuning

Adjust timeout values in code if needed:

```python
# In submit_prediction.py
subprocess.run(cmd, timeout=30)  # Increase for slow endpoints
subprocess.run(cmd, timeout=10)  # Decrease for fast endpoints
```

## Specification

**RPC Endpoint List Format:**
- **Type:** String (comma-separated or JSON array)
- **Default:** 3 hardcoded endpoints if not specified
- **Max URLs:** Unlimited (recommended: 1-5)
- **URL Validation:** Automatic normalization
- **Failover:** Automatic round-robin with tracking
- **Failure Threshold:** 3 per endpoint
- **Reset Condition:** When all endpoints fail

## Related Files

- `.env` - Configuration file with `RPC_ENDPOINTS`
- `submit_prediction.py` - Daemon using RPC endpoints
- `diagnose_env_wallet.py` - Diagnostic tool for verification
- `logs/submission.log` - Execution logs with RPC details

---

**Last Updated:** 2025-11-24  
**Version:** 2.1  
**Status:** Production Ready
