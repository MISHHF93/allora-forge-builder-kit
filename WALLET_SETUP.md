# Wallet Setup Guide for Allora Testnet

## The Problem: "Account Not Found"

When you see this error:
```
grpc._channel._InactiveRpcError: <_InactiveRpcError of RPC that terminated with:
        status = StatusCode.NOT_FOUND
        details = "account allo1ska6753h50xwxzm4knesa7sd7klqts4np4j5z7 not found"
```

**This is expected!** The wallet exists in your local keyring but hasn't been created on-chain yet.

### Why Does This Happen?

On blockchain, accounts are **lazy-created** - they don't exist on-chain until the first transaction that touches them. The account address is derived from your keys locally, but it needs at least one on-chain transaction to activate.

## Solution: Fund Your Wallet

### Step 1: Get Your Wallet Address

```bash
python setup_wallet.py --info
```

Or manually:
```bash
allorad keys show test-wallet -a
```

This will output your address like: `allo1ska6753h50xwxzm4knesa7sd7klqts4np4j5z7`

### Step 2: Fund the Wallet (Testnet Only)

On testnet, use the faucet:

```bash
# Try automatic faucet request
python setup_wallet.py --faucet

# Or manually visit the testnet faucet:
# https://faucet.testnet.allora.network
```

**For the manual faucet:**
1. Go to https://faucet.testnet.allora.network
2. Paste your wallet address
3. Click "Request Tokens"
4. Wait 30-60 seconds for tokens to arrive

### Step 3: Verify Wallet is On-Chain

```bash
# Check account exists
python setup_wallet.py --verify

# Check balance
python setup_wallet.py --balance
```

Expected output when funded:
```
Checking balance for allo1ska6753h50xwxzm4knesa7sd7klqts4np4j5z7...
✅ Balance: 10.000000 ALLO
```

### Step 4: Register for Topic (Optional)

If you want to be a worker for Topic 67:

```bash
python setup_wallet.py --register-topic 67
```

This sends the first on-chain transaction, which also creates your account.

## Complete Workflow

### Option A: Use Faucet (Easiest)

```bash
# 1. Create wallet from mnemonic (if needed)
export MNEMONIC="trick gaze bean avoid rack undo wing present alpha evoke curious jar..."
python setup_wallet.py --create

# 2. Request faucet tokens
python setup_wallet.py --faucet

# 3. Wait 30-60 seconds for funding

# 4. Verify account is on-chain
python setup_wallet.py --verify

# 5. Now your training+submit pipeline will work
python train_and_submit_sdk.py --submit --retrain
```

### Option B: Manual Funding + Registration

```bash
# 1. Get your address
WALLET_ADDR=$(allorad keys show test-wallet -a)
echo "Send ALLO to: $WALLET_ADDR"

# 2. (In another terminal or browser) Use faucet or send tokens

# 3. Register as worker (creates on-chain account)
python setup_wallet.py --register-topic 67

# 4. Verify
python setup_wallet.py --info

# 5. Start submitting
python train_and_submit_sdk.py --submit
```

## Troubleshooting

### Q: How much ALLO do I need?
**A:** Minimum 0.25 ALLO for ~50,000 submissions (at 1000 uallo = 0.001 ALLO per tx)

### Q: Faucet not working?
**A:** The faucet URL may vary by testnet. Check:
- Allora Discord for current faucet link
- Allora docs: https://docs.allora.network
- Or send tokens manually if you have testnet ALLO

### Q: My wallet address is different?
**A:** Make sure you're using the right mnemonic:
```bash
echo $MNEMONIC  # Check current mnemonic
allorad keys delete test-wallet  # Delete wrong wallet
python setup_wallet.py --create  # Create correct one
```

### Q: "Already registered for this topic"?
**A:** That's fine! You've already done the registration. Just verify your balance is positive:
```bash
python setup_wallet.py --balance
```

### Q: Still getting "account not found" after faucet?
**A:** The first transaction you send is what creates the account. Try:
```bash
python setup_wallet.py --register-topic 67
```

This sends a transaction which will create your on-chain account.

## Environment Variables

Set these for automatic wallet management:

```bash
export MNEMONIC="your 24-word phrase here"
export ALLORA_CHAIN_ID="allora-testnet-1"
export ALLORA_WALLET_NAME="test-wallet"
```

Then just run:
```bash
python train_and_submit_sdk.py --submit
```

## Quick Reference

| Command | Purpose |
|---------|---------|
| `python setup_wallet.py --info` | Show wallet status |
| `python setup_wallet.py --balance` | Check ALLO balance |
| `python setup_wallet.py --verify` | Check account on-chain |
| `python setup_wallet.py --faucet` | Request testnet tokens |
| `python setup_wallet.py --register-topic 67` | Register for Topic 67 |

---

**Key Takeaway:** The "account not found" error means your wallet needs to be funded first. Use the faucet to send it ALLO tokens, which will create the on-chain account automatically.
