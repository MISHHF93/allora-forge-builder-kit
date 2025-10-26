# Keplr: Correct Allora Testnet Configuration

If Keplr shows a near-zero ALLO balance while the CLI shows funds, you likely have a duplicate or misconfigured chain.

## Steps
1. Remove duplicate/stale Allora entries in Keplr (Settings → Chains).
2. Import the correct chain from `tools/keplr_allora_testnet_chain.json` using Keplr manual import.
3. Clear stale custom tokens using the wrong minimal denom or decimals.
4. Ensure ALLO is defined as:
   - Minimal denom: `uallo`
   - Decimals: `6`
   - If needed, add a custom token (Name: ALLO, Denom: uallo, Decimals: 6).
5. Reset Connected Websites in Keplr and reload the extension, then refresh any connected sites.

## CLI sanity checks
- `allorad --node https://allora-rpc.testnet.allora.network/ query emissions is-worker-registered 67 <your_address>`
- `allorad query bank balances <your_address> --node https://allora-rpc.testnet.allora.network/`

## Repo helpers
- `python -u tools/print_wallet_address.py` prints the SDK-resolved wallet (signer from `.allora_key`).
- `python -u tools/scrub_wallets.py` clears stale notebook outputs and replaces old addresses in text.
