#!/usr/bin/env python3
"""
check_worker_status.py

Purpose:
  Query whether a worker (wallet address) is registered/active for a topic on Allora,
  using the allora_sdk API client when possible, and falling back to allorad CLI queries otherwise.

Usage:
    python3 scripts/check_worker_status.py --address <allo...> --topic-id 67 \
      --rpc https://allora-rpc.testnet.allora.network --chain-id allora-testnet-1

Notes:
  - If allora_sdk AlloraAPIClient does not expose direct methods, the script tries
    to discover likely methods via introspection and attempts them.
  - If SDK methods are not available, it falls back to 'allorad' CLI queries if present.
  - No secrets are printed; only the wallet address and public query results are shown.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from typing import Any, Dict, Optional, Tuple, Iterable


DEFAULT_CHAIN_ID = os.getenv("ALLORA_CHAIN_ID", "allora-testnet-1")
DEFAULT_RPC = os.getenv("ALLORA_RPC_URL") or os.getenv("ALLORA_NODE") or "https://allora-rpc.testnet.allora.network"


def ts() -> str:
    import datetime as _dt
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_rpc(rpc: str) -> str:
    if not rpc:
        return rpc
    first = rpc.split()[0]
    m = re.match(r"^(https?://[^/\s]+)", first)
    if m:
        return m.group(1)
    m = re.match(r"^(tcp://[^/\s]+)", first)
    if m:
        return m.group(1)
    return first


def find_allora_client() -> Tuple[Optional[type], Optional[str]]:
    """Try to import AlloraAPIClient from common allora_sdk locations.

    Returns: (class_or_None, import_path)
    """
    candidates = [
        ("allora_sdk.client", "AlloraAPIClient"),
        ("allora_sdk.api", "AlloraAPIClient"),
        ("allora_sdk", "AlloraAPIClient"),
    ]
    for mod_name, cls_name in candidates:
        try:
            mod = __import__(mod_name, fromlist=[cls_name])
            cls = getattr(mod, cls_name, None)
            if cls is not None:
                return cls, f"{mod_name}.{cls_name}"
        except (ImportError, AttributeError):
            continue
    return None, None


def build_client_kwargs(client_cls: type, chain_id: str, rpc: str) -> Dict[str, Any]:
    """Construct best-effort kwargs for AlloraAPIClient constructor by signature inspection."""
    try:
        import inspect
        sig = inspect.signature(client_cls.__init__)
        names = set(sig.parameters.keys())
    except (ValueError, TypeError):
        names: set[str] = set()
    kwargs: Dict[str, Any] = {}
    if "chain_id" in names:
        kwargs["chain_id"] = chain_id
    if "chainId" in names:
        kwargs["chainId"] = chain_id
    # RPC / node url
    if "rpc_url" in names:
        kwargs["rpc_url"] = rpc
    elif "rpcUrl" in names:
        kwargs["rpcUrl"] = rpc
    elif "node" in names:
        kwargs["node"] = rpc
    elif "node_url" in names:
        kwargs["node_url"] = rpc
    elif "nodeUrl" in names:
        kwargs["nodeUrl"] = rpc
    return kwargs


def SDK_try_calls(client: Any, address: str, topic_id: int) -> Dict[str, Any]:
    """Attempt to call plausible SDK methods to fetch worker info/registration/latest inference.

    Returns dict with keys potentially present: worker_info, is_registered, latest_inference
    """
    out: Dict[str, Any] = {}
    methods = dir(client)
    # Candidates for method names
    candidates = {
        "worker_info": [
            "worker_info", "get_worker_info", "query_worker_info", "emissions_worker_info",
        ],
        "is_registered": [
            "is_worker_registered", "query_is_worker_registered", "worker_is_registered",
        ],
        "latest_inference": [
            "worker_latest_inference", "get_worker_latest_inference", "query_worker_latest_inference",
        ],
    }

    def try_call(name_list: Iterable[str], *args: Any, **kwargs: Any):
        for nm in name_list:
            if nm in methods:
                try:
                    fn = getattr(client, nm)
                    return True, fn(*args, **kwargs)
                except TypeError:
                    # Try alternative arg order
                    try:
                        return True, getattr(client, nm)(*reversed(args), **kwargs)
                    except (TypeError, AttributeError):
                        pass
                except (AttributeError, RuntimeError):
                    pass
        return False, None

    ok, val = try_call(candidates["worker_info"], address)
    if ok and val is not None:
        out["worker_info"] = val

    # For registration we may need (topic_id, address) or (address, topic_id)
    ok, val = try_call(candidates["is_registered"], topic_id, address)
    if not ok or val is None:
        ok, val = try_call(candidates["is_registered"], address, topic_id)
    if ok and val is not None:
        out["is_registered"] = val

    ok, val = try_call(candidates["latest_inference"], topic_id, address)
    if not ok or val is None:
        ok, val = try_call(candidates["latest_inference"], address, topic_id)
    if ok and val is not None:
        out["latest_inference"] = val

    return out


def run_cli(cmd: str) -> Tuple[int, str]:
    try:
        proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        code = int(proc.returncode)
        return code, (proc.stdout or "").strip() or (proc.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def cli_query_worker_info(rpc: str, address: str) -> Optional[Dict[str, Any]]:
    cmd = f"allorad query emissions worker-info {shlex.quote(address)} --node {shlex.quote(rpc)} -o json"
    code, out = run_cli(cmd)
    if code == 0 and out:
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {"raw": out}
    return None


def cli_query_is_registered(rpc: str, topic_id: int, address: str) -> Optional[bool]:
    cmd = f"allorad query emissions is-worker-registered {int(topic_id)} {shlex.quote(address)} --node {shlex.quote(rpc)} -o json"
    code, out = run_cli(cmd)
    if code == 0 and out:
        try:
            data = json.loads(out)
            if isinstance(data, bool):
                return data
            # Try to coerce from string or nested field
            if isinstance(data, str):
                return data.lower().strip() == "true"
            if isinstance(data, dict):
                # Probe common boolean-like fields without iterating unknown-typed values
                for key in ("registered", "is_registered", "result", "ok", "value"):
                    try:
                        if key in data:  # type: ignore[operator]
                            v_any = data[key]  # type: ignore[index]
                            if isinstance(v_any, bool):
                                return v_any
                            if isinstance(v_any, str) and v_any.lower().strip() in ("true", "false"):
                                return v_any.lower().strip() == "true"
                    except (KeyError, TypeError, AttributeError):
                        pass
        except json.JSONDecodeError:
            if out.lower().find("true") >= 0:
                return True
            if out.lower().find("false") >= 0:
                return False
    return None


def cli_query_latest_inference(rpc: str, topic_id: int, address: str) -> Optional[Dict[str, Any]]:
    cmd = f"allorad query emissions worker-latest-inference {int(topic_id)} {shlex.quote(address)} --node {shlex.quote(rpc)} -o json"
    code, out = run_cli(cmd)
    if code == 0 and out:
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {"raw": out}
    return None


def main() -> int:
    p = argparse.ArgumentParser(description="Check Allora worker status for a topic")
    p.add_argument("--address", default=os.getenv("ALLORA_WALLET_ADDR", ""))
    p.add_argument("--topic-id", type=int, default=67)
    p.add_argument("--rpc", default=DEFAULT_RPC)
    p.add_argument("--chain-id", default=DEFAULT_CHAIN_ID)
    args = p.parse_args()

    rpc = normalize_rpc(args.rpc)
    if not args.address or not args.address.startswith("allo"):
        print(f"[{ts()}] [ERROR] Provide a valid worker address via --address or ALLORA_WALLET_ADDR (starts with 'allo').", file=sys.stderr)
        return 2

    address = args.address
    topic_id = int(args.topic_id)
    print(f"[{ts()}] [INFO] Checking status: address={address} topic={topic_id} rpc={rpc} chain_id={args.chain_id}")

    # 1) Try allora_sdk AlloraAPIClient
    sdk_ok = False
    try:
        ClientCls, where = find_allora_client()
        if ClientCls is not None:
            kwargs = build_client_kwargs(ClientCls, args.chain_id, rpc)
            client = ClientCls(**kwargs) if kwargs else ClientCls()
            print(f"[{ts()}] [INFO] Using SDK client: {where} with kwargs={{{', '.join(f'{k}={v}' for k,v in kwargs.items())}}}")
            res = SDK_try_calls(client, address, topic_id)
            if res:
                sdk_ok = True
                if "worker_info" in res:
                    print(f"[{ts()}] [INFO] SDK worker-info: {res['worker_info']}")
                if "is_registered" in res:
                    print(f"[{ts()}] [INFO] SDK is-worker-registered: {res['is_registered']}")
                if "latest_inference" in res:
                    print(f"[{ts()}] [INFO] SDK worker-latest-inference: {res['latest_inference']}")
            else:
                print(f"[{ts()}] [WARN] SDK client available but no matching query methods responded.")
        else:
            print(f"[{ts()}] [WARN] allora_sdk AlloraAPIClient not found; skipping SDK path.")
    except (RuntimeError, AttributeError, TypeError) as e:
        print(f"[{ts()}] [WARN] SDK query attempt failed: {e}")

    # 2) Fallback to allorad CLI if SDK didn't yield
    had_any = False
    if not sdk_ok:
        # worker-info
        info = cli_query_worker_info(rpc, address)
        if info is not None:
            print(f"[{ts()}] [INFO] CLI worker-info: {json.dumps(info, ensure_ascii=False)}")
            had_any = True
        else:
            print(f"[{ts()}] [WARN] CLI worker-info query failed or returned empty.")
        # is-worker-registered
        isreg = cli_query_is_registered(rpc, topic_id, address)
        if isreg is not None:
            print(f"[{ts()}] [INFO] CLI is-worker-registered: {isreg}")
            had_any = True
        else:
            print(f"[{ts()}] [WARN] CLI is-worker-registered query failed.")
        # worker-latest-inference
        latest = cli_query_latest_inference(rpc, topic_id, address)
        if latest is not None:
            print(f"[{ts()}] [INFO] CLI worker-latest-inference: {json.dumps(latest, ensure_ascii=False)}")
            had_any = True
        else:
            print(f"[{ts()}] [WARN] CLI worker-latest-inference query failed.")

        if not had_any:
            print(f"[{ts()}] [ERROR] No SDK methods matched and CLI fallbacks failed. Ensure 'allorad' is installed in PATH or update allora_sdk.")
            return 1

    print(f"[{ts()}] [INFO] Done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
