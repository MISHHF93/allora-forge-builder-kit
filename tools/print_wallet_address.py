import os
import sys
from dotenv import load_dotenv

load_dotenv()

try:
    from allora_sdk.worker import AlloraWorker
    from allora_sdk.rpc_client.config import AlloraNetworkConfig, AlloraWalletConfig
except ImportError as e:
    print("ERROR: please install allora-sdk (pip install allora-sdk)", file=sys.stderr)
    raise


def main():
    try:
        wallet_cfg = AlloraWalletConfig.from_env()
    except ValueError as exc:
        print(f"Missing wallet configuration for allora-sdk: {exc}", file=sys.stderr)
        print("Hint: ensure .allora_key exists or set ALLORA_MNEMONIC / MNEMONIC_FILE.", file=sys.stderr)
        sys.exit(1)

    network_cfg = AlloraNetworkConfig(
        chain_id=os.getenv("ALLORA_CHAIN_ID", "allora-testnet-1"),
        url=os.getenv("ALLORA_GRPC_URL") or "grpc+https://testnet-allora.lavenderfive.com:443",
        websocket_url=os.getenv("ALLORA_WS_URL") or "wss://testnet-rpc.lavenderfive.com:443/allora/websocket",
        fee_denom="uallo",
        fee_minimum_gas_price=10.0,
    )

    # Newer SDKs require a 'run' callable in the constructor signature
    def dummy_run(_: int) -> float:
        return 0.0
    try:
        w = AlloraWorker(run=dummy_run, wallet=wallet_cfg, network=network_cfg, topic_id=67)
    except (TypeError, RuntimeError) as e:
        print(f"ERROR: Could not construct AlloraWorker: {e}", file=sys.stderr)
        sys.exit(2)
    addr = None
    for attr in ("wallet_address", "address", "wallet"):
        try:
            val = getattr(w, attr, None)
            if isinstance(val, dict):
                val = val.get("address")
            if val:
                addr = val
                break
        except AttributeError:
            continue
    if addr:
        print(f"Resolved SDK wallet address: {addr}")
        if os.getenv("ALLORA_WALLET_ADDR") and os.getenv("ALLORA_WALLET_ADDR") != addr:
            print("Warning: ALLORA_WALLET_ADDR differs from SDK-resolved wallet address; signing uses .allora_key only.", file=sys.stderr)
    else:
        print("Could not resolve wallet address from SDK worker.", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
