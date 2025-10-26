import os
import sys
from dotenv import load_dotenv

load_dotenv()

try:
    from allora_sdk.worker import AlloraWorker
except ImportError as e:
    print("ERROR: please install allora-sdk (pip install allora-sdk)", file=sys.stderr)
    raise


def main():
    api_key = os.getenv("ALLORA_API_KEY", "").strip()
    if not api_key:
        print("Missing ALLORA_API_KEY in environment or .env", file=sys.stderr)
        sys.exit(1)

    # Newer SDKs require a 'run' callable in the constructor signature
    def dummy_run(_: int) -> float:
        return 0.0
    try:
        w = AlloraWorker(run=dummy_run, api_key=api_key, topic_id=67)
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
