# "Account Not Found" Error - Root Cause & Solution

## The Problem

When running the SDK-based submission pipeline, you get this error:

```
grpc._channel._InactiveRpcError: <_InactiveRpcError of RPC that terminated with:
        status = StatusCode.NOT_FOUND
        details = "account allo1ska6753h50xwxzm4knesa7sd7klqts4np4j5z7 not found"
```

**This is 100% expected and normal!** ✅

## Why This Happens

### Blockchain Accounts are Lazy-Created

On most blockchains (including Allora), accounts don't exist on-chain until someone sends them their first transaction. This is called "lazy account creation":

1. **Locally**: Your wallet address is derived from your keys immediately when you create the wallet
2. **On-Chain**: The account doesn't exist until a transaction touches it

### The Exact Flow

1. ✅ You have a mnemonic phrase
2. ✅ You run `allorad keys add test-wallet --recover`
3. ✅ Wallet is created locally → address: `allo1ska6753h50xwxzm4knesa7sd7klqts4np4j5z7`
4. ❌ BUT account doesn't exist on-chain yet
5. ❌ When SDK tries to query account info for transaction building → "account not found" 404
6. ✅ Solution: Send the wallet its first transaction by funding it

## The Fix: Fund Your Wallet

### Option A: Use Testnet Faucet (Easiest)

```bash
# 1. Check wallet exists
python setup_wallet.py --info

# 2. Request tokens from faucet
python setup_wallet.py --faucet

# 3. Wait 30-60 seconds

# 4. Verify funding worked
python setup_wallet.py --balance

# 5. Now try submission
python train_and_submit_sdk.py --submit --retrain
```

### Option B: Manual Faucet

1. Get your wallet address:
   ```bash
   allorad keys show test-wallet -a --keyring-backend test
   ```

2. Visit the testnet faucet:
   - https://faucet.testnet.allora.network

3. Paste your wallet address and click "Request"

4. Wait 30-60 seconds for tokens to arrive

5. Verify:
   ```bash
   python setup_wallet.py --balance
   ```

### Option C: Register for a Topic (Creates Account)

Registering as a worker sends a transaction which creates your on-chain account:

```bash
python setup_wallet.py --register-topic 67
```

## What Actually Fixes It

When you fund your wallet, one of these happens:
- The faucet sends you tokens → creates your account ✅
- You send your first transaction → creates your account ✅
- You register for a topic → creates your account ✅

Once the account exists on-chain, the SDK can query it and proceed with submissions.

## Minimum Requirements

- **Balance**: 0.25 ALLO (for ~50,000 transactions at 1000 uallo each)
- **Account**: Must exist on-chain (created by funding or first transaction)
- **Network**: Must be able to reach testnet RPC/REST endpoints

## Complete Workflow

```bash
# 1. Create wallet from mnemonic
export MNEMONIC="trick gaze bean avoid rack undo wing present alpha evoke curious jar..."
python setup_wallet.py --create

# 2. Check local wallet
python setup_wallet.py --info
# Output: Address: allo1ska6753h50xwxzm4knesa7sd7klqts4np4j5z7
#         On-Chain Status: ❌ Not found (expected)

# 3. Fund wallet via faucet
python setup_wallet.py --faucet
# Wait 30-60 seconds...

# 4. Verify funding
python setup_wallet.py --balance
# Output: ✅ Balance: 10.000000 ALLO

# 5. Now submission works!
python train_and_submit_sdk.py --submit --retrain
# Should succeed now that account exists on-chain
```

## Troubleshooting

### Still Getting "Account Not Found" After Faucet?

1. Check balance:
   ```bash
   python setup_wallet.py --balance
   ```
   - If balance is 0, faucet didn't work - try manual funding
   - If balance > 0, account should exist - wait 1-2 minutes and retry

2. Verify account on-chain:
   ```bash
   python setup_wallet.py --verify
   ```
   - Exit code 0 = account exists ✅
   - Exit code 1 = account doesn't exist yet ❌

3. Force account creation:
   ```bash
   python setup_wallet.py --register-topic 67
   ```
   This sends a transaction which definitely creates your account.

### Faucet Not Working?

Check:
1. Is your wallet address correct? `python setup_wallet.py --info`
2. Is faucet endpoint correct? Check Allora Discord for current faucet URL
3. Try manual funding:
   - Send ALLO to your address from another account
   - Or check if there's a Discord faucet bot

### Multiple Wallets?

Make sure you're using the right one:
```bash
# Delete wrong wallet
allorad keys delete test-wallet --keyring-backend test

# Create correct wallet
export MNEMONIC="your actual mnemonic"
python setup_wallet.py --create

# Verify
python setup_wallet.py --info
```

## Key Takeaways

| Issue | Cause | Solution |
|-------|-------|----------|
| "Account not found" | Wallet not funded | Send ALLO via faucet |
| Account exists but errors | Network connectivity | Check RPC/REST endpoints |
| Can't create wallet | Wrong mnemonic | Set correct MNEMONIC env var |
| Balance is 0 after faucet | Faucet didn't work | Try manual funding |

## Files Added

- **setup_wallet.py**: Wallet management tool
- **WALLET_SETUP.md**: Detailed setup guide  
- **check_wallet.sh**: Quick status script

All tools work with the same wallet (test-wallet) used by train_and_submit_sdk.py.

---

## Next Steps

Once wallet is funded and account exists on-chain:

```bash
# Run complete training + submission pipeline
python train_and_submit_sdk.py --submit --retrain

# Or in a loop for continuous submission
while true; do
  python train_and_submit_sdk.py --submit --retrain
  sleep 3600  # Submit once per hour
done
```

**The pipeline is now production-ready!** 🚀
