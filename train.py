import os
import sys
import json
import argparse
import time
import asyncio
import logging
from typing import List, Optional, Tuple, Dict, Any, Set, cast
import warnings
import pandas as pd
from dotenv import load_dotenv, find_dotenv, dotenv_values
import re
import numpy as np
from numpy.typing import NDArray
import math
import pickle
import requests
import subprocess

# Load environment variables from .env at import time
load_dotenv()

from allora_forge_builder_kit.workflow import AlloraMLWorkflow
from allora_forge_builder_kit.alpha_features import build_alpha_features, merge_external_features
from allora_forge_builder_kit.submission_log import (
    ensure_submission_log_schema,
    normalize_submission_log_file,
    dedupe_submission_log_file,
    log_submission_row,
)

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None

# Set up logging to pipeline_run.log with timestamps
logging.basicConfig(
    filename='pipeline_run.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%SZ'
)

# --- Timezone helpers ---------------------------------------------------------
# NumPy datetime64 does not preserve timezone information. To avoid warnings
# like "no explicit representation of timezones available for np.datetime64"
# and to keep the competition cadence strictly in UTC, we normalize all
# datetime values to NAIVE UTC (tz stripped) before any NumPy conversion.
# (removed unused timezone alias)

def _to_naive_utc_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Return a DatetimeIndex normalized to naive UTC (tz stripped).
    - If tz-aware, convert to UTC and strip tzinfo.
    - If tz-naive, assume it already represents UTC and return as-is.
    """
    try:
        di = pd.DatetimeIndex(idx)
        if getattr(di, "tz", None) is not None:
            return di.tz_convert("UTC").tz_localize(None)
        return di
    except (ValueError, TypeError, AttributeError, RuntimeError):
        # Best-effort fallback
        di = pd.to_datetime(idx, utc=True)
        return pd.DatetimeIndex(di.tz_convert("UTC").tz_localize(None))

def _to_naive_utc_ts(ts: pd.Timestamp) -> pd.Timestamp:
    """Return a Timestamp normalized to naive UTC (tz stripped)."""
    try:
        if getattr(ts, "tz", None) is not None:
            return ts.tz_convert("UTC").tz_localize(None)
        return ts
    except (ValueError, TypeError, AttributeError, RuntimeError):
        # Fallback: coerce to UTC then strip
        t = pd.Timestamp(ts, tz="UTC")
        return t.tz_localize(None)

def _require_api_key() -> str:
    api_key = os.getenv("ALLORA_API_KEY")
    if api_key:
        return api_key.strip()

    # Retry with explicit path near this script and with find_dotenv fallback
    repo_dotenv = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    # If a .env is found elsewhere (e.g., parent), prefer that
    discovered = find_dotenv(usecwd=True) or repo_dotenv
    if os.path.exists(discovered):
        load_dotenv(dotenv_path=discovered, override=True, encoding="utf-8")
        api_key = os.getenv("ALLORA_API_KEY")
        if api_key:
            return api_key.strip()

    # Last-chance parse without injecting into env
    def _manual_parse_env(path: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    # Normalize key: keep only [A-Za-z0-9_]
                    k = re.sub(r"[^A-Za-z0-9_]", "", k.strip())
                    v = v.strip().strip('"').strip("'")
                    result[k] = v
        except (OSError, IOError):
            return {}
        return result

    try:
        parsed = dotenv_values(discovered) if os.path.exists(discovered) else {}
        # Also parse manually and merge if needed
        manual: Dict[str, str] = _manual_parse_env(discovered) if os.path.exists(discovered) else {}
        parsed_clean: Dict[str, str] = {k: str(v) for k, v in (parsed or {}).items() if isinstance(v, str) and v}
        merged: Dict[str, str] = {**parsed_clean, **{k: v for k, v in manual.items() if v}}
        # Debug: list parsed keys without values
        if merged:
            print(f"Loaded .env from {discovered} with keys: {list(merged.keys())}")
        api_key = (merged or {}).get("ALLORA_API_KEY")
        if api_key:
            os.environ["ALLORA_API_KEY"] = api_key
    except (OSError, IOError):
        api_key = None

    # Final attempt: bytes-level grep for the key with tolerant separators/whitespace
    if not api_key and os.path.exists(discovered):
        try:
            with open(discovered, "rb") as fb:
                raw = fb.read()
            text = None
            for enc in ("utf-8-sig", "utf-8", "latin-1"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if text is None:
                text = raw.decode("latin-1", errors="ignore")
            # Regex: allow non-word separators around key and either '=' or ':' as assignment
            m = re.search(r"(?mi)^\s*ALLORA_API_KEY\s*[:=]\s*([^\r\n]+)", text)
            if m:
                candidate = m.group(1).strip().strip('"').strip("'")
                if candidate:
                    os.environ["ALLORA_API_KEY"] = candidate
                    return candidate
        except OSError:
            pass

    if not api_key:
        print(
            f"ERROR: ALLORA_API_KEY not found in environment (.env). Searched: {discovered} (exists={os.path.exists(discovered)}).",
            file=sys.stderr,
        )
        sys.exit(1)
    return api_key.strip()


def _load_pipeline_config(root_dir: str) -> Dict[str, Any]:
    """Load pipeline configuration once for reuse."""
    cfg_path = os.path.join(root_dir, "config", "pipeline.yaml")
    cfg: Dict[str, Any] = {}
    if yaml and os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as fh:
                loaded: Any = yaml.safe_load(fh) or {}
            if isinstance(loaded, dict):
                cfg = cast(Dict[str, Any], loaded)
        except (OSError, IOError, UnicodeDecodeError, ValueError, TypeError) as exc:
            print(f"Warning: failed to load config/pipeline.yaml: {exc}")
    return cfg


# --- Submission helpers (integrated from prior submission script) ------------

CHAIN_ID = os.getenv("ALLORA_CHAIN_ID", "allora-testnet-1")
DEFAULT_TOPIC_ID = 67
DEFAULT_RPC = os.getenv("ALLORA_RPC_URL") or os.getenv("ALLORA_NODE") or "https://allora-rpc.testnet.allora.network"


def _derive_rest_base_from_rpc(rpc_url: str) -> str:
    """Best-effort derive REST base URL from an RPC URL.
    Known patterns:
      - https://allora-rpc.testnet.allora.network -> https://allora-api.testnet.allora.network
      - https://allora-rpc.mainnet.allora.network -> https://allora-api.mainnet.allora.network
    Fallback: if ALLORA_REST_URL env var is set, return that; else return the input unchanged.
    """
    env_rest = os.getenv("ALLORA_REST_URL", "").strip()
    if env_rest:
        return env_rest.rstrip('/')
    try:
        u = str(rpc_url or "").strip()
        # Generic replacements for common hostnames
        u2 = (
            u.replace("-rpc.", "-api.")
             .replace("rpc.", "api.")
        )
        return u2.rstrip('/')
    except Exception:
        return str(rpc_url).rstrip('/')


def _atomic_json_write(path: str, payload: Dict[str, Any]) -> None:
    """Atomically write JSON by using a temporary file and replacing the target."""
    tmp = f"{path}.tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as mf:
        json.dump(payload, mf, indent=2, allow_nan=False)
    os.replace(tmp, path)


# Contract schema (reference only, informs validation and helps tooling understand the topic config):
# Expected fields for MsgCreateNewTopic / Topic params
# {
#   creator: string (bech32 wallet address),
#   metadata: string (human-readable description; e.g., "BTC/USD 7d log-return forecaster"),
#   loss_method: string (e.g., "zptae_log10"),
#   epoch_length: int (blocks per epoch),
#   ground_truth_lag: int (epochs; matches forecast horizon),
#   worker_submission_window: int (epochs or blocks; window size for submissions),
#   p_norm: float (e.g., 3.0 for ZPTAE p=3),
#   alpha_regret: float,
#   allow_negative: bool (True for log returns),
#   epsilon: float (small positive, e.g., 1e-12),
#   merit_sortition_alpha: float,
#   active_inferer_quantile: float,
#   active_forecaster_quantile: float,
#   active_reputer_quantile: float
# }

# For Topic 67 (BTC/USD 7d log-returns) we align with the competition rules:
EXPECTED_TOPIC_67: Dict[str, Any] = {
    "topic_id": 67,
    "metadata_substr": ["BTC", "USD", "7", "log"],  # tolerant contains check
    "loss_method": ["zptae_log10", "zptae"],           # accept family name
    "p_norm": 3.0,
    "allow_negative": True,
    # Epoch and lag are chain-specific; we verify presence and positivity and try to infer horizon compatibility
    "require_epoch_length": True,
    "require_ground_truth_lag": True,
    # Submission window must exist and be > 0
    "require_worker_submission_window": True,
}


# Track topic activity state across loop iterations so we can surface transitions loudly
_LAST_TOPIC_ACTIVE_STATE: Optional[bool] = None


def zptae_log10_loss(y_true: List[float], y_pred: List[float], window: int = 100, p: float = 3.0, eps: float = 1e-12) -> Dict[str, float]:
    """Compute Z-transformed Power-Tanh Absolute Error and its log10(mean), with robust fallbacks.

    z = |y - y_hat| / (ref_std + eps), where ref_std is a rolling std with fallbacks.
    ptanh = tanh(z ** p)
    log10_loss = log10(mean(ptanh) + eps)

    If rolling std is unavailable (short series), fill with a positive global std.
    If the final mean is not finite, fall back to MAE-based log10 loss.
    Returns dict with mean_ptanh, log10_loss, mae, and mse for diagnostics.
    """
    a = np.asarray(y_true, dtype=float)
    b = np.asarray(y_pred, dtype=float)
    if a.shape != b.shape or a.size == 0:
        return {"mean_ptanh": float("nan"), "log10_loss": float("nan"), "mae": float("nan"), "mse": float("nan")}

    # Compute reference std: rolling with fallback to global
    try:
        ref_std = pd.Series(a).rolling(window=window, min_periods=max(2, window // 2)).std().to_numpy()
    except (AttributeError, ValueError, RuntimeError):
        ref_std = np.full_like(a, np.nan)

    # Fallback/repair: replace non-finite or non-positive entries with a positive global std
    global_std = float(np.nanstd(a))
    if not np.isfinite(global_std) or global_std <= 0:
        alt = float(np.nanstd(b))
        global_std = alt if (np.isfinite(alt) and alt > 0) else 1.0
    ref_std = np.where(~np.isfinite(ref_std) | (ref_std <= 0), global_std, ref_std)

    # Core ZPTAE computation
    z = np.abs(a - b) / (ref_std + eps)
    pt = np.tanh(np.power(z, float(p)))
    with np.errstate(invalid="ignore"):
        mean_pt = float(np.nanmean(pt))

    # Baseline metrics for fallbacks/telemetry
    mae = float(np.nanmean(np.abs(a - b))) if a.size else float("nan")
    mse = float(np.nanmean((a - b) ** 2)) if a.size else float("nan")

    # Prefer ZPTAE if finite; otherwise fall back to log10(MAE)
    if not np.isfinite(mean_pt):
        l10 = float(np.log10(max(mae, eps))) if np.isfinite(mae) else float("nan")
    else:
        l10 = float(np.log10(max(mean_pt, eps)))

    return {"mean_ptanh": mean_pt, "log10_loss": l10, "mae": mae, "mse": mse}


def _parse_cadence(s: Optional[str]) -> int:
    if not s:
        return 3600
    s2 = s.strip().lower()
    try:
        if s2.endswith("h"):
            return int(float(s2[:-1]) * 3600)
        if s2.endswith("m"):
            return int(float(s2[:-1]) * 60)
        return int(float(s2))
    except (ValueError, TypeError):
        return 3600


def _load_cadence_from_config(root_dir: str) -> int:
    cfg_path = os.path.join(root_dir, "config", "pipeline.yaml")
    if yaml and os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            if isinstance(cfg, dict):
                sch = cfg.get("schedule", {}) or {}
                cad = sch.get("cadence")
                return _parse_cadence(cad)
        except (OSError, IOError, ValueError, TypeError):
            return 3600
    return 3600


def _window_start_utc(now: Optional[pd.Timestamp] = None, cadence_s: int = 3600) -> pd.Timestamp:
    # Use timezone-aware UTC now; avoid tz_localize on possibly tz-aware objects
    now_dt = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now).tz_convert("UTC")
    epoch = int(now_dt.timestamp())
    start_epoch = (epoch // cadence_s) * cadence_s
    return pd.Timestamp(start_epoch, unit="s", tz="UTC")


def _has_submitted_this_hour(log_path: str, window_timestamp: pd.Timestamp) -> bool:
    try:
        if not os.path.exists(log_path):
            return False
        import csv as _csv
        ts_str = window_timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(log_path, "r", encoding="utf-8") as fh:
            r = _csv.DictReader(fh)
            for row in r:
                if (row.get("timestamp_utc") or "").strip() == ts_str:
                    if (row.get("success", "").strip().lower() in ("true", "1")):
                        return True
    except (OSError, IOError, ValueError):
        return False
    return False


def _resolve_wallet_for_logging(root_dir: str) -> Optional[str]:
    env_wallet = os.getenv("ALLORA_WALLET_ADDR", "").strip()
    if env_wallet:
        return env_wallet
    # last nonce cache
    try:
        ln_path = os.path.join(root_dir, ".last_nonce.json")
        if os.path.exists(ln_path):
            with open(ln_path, "r", encoding="utf-8") as f:
                j = json.load(f)
            aw = j.get("address")
            if isinstance(aw, str) and aw.strip():
                return aw.strip()
    except (OSError, IOError, json.JSONDecodeError):
        pass
    # from CSV
    try:
        csv_path = os.path.join(root_dir, "submission_log.csv")
        if os.path.exists(csv_path):
            import csv as _csv
            last_wallet: Optional[str] = None
            with open(csv_path, "r", encoding="utf-8") as fh:
                r = _csv.DictReader(fh)
                for row in r:
                    w = (row.get("wallet") or "").strip()
                    if w and w.lower() != "null":
                        last_wallet = w
            return last_wallet
    except (OSError, IOError, ValueError):
        pass
    return None


def _guard_already_submitted_this_window(root_dir: str, cadence_s: int, wallet: Optional[str]) -> bool:
    ws = _window_start_utc(cadence_s=cadence_s)
    lock_path = os.path.join(root_dir, ".submission_lock.json")
    try:
        if os.path.exists(lock_path):
            with open(lock_path, "r", encoding="utf-8") as f:
                j = json.load(f)
            last_ws = j.get("last_window_start")
            last_wallet = j.get("wallet")
            if last_ws:
                try:
                    _t = pd.Timestamp(last_ws)
                    _t = _t.tz_localize("UTC") if getattr(_t, "tzinfo", None) is None else _t.tz_convert("UTC")
                except Exception:
                    _t = None
            else:
                _t = None
            if _t is not None and _t == ws:
                if (not wallet) or (not last_wallet) or (wallet == last_wallet):
                    # Double-check CSV has a success row for this hour; if not, don't block
                    csv_path_chk = os.path.join(root_dir, "submission_log.csv")
                    if _has_submitted_this_hour(csv_path_chk, ws):
                        return True
    except (OSError, IOError, json.JSONDecodeError, ValueError):
        pass
    # CSV success row fast-path
    csv_path = os.path.join(root_dir, "submission_log.csv")
    try:
        if _has_submitted_this_hour(csv_path, ws):
            return True
    except (OSError, IOError, ValueError, RuntimeError, TypeError):  # best-effort
        pass
    return False


def _update_window_lock(root_dir: str, cadence_s: int, wallet: Optional[str]) -> None:
    try:
        ws = _window_start_utc(cadence_s=cadence_s)
        payload = {"last_window_start": ws.strftime("%Y-%m-%dT%H:%M:%SZ"), "wallet": wallet}
        with open(os.path.join(root_dir, ".submission_lock.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except (OSError, IOError, ValueError, TypeError):
        pass


def _log_submission(
    root_dir: str,
    window_dt_utc: pd.Timestamp,
    topic_id: int,
    value: Optional[float],
    wallet: Optional[str],
    nonce: Optional[int],
    tx_hash: Optional[str],
    success: bool,
    exit_code: int,
    status: str,
    log10_loss: Optional[float] = None,
    score: Optional[float] = None,
    reward: Optional[Any] = None,
) -> None:
    csv_path = os.path.join(root_dir, "submission_log.csv")
    ensure_submission_log_schema(csv_path)
    normalize_submission_log_file(csv_path)
    try:
        # Write a single row in canonical order via dict API
        # Helper to allow a string like "pending" for reward while keeping numerics numeric
        def _num_or_str(x: Any) -> Any:
            if x is None:
                return None
            if isinstance(x, (int, float)):
                try:
                    fx = float(x)
                    return fx if np.isfinite(fx) else None
                except Exception:
                    return None
            if isinstance(x, str):
                s = x.strip()
                if s == "":
                    return None
                # if it's numeric-looking, cast; else leave as string (e.g., "pending")
                try:
                    fx = float(s)
                    return fx if np.isfinite(fx) else s
                except Exception:
                    return s
            return None

        row: Dict[str, Any] = {
            "timestamp_utc": window_dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "topic_id": int(topic_id),
            "value": float(value) if value is not None else None,
            "wallet": wallet,
            "nonce": int(nonce) if isinstance(nonce, int) else None,
            "tx_hash": tx_hash,
            "success": bool(success),
            "exit_code": int(exit_code),
            "status": str(status),
            "log10_loss": float(log10_loss) if (log10_loss is not None) else None,
            "score": float(score) if (score is not None) else None,
            "reward": _num_or_str(reward),
        }
        log_submission_row(csv_path, row)
    except (OSError, IOError, ValueError, TypeError, RuntimeError):
        pass


def _current_block_height(timeout: int = 15) -> Optional[int]:
    """Query current block height from the configured RPC via allorad status."""
    cmd = [
        "allorad", "status",
        "--node", str(DEFAULT_RPC),
        "--output", "json",
        "--trace",
    ]
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        out = (cp.stdout or cp.stderr or "").strip()
        j = json.loads(out)
        # common fields: result.sync_info.latest_block_height OR sync_info.latest_block_height
        try:
            h = j.get("result", {}).get("sync_info", {}).get("latest_block_height")
        except Exception:
            h = None
        if h is None:
            h = j.get("sync_info", {}).get("latest_block_height")
        if h is None and isinstance(j, dict):
            # deep search
            def _find_height(obj: Any) -> Optional[int]:
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(v, (dict, list)):
                            r = _find_height(v)
                            if r is not None:
                                return r
                        if k.endswith("latest_block_height") and isinstance(v, (str, int)):
                            try:
                                return int(v)
                            except Exception:
                                return None
                if isinstance(obj, list):
                    for it in obj:
                        r = _find_height(it)
                        if r is not None:
                            return r
                return None
            r = _find_height(j)
            if r is not None:
                return int(r)
        if h is not None:
            return int(h)
    except Exception:
        return None
    return None


# --- Topic lifecycle and emissions params helpers ---------------------------------
def _run_allorad_json(args: List[str], timeout: int = 20) -> Optional[Dict[str, Any]]:
    """Run an allorad CLI query with JSON output, --node and --trace, return parsed JSON or None.
    This is a best-effort helper and will not raise on failures."""
    cmd = ["allorad"] + [str(a) for a in args] + ["--node", str(DEFAULT_RPC), "--output", "json", "--trace"]
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        out = (cp.stdout or cp.stderr or "").strip()
        if not out:
            return None
        try:
            return cast(Dict[str, Any], json.loads(out))
        except Exception:
            # Some builds print JSON to stderr; try swapping
            try:
                return cast(Dict[str, Any], json.loads(cp.stderr or "{}"))
            except Exception:
                return None
    except FileNotFoundError:
        print("Warning: allorad CLI not found; lifecycle checks limited")
        return None
    except Exception:
        return None


def _get_emissions_params() -> Dict[str, Any]:
    j = _run_allorad_json(["q", "emissions", "params"]) or {}
    # Attempt to normalize fields
    out: Dict[str, Any] = {"raw": j}
    # epoch length could be under params.epochLength or similar
    epoch_len = None
    try:
        epoch_len = (
            j.get("params", {}).get("epochLength")
            or j.get("epochLength")
            or j.get("params", {}).get("epoch_length")
            or j.get("epoch_length")
        )
        if epoch_len is not None:
            epoch_len = int(epoch_len)
    except Exception:
        epoch_len = None
    out["epoch_length"] = epoch_len
    # ground truth lag may be in hours; attempt common keys
    gt_lag = None
    try:
        for k in ("groundTruthLag", "ground_truth_lag", "gtLag", "gt_lag"):
            v = (j.get("params", {}) or {}).get(k)
            if v is None:
                v = j.get(k)
            if v is not None:
                gt_lag = int(v)
                break
    except Exception:
        gt_lag = None
    out["ground_truth_lag"] = gt_lag
    return out


def _get_topic_info(topic_id: int) -> Dict[str, Any]:
    """Query topic status/info, normalizing effective_revenue, delegated_stake, reputers_count, weight, last_update."""

    status = _run_allorad_json(["q", "emissions", "topic-status", str(int(topic_id))]) or {}
    info = _run_allorad_json(["q", "emissions", "topic-info", str(int(topic_id))]) or {}
    fallback_topic: Dict[str, Any] = {}
    if not info:
        fallback_topic = _run_allorad_json(["q", "emissions", "topic", str(int(topic_id))]) or {}

    combined: Dict[str, Any] = {
        "topic_status": status,
        "topic_info": info,
        "topic": fallback_topic,
    }

    def _deep_find(obj: Any, keys: List[str]) -> Optional[Any]:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in keys:
                    return v
                r = _deep_find(v, keys)
                if r is not None:
                    return r
        if isinstance(obj, list):
            for it in obj:
                r = _deep_find(it, keys)
                if r is not None:
                    return r
        return None

    def _to_float(x: Any) -> Optional[float]:
        try:
            f = float(x)
            return f if np.isfinite(f) else None
        except Exception:
            try:
                # parse coin strings like "123uallo"
                s = str(x)
                num = "".join(ch for ch in s if (ch.isdigit() or ch == "."))
                if num:
                    return float(num)
            except Exception:
                return None
        return None

    eff_rev = _deep_find(combined, ["effective_revenue", "effectiveRevenue", "revenue", "effective"])
    del_stk = _deep_find(combined, ["delegated_stake", "delegatedStake", "stake_delegated"])
    reputers = _deep_find(combined, ["reputers_count", "reputersCount", "reputers", "n_reputers"])
    weight = _deep_find(combined, ["weight", "topic_weight", "score_weight"])
    last_update = _deep_find(combined, ["last_update_height", "lastUpdateHeight", "last_update_time", "lastUpdateTime"])

    out: Dict[str, Any] = {
        "raw": combined,
        "topic_status_raw": status if status else None,
        "topic_info_raw": info if info else None,
        "topic_fallback_raw": fallback_topic if fallback_topic else None,
        "effective_revenue": _to_float(eff_rev),
        "delegated_stake": _to_float(del_stk),
        "reputers_count": int(reputers) if reputers is not None else None,
        "weight": _to_float(weight),
        "last_update": last_update,
    }
    return out


def _fetch_topic_config(topic_id: int) -> Dict[str, Any]:
    """Fetch topic configuration fields using multiple queries and normalize keys to expected schema.
    Returns a dict with keys: metadata, loss_method, epoch_length, ground_truth_lag, worker_submission_window,
    p_norm, alpha_regret, allow_negative, epsilon, merit_sortition_alpha,
    active_inferer_quantile, active_forecaster_quantile, active_reputer_quantile
    (fields may be None if not present)."""
    # Try dedicated topic queries first
    j1 = _run_allorad_json(["q", "emissions", "topic", str(int(topic_id))]) or {}
    j2 = _run_allorad_json(["q", "emissions", "topic-info", str(int(topic_id))]) or {}
    merged: Dict[str, Any] = {"a": j1, "b": j2}
    def _deep_find(obj: Any, *names: str) -> Optional[Any]:
        names_l = [n for n in names if n]
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in names_l:
                    return v
                r = _deep_find(v, *names_l)
                if r is not None:
                    return r
        if isinstance(obj, list):
            for it in obj:
                r = _deep_find(it, *names_l)
                if r is not None:
                    return r
        return None
    def _to_bool(x: Any) -> Optional[bool]:
        if isinstance(x, bool):
            return x
        if isinstance(x, str):
            s = x.strip().lower()
            if s in ("true", "1", "yes", "y"): return True
            if s in ("false", "0", "no", "n"): return False
        return None
    def _to_float(x: Any) -> Optional[float]:
        try:
            f = float(x)
            return f if np.isfinite(f) else None
        except Exception:
            try:
                s = str(x)
                num = "".join(ch for ch in s if (ch.isdigit() or ch == "."))
                return float(num) if num else None
            except Exception:
                return None
    def _to_int(x: Any) -> Optional[int]:
        try:
            return int(str(x))
        except Exception:
            return None
    out: Dict[str, Any] = {
        "metadata": _deep_find(merged, "metadata", "topic_metadata", "desc"),
        "loss_method": _deep_find(merged, "loss_method", "lossMethod", "loss"),
        "epoch_length": _to_int(_deep_find(merged, "epoch_length", "epochLength")),
        "ground_truth_lag": _to_int(_deep_find(merged, "ground_truth_lag", "groundTruthLag")),
        "worker_submission_window": _to_int(_deep_find(merged, "workerSubmissionWindow", "worker_submission_window", "submission_window")),
        "p_norm": _to_float(_deep_find(merged, "p_norm", "pNorm", "pnorm")),
        "alpha_regret": _to_float(_deep_find(merged, "alpha_regret", "alphaRegret")),
        "allow_negative": _to_bool(_deep_find(merged, "allow_negative", "allowNegative")),
        "epsilon": _to_float(_deep_find(merged, "epsilon", "eps", "epsilon_small")),
        "merit_sortition_alpha": _to_float(_deep_find(merged, "merit_sortition_alpha", "meritSortitionAlpha")),
        "active_inferer_quantile": _to_float(_deep_find(merged, "active_inferer_quantile", "activeInfererQuantile")),
        "active_forecaster_quantile": _to_float(_deep_find(merged, "active_forecaster_quantile", "activeForecasterQuantile")),
        "active_reputer_quantile": _to_float(_deep_find(merged, "active_reputer_quantile", "activeReputerQuantile")),
        "raw": merged,
    }
    return out


def _validate_topic_creation_and_funding(topic_id: int, expected: Dict[str, Any]) -> Dict[str, Any]:
    """Validate that the topic exists, has sane parameters aligned with expectations, and is funded.
    Returns a result dict: { ok: bool, funded: bool, mismatches: [..], fields: {..}, info: {..} } and prints concise reasons.
    This is a pre-flight compliance check; we do not tx-create topics here."""
    spec = _fetch_topic_config(topic_id)
    info = _get_topic_info(topic_id)
    mismatches: List[str] = []
    # ID check
    try:
        if int(expected.get("topic_id", topic_id)) != int(topic_id):
            mismatches.append("topic_id_mismatch")
    except Exception:
        pass
    # Metadata contains
    metas = expected.get("metadata_substr") or []
    if metas and isinstance(spec.get("metadata"), str):
        txt = spec.get("metadata") or ""
        for sub in metas:
            if str(sub).lower() not in txt.lower():
                mismatches.append(f"metadata_missing:{sub}")
    # Loss method
    lm_ok = False
    lm = (spec.get("loss_method") or "").lower() if spec.get("loss_method") else ""
    exp_lm: List[str] = [s.lower() for s in (expected.get("loss_method") or [])]
    if lm and exp_lm:
        lm_ok = any(e in lm for e in exp_lm)
        if not lm_ok:
            mismatches.append(f"loss_method:{lm}")
    # p-norm
    pn = spec.get("p_norm")
    if pn is not None and expected.get("p_norm") is not None and abs(float(pn) - float(expected["p_norm"])) > 1e-6:
        mismatches.append(f"p_norm:{pn}")
    # allow_negative
    an = spec.get("allow_negative")
    if an is not None and expected.get("allow_negative") is not None and bool(an) != bool(expected["allow_negative"]):
        mismatches.append(f"allow_negative:{an}")
    # presence checks
    if expected.get("require_epoch_length") and not spec.get("epoch_length"):
        mismatches.append("missing:epoch_length")
    if expected.get("require_ground_truth_lag") and not spec.get("ground_truth_lag"):
        mismatches.append("missing:ground_truth_lag")
    if expected.get("require_worker_submission_window") and not spec.get("worker_submission_window"):
        mismatches.append("missing:worker_submission_window")
    # Funding / incentives check (effective_revenue > 0)
    funded = False
    try:
        eff = info.get("effective_revenue")
        funded = bool(eff is not None and float(eff) > 0.0)
    except Exception:
        funded = False
    ok = (len(mismatches) == 0) and funded
    result = {
        "ok": bool(ok),
        "funded": bool(funded),
        "mismatches": mismatches,
        "fields": spec,
        "info": info,
    }
    return result


def _get_weights_rank(topic_id: int) -> Tuple[Optional[int], Optional[int]]:
    """Return (rank, total) by weight for topic_id if available."""
    j = _run_allorad_json(["q", "emissions", "topics"]) or {}
    # look for a list with items having id and weight
    items: List[Dict[str, Any]] = []
    def _collect(obj: Any):
        nonlocal items
        if isinstance(obj, list):
            for it in obj:
                if isinstance(it, dict) and ("id" in it or "topic_id" in it) and ("weight" in it or "topic_weight" in it):
                    items.append(it)
                else:
                    _collect(it)
        elif isinstance(obj, dict):
            for v in obj.values():
                _collect(v)
    _collect(j)
    if not items:
        return None, None
    def _get_weight(d: Dict[str, Any]) -> float:
        v = d.get("weight") or d.get("topic_weight")
        try:
            return float(v)
        except Exception:
            try:
                s = str(v)
                num = "".join(ch for ch in s if (ch.isdigit() or ch == "."))
                return float(num) if num else 0.0
            except Exception:
                return 0.0
    items_sorted = sorted(items, key=_get_weight, reverse=True)
    total = len(items_sorted)
    rank = None
    for i, it in enumerate(items_sorted, start=1):
        tid = it.get("id") or it.get("topic_id")
        try:
            if int(tid) == int(topic_id):
                rank = i
                break
        except Exception:
            continue
    return (rank, total)


def _get_unfulfilled_nonces_count(topic_id: int) -> Optional[int]:
    j = _run_allorad_json(["q", "emissions", "unfulfilled-nonces", str(int(topic_id))])
    if not j:
        return None
    # Try common shapes
    for k in ("count", "unfulfilled_count", "unfulfilledNonces", "nonces"):
        v = j.get(k)
        if v is not None:
            try:
                if isinstance(v, list):
                    return int(len(v))
                return int(v)
            except Exception:
                continue
    # deep count list length
    def _first_list(o: Any) -> Optional[int]:
        if isinstance(o, list):
            return len(o)
        if isinstance(o, dict):
            for vv in o.values():
                r = _first_list(vv)
                if r is not None:
                    return r
        return None
    return _first_list(j)


def _compute_lifecycle_state(topic_id: int) -> Dict[str, Any]:
    params = _get_emissions_params()
    info = _get_topic_info(topic_id)
    rank, total = _get_weights_rank(topic_id)
    unfulfilled = _get_unfulfilled_nonces_count(topic_id)
    epoch_len = params.get("epoch_length")
    # Active criteria: effective revenue and delegated stake positive; reputers >=1
    eff = info.get("effective_revenue")
    stk = info.get("delegated_stake")
    reps = info.get("reputers_count")
    inactive_reasons: List[str] = []
    inactive_codes: List[str] = []
    if eff is None:
        inactive_reasons.append("fee revenue unavailable")
        inactive_codes.append("effective_revenue_missing")
    elif eff <= 0:
        inactive_reasons.append("fee revenue zero")
        inactive_codes.append("effective_revenue_zero")
    if stk is None:
        inactive_reasons.append("stake unavailable")
        inactive_codes.append("delegated_stake_missing")
    elif stk <= 0:
        inactive_reasons.append("stake too low")
        inactive_codes.append("delegated_stake_non_positive")
    if reps is None:
        inactive_reasons.append("reputers missing")
        inactive_codes.append("reputers_missing")
    elif reps < 1:
        inactive_reasons.append("reputers missing")
        inactive_codes.append("reputers_below_minimum")

    is_active = len(inactive_codes) == 0
    # Churnable criteria: at least one epoch elapsed since last update and sufficiently high weight rank
    # We approximate 'since last update' using block height and epoch length if available.
    is_churnable = False
    reason_churn = []
    if epoch_len and isinstance(info.get("last_update"), (int, float, str)):
        try:
            last_up = int(str(info.get("last_update")))
        except Exception:
            last_up = None
        cur_h = _current_block_height() or None
        if last_up is not None and cur_h is not None and cur_h - last_up >= int(epoch_len):
            is_churnable = True
        else:
            reason_churn.append("epoch_not_elapsed")
    else:
        # If we can't determine precisely, remain conservative
        reason_churn.append("missing_epoch_or_last_update")
    # Weight rank gating: require topic to be within top half by weight when available
    if rank is not None and total:
        if rank <= max(1, total // 2):
            pass
        else:
            is_churnable = False
            reason_churn.append(f"low_weight_rank({rank}/{total})")
    # Rewardable: no unfulfilled nonces suggests requests/fulfillments cleared; heuristic
    is_rewardable = (unfulfilled is not None and int(unfulfilled) == 0)
    return {
        "params": params,
        "info": info,
        "weight_rank": rank,
        "weight_total": total,
        "unfulfilled": unfulfilled,
        "is_active": bool(is_active),
        "inactive_reasons": inactive_reasons,
        "inactive_reason_codes": inactive_codes,
        "is_churnable": bool(is_churnable),
        "is_rewardable": bool(is_rewardable),
        "activity_snapshot": {
            "effective_revenue": eff,
            "delegated_stake": stk,
            "reputers_count": reps,
        },
        "churn_reasons": reason_churn,
    }


def _post_submit_backfill(root_dir: str, tail: int = 20, attempts: int = 3, delay_s: float = 2.0) -> None:
    """After a successful submit, try to backfill score/reward by running tools/refresh_scores.py.
    Non-fatal on failures; best-effort with a few short retries for eventual consistency."""
    try:
        script = os.path.join(root_dir, "tools", "refresh_scores.py")
        if not os.path.exists(script):
            return
        csv_path = os.path.join(root_dir, "submission_log.csv")
        rest_base = _derive_rest_base_from_rpc(DEFAULT_RPC)
        for _ in range(max(1, int(attempts))):
            cmd = [
                sys.executable, script,
                "--csv", csv_path,
                "--rest", str(rest_base),
                "--tail", str(int(tail)),
            ]
            try:
                cp = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
                out = (cp.stdout or cp.stderr or "").strip()
                if out:
                    print(f"[refresh_scores] {out.splitlines()[-1]}")
            except Exception:
                pass
            time.sleep(float(delay_s))
    except Exception:
        # Never raise from a post-submit refresher
        pass

async def _submit_with_sdk(topic_id: int, value: float, api_key: str, timeout_s: int, max_retries: int, root_dir: str, pre_log10_loss: Optional[float]) -> int:
    try:
        from allora_sdk.worker import AlloraWorker as WorkerCls  # type: ignore
    except ImportError as e:
        print("ERROR: allora-sdk is required. Install with 'python -m pip install -U allora-sdk'.", file=sys.stderr)
        print(f"Detail: {e}", file=sys.stderr)
        return 1

    def run_fn(_: int) -> float:
        return float(value)

    cadence_s = _load_cadence_from_config(root_dir)
    attempt = 0
    last_loss: Optional[float] = None
    last_score: Optional[float] = None
    last_reward: Optional[float] = None
    last_status: Optional[str] = None
    last_nonce: Optional[int] = None
    last_tx: Optional[str] = None
    intended_env = os.getenv("ALLORA_WALLET_ADDR", "").strip() or None
    wallet_str: Optional[str] = intended_env

    def _query_ema_score(topic: int, wallet: Optional[str], retries: int = 2, delay_s: float = 2.0, timeout: int = 15) -> Optional[float]:
        """Best-effort query of EMA score via allorad CLI. Returns float or None on failure.
        Tries JSON parsing first, then regex fallback. Retries a couple times for eventual consistency.
        """
        if not wallet:
            return None
        cmd = [
            "allorad", "q", "emissions", "inferer-score-ema", str(int(topic)), str(wallet),
            "--node", str(DEFAULT_RPC), "--chain-id", str(CHAIN_ID), "--output", "json", "--trace",
        ]
        def _try_once() -> Optional[float]:
            try:
                cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            except FileNotFoundError:
                return None
            except Exception:
                return None
            out = (cp.stdout or "").strip()
            if cp.returncode != 0 and not out:
                out = (cp.stderr or "").strip()
            # Attempt JSON parse
            try:
                j = json.loads(out)
                def _find_num(obj: Any) -> Optional[float]:
                    if isinstance(obj, (int, float)) and np.isfinite(obj):
                        return float(obj)
                    if isinstance(obj, str):
                        try:
                            v = float(obj)
                            return v if np.isfinite(v) else None
                        except Exception:
                            return None
                    if isinstance(obj, dict):
                        # Prefer known keys
                        for k in ("score", "ema", "score_ema", "inferer_score_ema", "value", "result"):
                            if k in obj:
                                v = _find_num(obj[k])
                                if v is not None:
                                    return v
                        for v in obj.values():
                            r = _find_num(v)
                            if r is not None:
                                return r
                    if isinstance(obj, (list, tuple)):
                        for v in obj:
                            r = _find_num(v)
                            if r is not None:
                                return r
                    return None
                val = _find_num(j)
                if val is not None and np.isfinite(val):
                    return float(val)
            except Exception:
                pass
            # Regex fallback
            m = re.search(r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", out)
            if m:
                try:
                    v = float(m.group(1))
                    return v if np.isfinite(v) else None
                except Exception:
                    return None
            return None
        # Retry loop
        for i in range(max(1, int(retries) + 1)):
            val = _try_once()
            if val is not None:
                return val
            try:
                time.sleep(float(delay_s))
            except Exception:
                pass
        return None

    def _query_reward_for_tx(wallet: Optional[str], tx_hash: Optional[str], denom_hint: Optional[str] = None, retries: int = 2, delay_s: float = 2.0, timeout: int = 20) -> Optional[float]:
        """Query the transaction by hash and extract reward tokens received by the wallet.
        Heuristics:
          - Inspect transfer/coin_received events with recipient==wallet
          - Parse amounts like '123uallo' (Cosmos SDK coin string), sum matching 'allo' denoms
          - Convert micro-denoms (prefix 'u') to base by dividing by 1e6
        Returns amount in base units (e.g., ALLO), or None if not found yet.
        """
        if not wallet or not tx_hash:
            return None
        cmd = ["allorad", "q", "tx", str(tx_hash), "--node", str(DEFAULT_RPC), "--output", "json", "--trace"]

        def _parse_amounts(s: str) -> float:
            # Supports comma-separated coins
            total = 0.0
            for part in re.split(r"[,\s]+", s.strip()):
                if not part:
                    continue
                m = re.match(r"^([0-9]+)([a-zA-Z/\.]+)$", part)
                if not m:
                    # Try float amount then unit
                    m2 = re.match(r"^([0-9]*\.?[0-9]+)([a-zA-Z/\.]+)$", part)
                    if not m2:
                        continue
                    amt = float(m2.group(1))
                    unit = m2.group(2)
                else:
                    amt = float(m.group(1))
                    unit = m.group(2)
                unit_low = unit.lower()
                if denom_hint and denom_hint.lower() in unit_low:
                    scale = 1e6 if unit_low.startswith("u") else 1.0
                    total += (amt / scale)
                elif "allo" in unit_low:
                    scale = 1e6 if unit_low.startswith("u") else 1.0
                    total += (amt / scale)
            return total

        def _try_once() -> Optional[float]:
            try:
                cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            except FileNotFoundError:
                return None
            except Exception:
                return None
            out = (cp.stdout or "").strip()
            if not out:
                out = (cp.stderr or "").strip()
            try:
                j = json.loads(out)
            except Exception:
                # regex amount fallback if any
                return None
            # Cosmos tx JSON usually has logs -> [ { events: [ {type, attributes:[{key,value}]} ] } ]
            try:
                logs = j.get("logs") or []
                acc = 0.0
                for lg in logs:
                    events = lg.get("events") or []
                    for ev in events:
                        et = (ev.get("type") or "").lower()
                        attrs = ev.get("attributes") or []
                        # Build a small dict of attributes
                        ad: Dict[str, List[str]] = {}
                        for a in attrs:
                            k = str(a.get("key", "")).lower()
                            v = str(a.get("value", ""))
                            ad.setdefault(k, []).append(v)
                        recipients = [r for r in ad.get("recipient", []) if r]
                        amounts = ad.get("amount", [])
                        # Both transfer and coin_received are relevant in Cosmos
                        if (et in ("transfer", "coin_received") or "reward" in et) and recipients:
                            if wallet in recipients:
                                for am in amounts:
                                    acc += _parse_amounts(am)
                if acc > 0:
                    return float(acc)
            except Exception:
                return None
            return None

        for _ in range(max(1, int(retries) + 1)):
            val = _try_once()
            if val is not None:
                return val
            try:
                time.sleep(float(delay_s))
            except Exception:
                pass
        return None

    while attempt <= max_retries:
        attempt += 1
        try:
            import inspect as _inspect
            sig = _inspect.signature(WorkerCls.__init__)
            param_names = set(sig.parameters.keys())
            kwargs: Dict[str, Any] = {"run": run_fn, "api_key": api_key, "topic_id": topic_id}
            if "chain_id" in param_names:
                kwargs["chain_id"] = CHAIN_ID
            if "rpc_url" in param_names:
                kwargs["rpc_url"] = DEFAULT_RPC
            elif "node" in param_names:
                kwargs["node"] = DEFAULT_RPC
            worker = WorkerCls(**kwargs)
        except TypeError:
            worker = WorkerCls(run_fn, api_key=api_key, topic_id=topic_id)
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            msg = str(e)
            print(f"ERROR: SDK worker initialization failed: {msg}", file=sys.stderr)
            ws = _window_start_utc(cadence_s=cadence_s)
            _log_submission(root_dir, ws, topic_id, value, wallet_str, None, None, False, 1, f"sdk_init_error: {msg}")
            if attempt <= max_retries:
                await asyncio.sleep(3.0)
                continue
            return 1

        # Best-effort: attach forecast elements if the SDK supports it via attributes/methods (XGB-only policy)
        try:
            art_dir = os.path.join(root_dir, "data", "artifacts")
            lf_path = os.path.join(art_dir, "live_forecast.json")
            forecast_elements: List[Dict[str, str]] = []
            extra_payload: Dict[str, Any] = {}
            intended_env = os.getenv("ALLORA_WALLET_ADDR", "").strip() or None
            if os.path.exists(lf_path):
                with open(lf_path, "r", encoding="utf-8") as lf:
                    meta = json.load(lf) or {}
                # Prefer xgb prediction and derive forecast=5%*abs(xgb)
                mp = cast(Dict[str, Any], meta.get("member_preds") or {})
                xgb_raw = mp.get("xgb")
                if xgb_raw is not None:
                    try:
                        xgb_val = float(xgb_raw)
                        fval = 0.05 * abs(xgb_val)
                        forecast_elements.append({"inferer": str(intended_env or ""), "value": str(fval)})
                    except Exception:
                        pass
                extra_payload = {
                    "as_of": meta.get("as_of"),
                    "topic_id": meta.get("topic_id"),
                    "weights": meta.get("weights"),
                    "member_preds": meta.get("member_preds"),
                }
            if forecast_elements:
                # Try common attribute names
                for attr in ("forecast_elements", "forecast", "_forecast_elements", "forecastElements"):
                    try:
                        setattr(worker, attr, forecast_elements)
                    except Exception:
                        continue
                # Try common setter methods
                for mname in ("set_forecast_elements", "set_forecast", "update_forecast", "attach_forecast"):
                    try:
                        m = getattr(worker, mname, None)
                        if callable(m):
                            m(forecast_elements)
                    except Exception:
                        continue
                # Attach extra_data/proof when possible
                try:
                    blob = json.dumps(extra_payload, separators=(",", ":")).encode("utf-8")
                except Exception:
                    blob = b""
                for attr in ("extra_data", "_extra_data", "forecast_extra_data"):
                    try:
                        setattr(worker, attr, blob)
                    except Exception:
                        continue
                for attr in ("proof", "_proof"):
                    try:
                        setattr(worker, attr, "")
                    except Exception:
                        continue
        except Exception:
            pass

        # Resolve wallet address for logging
        wallet_address = None
        for attr in ("wallet_address", "address", "wallet"):
            try:
                wallet_address = getattr(worker, attr, None)
                if isinstance(wallet_address, dict):
                    wallet_address = wallet_address.get("address")
                if isinstance(wallet_address, str) and wallet_address:
                    break
            except AttributeError:
                continue
        if intended_env and wallet_address and intended_env != wallet_address:
            print("Warning: ALLORA_WALLET_ADDR differs from SDK wallet; signing uses SDK key.", file=sys.stderr)
        wallet_str = wallet_address if isinstance(wallet_address, str) and wallet_address else intended_env
        print(f"Worker target chain_id={CHAIN_ID} rpc={DEFAULT_RPC}")

        loop = asyncio.get_running_loop()
        not_whitelisted = asyncio.Event()
        success_event = asyncio.Event()
        shared_success: Dict[str, Any] = {"nonce": None, "tx": None}

        class _WLHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                try:
                    msg = record.getMessage()
                except (ValueError, TypeError, AttributeError):
                    msg = str(record.msg)
                low = str(msg).lower()
                if "not whitelisted" in low:
                    try:
                        loop.call_soon_threadsafe(not_whitelisted.set)
                    except RuntimeError:
                        pass
                if "successfully submitted" in low:
                    m = re.search(r"nonce[\s:=]+(\d+)", str(msg), flags=re.IGNORECASE)
                    if m:
                        shared_success["nonce"] = int(m.group(1))
                if "transaction hash" in low:
                    m = re.search(r"([0-9A-Fa-f]{64})", str(msg))
                    if m:
                        shared_success["tx"] = m.group(1)
                        loop.call_soon_threadsafe(success_event.set)

        sdk_logger = logging.getLogger("allora_sdk")
        worker_logger = logging.getLogger("allora_sdk.worker")
        wl_handler = _WLHandler()
        sdk_logger.addHandler(wl_handler)
        worker_logger.addHandler(wl_handler)
        for lg in (sdk_logger, worker_logger):
            if lg.level > logging.INFO:
                lg.setLevel(logging.INFO)

        async def _pump(gen: Any, out_queue: "asyncio.Queue[Any]") -> None:
            try:
                async for item in gen:
                    await out_queue.put(item)
            except asyncio.CancelledError:
                return
            except (RuntimeError, ValueError) as _e:
                await out_queue.put(_e)

        gen = None
        task = None
        try:
            gen = worker.run()
            q: "asyncio.Queue[Any]" = asyncio.Queue()
            task = asyncio.create_task(_pump(gen, q))
            try:
                while True:
                    wait_timeout = None
                    if timeout_s and timeout_s > 0:
                        # No precise remaining calc needed; rely on queue timeout
                        wait_timeout = timeout_s
                    done, _ = await asyncio.wait({asyncio.create_task(q.get()), asyncio.create_task(not_whitelisted.wait()), asyncio.create_task(success_event.wait())}, timeout=wait_timeout, return_when=asyncio.FIRST_COMPLETED)
                    if not done:
                        # timed out overall
                        ws = _window_start_utc(cadence_s=cadence_s)
                        _log_submission(root_dir, ws, topic_id, value, wallet_str, last_nonce, last_tx, False, 2, "timeout", last_loss, last_score, last_reward)
                        return 2
                    for fut in done:
                        try:
                            res = fut.result()
                        except (RuntimeError, ValueError) as e_done:
                            print(f"Worker error: {e_done}", file=sys.stderr)
                            continue
                        if success_event.is_set():
                            try:
                                n = shared_success.get("nonce")
                                t = shared_success.get("tx")
                                if t:
                                    if n is not None:
                                        try:
                                            with open(os.path.join(root_dir, ".last_nonce.json"), "w", encoding="utf-8") as f:
                                                json.dump({"topic_id": topic_id, "nonce": int(n), "address": wallet_str, "ts": int(time.time())}, f)
                                        except (OSError, IOError, ValueError, TypeError):
                                            pass
                                    ws = _window_start_utc(cadence_s=cadence_s)
                                    # Populate EMA score and reward if not already provided by SDK
                                    score_final = last_score
                                    if score_final is None:
                                        score_final = _query_ema_score(topic_id, wallet_str)
                                    reward_final = last_reward
                                    if reward_final is None:
                                        reward_final = _query_reward_for_tx(wallet_str, str(t)) or "pending"
                                    _log_submission(root_dir, ws, topic_id, value, wallet_str, int(n) if isinstance(n, int) else last_nonce, str(t), True, 0, last_status or "submitted", last_loss if last_loss is not None else pre_log10_loss, score_final, reward_final)
                                    return 0
                            except (OSError, IOError, ValueError, TypeError, RuntimeError):
                                pass
                        if (res is True or res is None) and not_whitelisted.is_set():
                            ws = _window_start_utc(cadence_s=cadence_s)
                            _log_submission(root_dir, ws, topic_id, value, wallet_str, None, None, False, 3, "not_whitelisted")
                            return 3
                        result = res
                        if isinstance(result, Exception):
                            msg = str(result)
                            low = msg.lower()
                            if "not whitelisted" in low:
                                ws = _window_start_utc(cadence_s=cadence_s)
                                _log_submission(root_dir, ws, topic_id, value, wallet_str, None, None, False, 3, "not_whitelisted")
                                return 3
                            if "cannot update ema more than once per window" in low:
                                # Treat as duplicate-success for logging purposes
                                ws = _window_start_utc(cadence_s=cadence_s)
                                loss_to_log = last_loss if (last_loss is not None) else pre_log10_loss
                                _log_submission(root_dir, ws, topic_id, value, wallet_str, last_nonce, last_tx, False, 0, "duplicate_window", loss_to_log, last_score, last_reward)
                                try:
                                    _update_window_lock(root_dir, cadence_s, wallet_str)
                                except Exception:
                                    pass
                                return 0
                            else:
                                print(f"Worker error: {msg}", file=sys.stderr)
                                continue
                        nonce = None
                        tx = None
                        loss = None
                        sc = None
                        rew = None
                        status = None
                        if isinstance(result, dict):
                            d = cast(Dict[str, Any], result)
                            # direct
                            nonce = d.get("nonce") or d.get("windowNonce")
                            tx = d.get("tx_hash") or d.get("txHash") or d.get("transactionHash") or d.get("hash")
                            status = d.get("status") or d.get("message")
                            loss = d.get("log10_loss") or d.get("loss")
                            sc = d.get("score") or d.get("latest_score")
                            rew = d.get("reward") or d.get("rewards")
                            if isinstance(nonce, int):
                                last_nonce = nonce
                            if isinstance(tx, str) and tx:
                                last_tx = tx
                            if isinstance(status, str) and status:
                                last_status = status
                            if loss is not None:
                                try:
                                    last_loss = float(loss)
                                except (ValueError, TypeError):
                                    pass
                            if sc is not None:
                                try:
                                    last_score = float(sc)
                                except (ValueError, TypeError):
                                    pass
                            if rew is not None:
                                try:
                                    last_reward = float(rew)
                                except (ValueError, TypeError):
                                    pass
                            if isinstance(status, str) and ("not whitelisted" in status.lower()):
                                ws = _window_start_utc(cadence_s=cadence_s)
                                _log_submission(root_dir, ws, topic_id, value, wallet_str, None, None, False, 3, "not_whitelisted")
                                return 3
                        if not_whitelisted.is_set():
                            ws = _window_start_utc(cadence_s=cadence_s)
                            _log_submission(root_dir, ws, topic_id, value, wallet_str, None, None, False, 3, "not_whitelisted")
                            return 3
                        if tx:
                            ws = _window_start_utc(cadence_s=cadence_s)
                            # If SDK didn't include a score/reward, try querying the chain
                            score_final2 = sc if sc is not None else last_score
                            if score_final2 is None:
                                score_final2 = _query_ema_score(topic_id, wallet_str)
                            reward_final2: Any = rew if rew is not None else last_reward
                            if reward_final2 is None:
                                reward_final2 = _query_reward_for_tx(wallet_str, str(tx)) or "pending"
                            _log_submission(root_dir, ws, topic_id, value, wallet_str, int(nonce) if nonce is not None else last_nonce, str(tx), True, 0, status or last_status or "submitted", (loss if loss is not None else (last_loss if last_loss is not None else pre_log10_loss)), score_final2, reward_final2)
                            return 0
                        else:
                            continue
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        except asyncio.CancelledError:
            ws = _window_start_utc(cadence_s=cadence_s)
            _log_submission(root_dir, ws, topic_id, value, wallet_str, last_nonce, last_tx, False, 2, "cancelled", last_loss, last_score, last_reward)
            return 2
        except (RuntimeError, ValueError, OSError, TimeoutError) as e:
            msg = str(e)
            if "cannot update ema more than once per window" in msg.lower():
                ws = _window_start_utc(cadence_s=cadence_s)
                # If SDK didn't provide a loss, fall back to precomputed metric for traceability
                loss_to_log = last_loss if (last_loss is not None) else pre_log10_loss
                _log_submission(root_dir, ws, topic_id, value, wallet_str, last_nonce, last_tx, False, 0, "duplicate_window", loss_to_log, last_score, last_reward)
                # Ensure any background polling task is cancelled before exiting
                try:
                    if task is not None:
                        task.cancel()
                        await asyncio.sleep(0)  # yield to cancellation
                except Exception:
                    pass
                try:
                    _update_window_lock(root_dir, cadence_s, wallet_str)
                except Exception:
                    pass
                return 0
            if "not whitelisted" in msg.lower():
                ws = _window_start_utc(cadence_s=cadence_s)
                _log_submission(root_dir, ws, topic_id, value, wallet_str, last_nonce, last_tx, False, 3, "not_whitelisted", last_loss, last_score, last_reward)
                return 3
            print(f"ERROR: SDK submission failed: {msg}", file=sys.stderr)
            ws = _window_start_utc(cadence_s=cadence_s)
            _log_submission(root_dir, ws, topic_id, value, wallet_str, last_nonce, last_tx, False, 1, f"sdk_error: {msg}", last_loss, last_score, last_reward)
        if attempt <= max_retries:
            await asyncio.sleep(3.0)
    ws = _window_start_utc(cadence_s=cadence_s)
    _log_submission(root_dir, ws, topic_id, value, wallet_str, last_nonce, last_tx, False, 2, "timeout", last_loss, last_score, last_reward)
    return 2


async def _submit_with_client_xgb(topic_id: int, xgb_val: float, root_dir: str, pre_log10_loss: Optional[float], force_submit: bool = False) -> int:
    """Submit using emissions client and ONLY xgb prediction for both inference and forecast.
    - inference.value := xgb_val (already computed live prediction)
    - forecast.value := 0.05 * abs(xgb_val) (dummy uncertainty)
    Ensures forecast is non-null without relying on artifacts on disk.
    """
    # Forecast value: ±5% dummy variance (use magnitude)
    try:
        xgb_val = float(xgb_val)
    except Exception:
        print("ERROR: live xgb value is not numeric", file=sys.stderr)
        ws = _window_start_utc(cadence_s=_load_cadence_from_config(root_dir))
        _log_submission(root_dir, ws, topic_id, None, _resolve_wallet_for_logging(root_dir), None, None, False, 1, "xgb_not_numeric", pre_log10_loss)
        return 1
    forecast_val = 0.05 * abs(xgb_val)

    # Resolve wallet (env/log placeholder until we construct LocalWallet below)
    wallet = os.getenv("ALLORA_WALLET_ADDR", "").strip() or _resolve_wallet_for_logging(root_dir)

    # Resolve nonce helpers. We'll poll for the worker window to open via can-submit,
    # then select the fresh unfulfilled nonce for this topic. Fallback to current height.
    def _query_unfulfilled_nonce(topic: int, wal: Optional[str], timeout: int = 20) -> Optional[int]:
        cmd = [
            "allorad", "q", "emissions", "unfulfilled-worker-nonces", str(int(topic)),
            "--node", str(DEFAULT_RPC), "--output", "json", "--trace",
        ]
        try:
            cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return None
        except Exception:
            return None
        out = (cp.stdout or cp.stderr or "").strip()
        try:
            j = json.loads(out)
        except Exception:
            # Try to extract first integer-looking nonce
            m = re.search(r"\b(\d{6,})\b", out)
            return int(m.group(1)) if m else None
        # Heuristic: look for fields like nonces, block_heights, or wallet-keyed maps
        # Prefer entries for our wallet when present
        def _find_nonces(obj: Any) -> List[int]:
            res: List[int] = []
            if isinstance(obj, dict):
                for k, v in obj.items():
                    kl = str(k).lower()
                    if kl in ("nonces", "block_heights", "heights") and isinstance(v, (list, tuple)):
                        for it in v:
                            try:
                                res.append(int(it))
                            except Exception:
                                continue
                    # Sometimes structure is {wallet: [nonces]}
                    try:
                        if isinstance(v, (list, tuple)) and wal and (wal in str(k)):
                            for it in v:
                                try:
                                    res.append(int(it))
                                except Exception:
                                    continue
                    except Exception:
                        pass
                    res.extend(_find_nonces(v))
            elif isinstance(obj, list):
                for it in obj:
                    res.extend(_find_nonces(it))
            return res
        arr = _find_nonces(j)
        if arr:
            # choose the most recent (max)
            try:
                return max(int(x) for x in arr)
            except Exception:
                return None
        return None

    def _query_topic_last_worker_commit_nonce(topic: int, timeout: int = 15) -> Optional[int]:
        cmd = [
            "allorad", "q", "emissions", "topic-last-worker-commit", str(int(topic)),
            "--node", str(DEFAULT_RPC), "--output", "json", "--trace",
        ]
        try:
            cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return None
        except Exception:
            return None
        out = (cp.stdout or cp.stderr or "").strip()
        try:
            j = json.loads(out)
        except Exception:
            return None
        try:
            n = j.get("last_commit", {}).get("nonce", {}).get("block_height")
            return int(n) if n is not None else None
        except Exception:
            return None

    def _can_submit_worker_payload(topic: int, wal: Optional[str], timeout: int = 10) -> Optional[bool]:
        if not wal:
            return None
        cmd = [
            "allorad", "q", "emissions", "can-submit-worker-payload", str(int(topic)), str(wal),
            "--node", str(DEFAULT_RPC), "--chain-id", str(CHAIN_ID), "--output", "json", "--trace",
        ]
        try:
            cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return None
        except Exception:
            return None
        out = (cp.stdout or cp.stderr or "").strip()
        try:
            j = json.loads(out)
            # Expected key: can_submit_worker_payload: true/false
            for k in ("can_submit_worker_payload", "canSubmit", "result", "value"):
                if k in j:
                    v = j.get(k)
                    if isinstance(v, bool):
                        return v
                    if isinstance(v, str):
                        vl = v.strip().lower()
                        if vl in ("true", "1", "yes"):
                            return True
                        if vl in ("false", "0", "no"):
                            return False
        except Exception:
            # Regex fallback
            m = re.search(r"true|false|1|0", out, flags=re.IGNORECASE)
            if m:
                s = m.group(0).lower()
                return s in ("true", "1")
        return None

    # Build REST clients and wallet first so we can derive the authoritative wallet address
    try:
        # Imports based on current installed SDK
        from allora_sdk.rpc_client.client_emissions import EmissionsTxs  # type: ignore
        from allora_sdk.rpc_client.config import AlloraNetworkConfig  # type: ignore
        from allora_sdk.rpc_client.tx_manager import TxManager  # type: ignore
        from allora_sdk.rest.cosmos_tx_v1beta1_rest_client import CosmosTxV1Beta1RestServiceClient  # type: ignore
        from allora_sdk.rest.cosmos_auth_v1beta1_rest_client import CosmosAuthV1Beta1RestQueryClient  # type: ignore
        from allora_sdk.rest.cosmos_bank_v1beta1_rest_client import CosmosBankV1Beta1RestQueryClient  # type: ignore
        from cosmpy.aerial.wallet import LocalWallet  # type: ignore

        # Resolve mnemonic from .allora_key (same file the worker uses)
        key_path = os.path.join(root_dir, ".allora_key")
        if not os.path.exists(key_path):
            raise RuntimeError(".allora_key not found; cannot construct LocalWallet for client submission")
        with open(key_path, "r", encoding="utf-8") as kf:
            mnemonic = kf.read().strip()
        if not mnemonic or len(mnemonic.split()) < 12:
            raise RuntimeError("Invalid mnemonic in .allora_key")

        wallet_obj = LocalWallet.from_mnemonic(mnemonic, prefix="allo")
        # Try to get canonical address string from wallet_obj if available
        try:
            wal_addr = getattr(wallet_obj, "address", None)
            if callable(wal_addr):
                wal_addr = wal_addr()  # some versions expose address() method
            if isinstance(wal_addr, str) and wal_addr:
                wallet = wal_addr
        except Exception:
            pass

        # Build REST clients against the REST base URL (not RPC)
        base_url = _derive_rest_base_from_rpc(DEFAULT_RPC)
        tx_client = CosmosTxV1Beta1RestServiceClient(base_url)
        auth_client = CosmosAuthV1Beta1RestQueryClient(base_url)
        bank_client = CosmosBankV1Beta1RestQueryClient(base_url)

        # Network config (fee params, chain id)
        if str(CHAIN_ID) == "allora-testnet-1":
            net_cfg = AlloraNetworkConfig.testnet()
        elif str(CHAIN_ID) == "allora-mainnet-1":
            net_cfg = AlloraNetworkConfig.mainnet()
        else:
            # Custom with provided CHAIN_ID; fallback to testnet fee params
            net_cfg = AlloraNetworkConfig(
                chain_id=str(CHAIN_ID),
                # Use REST base URL directly; some SDKs expect a gRPC-like string but TxManager relies on REST clients passed above
                url=base_url,
                websocket_url=None,
                fee_denom="uallo",
                fee_minimum_gas_price=10.0,
            )

        # Construct TxManager and EmissionsTxs
        tm = TxManager(wallet=wallet_obj, tx_client=tx_client, auth_client=auth_client, bank_client=bank_client, config=net_cfg)
        # Prefer block broadcast to get a synchronous tx response containing txhash; try multiple variants for compatibility
        def _try_set_bcast(mode: str) -> None:
            try:
                if hasattr(tm, "set_broadcast_mode") and callable(getattr(tm, "set_broadcast_mode")):
                    tm.set_broadcast_mode(mode)  # type: ignore
                elif hasattr(tm, "broadcast_mode"):
                    setattr(tm, "broadcast_mode", mode)
            except Exception:
                pass
        for m in ("block", "BROADCAST_MODE_BLOCK"):
            _try_set_bcast(m)
        # Best-effort fee defaults if supported
        for attr, val in (("gas_limit", 300000), ("gas_price", 10.0)):
            try:
                if hasattr(tm, attr):
                    setattr(tm, attr, val)  # type: ignore
            except Exception:
                pass
        txs = EmissionsTxs(tm)
    except Exception as e:
        print(f"ERROR: client-based xgb submit failed: {e}", file=sys.stderr)
        ws = _window_start_utc(cadence_s=_load_cadence_from_config(root_dir))
        _log_submission(root_dir, ws, topic_id, xgb_val if 'xgb_val' in locals() else None, wallet, None, None, False, 1, "client_submit_exception", pre_log10_loss)
        return 1

    # Wait for the worker window to open (up to ~90s), then choose the freshest nonce
    wait_deadline = time.time() + 90.0
    chosen_nonce: Optional[int] = None
    while time.time() < wait_deadline:
        can_sub = _can_submit_worker_payload(int(topic_id), wallet)
        unf = _query_unfulfilled_nonce(int(topic_id), wallet)
        # Prefer explicit unfulfilled nonce when present
        if isinstance(unf, int) and unf > 0:
            chosen_nonce = int(unf)
            break
        # If we can submit but unfulfilled list isn't populated yet, use current height
        if can_sub is True:
            h = _current_block_height()
            if isinstance(h, int) and h > 0:
                chosen_nonce = int(h)
                break
        # Sleep briefly before polling again
        try:
            await asyncio.sleep(2.0)
        except Exception:
            time.sleep(2.0)

    # Final fallback: last worker commit nonce or current height
    if chosen_nonce is None:
        chosen_nonce = (
            _query_unfulfilled_nonce(int(topic_id), wallet)
            or _current_block_height()
            or _query_topic_last_worker_commit_nonce(int(topic_id))
            or 0
        )
    nonce_h = int(chosen_nonce or 0)
    if nonce_h <= 0:
        print("Warning: could not resolve a valid worker nonce; submission may fail", file=sys.stderr)

    # Build forecast elements and extra data
    forecast_elements = [{"inferer": str(wallet or ""), "value": str(forecast_val)}]
    extra_payload = {
        "policy": "xgb_only",
        "note": "forecast=5pct_abs(xgb)",
    }
    try:
        extra_data = json.dumps(extra_payload, separators=(",", ":")).encode("utf-8")
    except Exception:
        extra_data = b""

    # Perform async insert and wait for inclusion (TxManager returns a PendingTx)
    try:
        # Some SDK versions require different broadcast modes; try a few if txhash isn't returned
        tx_hash = None
        last_tx_resp: Any = None
        def _extract_tx_hash(obj: Any, depth: int = 0) -> Optional[str]:
            if obj is None or depth > 3:
                return None
            for key in ("txhash", "hash", "tx_hash"):
                try:
                    if isinstance(obj, dict) and key in obj and isinstance(obj[key], str) and len(obj[key]) >= 64:
                        return obj[key]
                    if hasattr(obj, key):
                        val = getattr(obj, key)
                        if isinstance(val, str) and len(val) >= 64:
                            return val
                except Exception:
                    pass
            try:
                if isinstance(obj, dict) and "tx_response" in obj:
                    r = _extract_tx_hash(obj["tx_response"], depth + 1)
                    if r:
                        return r
            except Exception:
                pass
            try:
                if hasattr(obj, "tx_response"):
                    r = _extract_tx_hash(getattr(obj, "tx_response"), depth + 1)
                    if r:
                        return r
            except Exception:
                pass
            try:
                s = str(obj)
                m = re.search(r"\b([0-9A-Fa-f]{64})\b", s)
                if m:
                    return m.group(1)
            except Exception:
                pass
            return None

        broadcast_modes_to_try = ["block", "BROADCAST_MODE_BLOCK", "sync", "BROADCAST_MODE_SYNC"]
        for bmode in broadcast_modes_to_try:
            # Switch mode if possible
            try:
                if hasattr(tm, "set_broadcast_mode") and callable(getattr(tm, "set_broadcast_mode")):
                    tm.set_broadcast_mode(bmode)  # type: ignore
                elif hasattr(tm, "broadcast_mode"):
                    setattr(tm, "broadcast_mode", bmode)
            except Exception:
                pass
            # SDKs have varied argument names across versions.
            # Try with forecast_elements first; if signature mismatch, retry with forecast.
            try:
                try:
                    pending = await txs.insert_worker_payload(
                        topic_id=int(topic_id),
                        inference_value=str(xgb_val),
                        nonce=int(nonce_h),
                        forecast_elements=forecast_elements,
                        extra_data=extra_data,
                        proof="",
                    )
                except TypeError:
                    pending = await txs.insert_worker_payload(
                        topic_id=int(topic_id),
                        inference_value=str(xgb_val),
                        nonce=int(nonce_h),
                        forecast=forecast_elements,
                        extra_data=extra_data,
                        proof="",
                    )
                try:
                    last_tx_resp = await pending
                    tx_hash = _extract_tx_hash(last_tx_resp)
                except Exception:
                    # If wait failed, try to extract from pending or manager state
                    try:
                        tx_hash = tx_hash or getattr(pending, "last_tx_hash", None)
                    except Exception:
                        pass
                    try:
                        tx_hash = tx_hash or _extract_tx_hash(getattr(pending, "tx_response", None))
                    except Exception:
                        pass
                    try:
                        mgr = getattr(txs, "tx_manager", None)
                        if mgr is not None:
                            tx_hash = tx_hash or _extract_tx_hash(mgr)
                    except Exception:
                        pass
            except Exception:
                # Try next mode
                tx_hash = None
            # Stop if we have a hash
            if tx_hash:
                break
        nonce_out: Optional[int] = int(nonce_h) if nonce_h else None

        # Enrich: attempt to extract EMA score and reward from the committed tx, else fall back to queries
        def _parse_float_any(x: Any) -> Optional[float]:
            try:
                v = float(x)
                return v if np.isfinite(v) else None
            except Exception:
                return None

        def _extract_from_tx_json(txj: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
            """Parse Cosmos tx JSON for EMA score and rewards.
            Searches logs[].events for EventEMAScoresSet and transfer events.
            """
            score_val: Optional[float] = None
            reward_amt: Optional[float] = None
            logs = txj.get("logs") or []
            # Some RPCs return stringified raw_log; ignore that path here
            for lg in logs:
                events = lg.get("events") or []
                for ev in events:
                    et = str(ev.get("type", "")).lower()
                    attrs = ev.get("attributes") or []
                    # EMA score event
                    if "eventemascoresset" in et or "emascore" in et or "score" in et:
                        for a in attrs:
                            k = str(a.get("key", "")).lower()
                            if k in ("scores", "inferer_scores", "infererscores", "ema_scores", "emascores"):
                                val = a.get("value")
                                try:
                                    arr = json.loads(val)
                                    if isinstance(arr, list) and arr:
                                        sv = _parse_float_any(arr[0])
                                        if sv is not None:
                                            score_val = sv
                                except Exception:
                                    m = re.search(r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", str(val))
                                    if m:
                                        sv = _parse_float_any(m.group(1))
                                        if sv is not None:
                                            score_val = sv
                    # reward detection via coin_received/transfer with recipient==wallet
                    if et in ("coin_received", "transfer"):
                        ad: Dict[str, List[str]] = {}
                        for a in attrs:
                            k = str(a.get("key", "")).lower(); v = str(a.get("value", ""))
                            ad.setdefault(k, []).append(v)
                        recips = [r for r in ad.get("receiver", []) + ad.get("recipient", []) if r]
                        if wallet and wallet in recips:
                            for am in ad.get("amount", []):
                                for part in re.split(r"[\s,]+", am.strip()):
                                    if not part:
                                        continue
                                    m2 = re.match(r"^([0-9]*\.?[0-9]+)([a-zA-Z/\.]+)$", part)
                                    if not m2:
                                        continue
                                    amt = _parse_float_any(m2.group(1))
                                    unit = m2.group(2).lower()
                                    if amt is None:
                                        continue
                                    if "allo" in unit:
                                        scale = 1e6 if unit.startswith("u") else 1.0
                                        reward_amt = (reward_amt or 0.0) + (amt / scale)
            return score_val, reward_amt

        # Reusable EMA score query with retries (inferer role)
        def _query_ema_score_retry(topic: int, wal: Optional[str], retries: int = 3, delay_s: float = 2.0, timeout: int = 15) -> Optional[float]:
            if not wal:
                return None
            cmd = [
                "allorad", "q", "emissions", "inferer-score-ema", str(int(topic)), str(wal),
                "--node", str(DEFAULT_RPC), "--chain-id", str(CHAIN_ID), "--output", "json", "--trace",
            ]
            def _try_once() -> Optional[float]:
                try:
                    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
                except Exception:
                    return None
                out = (cp.stdout or cp.stderr or "").strip()
                try:
                    j = json.loads(out)
                    # Probe common numeric fields; otherwise deep search for first float
                    for key in ("score", "ema", "score_ema", "inferer_score_ema", "value", "result"):
                        if key in j:
                            v = _parse_float_any(j.get(key))
                            if v is not None:
                                return v
                    # Deep search
                    def _find_num(o: Any) -> Optional[float]:
                        if isinstance(o, (int, float)) and np.isfinite(o):
                            return float(o)
                        if isinstance(o, str):
                            return _parse_float_any(o)
                        if isinstance(o, dict):
                            for v in o.values():
                                r = _find_num(v)
                                if r is not None:
                                    return r
                        if isinstance(o, (list, tuple)):
                            for v in o:
                                r = _find_num(v)
                                if r is not None:
                                    return r
                        return None
                    return _find_num(j)
                except Exception:
                    m = re.search(r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", out)
                    if m:
                        return _parse_float_any(m.group(1))
                return None
            for _ in range(max(1, int(retries) + 1)):
                val = _try_once()
                if val is not None:
                    return val
                try:
                    time.sleep(float(delay_s))
                except Exception:
                    pass
            return None

        score_final: Optional[float] = None
        reward_final: Any = None
        chain_code: Optional[int] = None
        chain_codespace: Optional[str] = None
        if tx_hash:
            # Query the tx via CLI for full event logs; allow a couple retries for indexers to catch up
            for _ in range(3):
                try:
                    cp = subprocess.run([
                        "allorad", "q", "tx", str(tx_hash), "--node", str(DEFAULT_RPC), "--output", "json", "--trace"
                    ], capture_output=True, text=True, timeout=25)
                    out = (cp.stdout or cp.stderr or "").strip()
                    j = json.loads(out)
                    # Record chain result code
                    try:
                        chain_code = int(j.get("code", 0))
                    except Exception:
                        chain_code = 0
                    chain_codespace = j.get("codespace") or ""
                    sc, rw = _extract_from_tx_json(j)
                    if score_final is None:
                        score_final = sc
                    if reward_final is None:
                        reward_final = rw
                    if score_final is not None and reward_final is not None:
                        break
                except Exception:
                    pass
                try:
                    time.sleep(2.0)
                except Exception:
                    pass
        # Best-effort fallback for score via EMA query if not in the tx logs yet
        if score_final is None and wallet:
            score_final = _query_ema_score_retry(int(topic_id), wallet, retries=4, delay_s=2.0, timeout=15)
        # Reward fallback via tx query helper if not already populated
        if reward_final is None and tx_hash:
            try:
                # Re-use the tx query above if needed; otherwise mark pending
                reward_final = "pending"
            except Exception:
                reward_final = "pending"

        # Determine success based on chain response code (0 = success)
        success_flag = bool(chain_code == 0) if (chain_code is not None and tx_hash) else bool(tx_hash)
        exit_code_out = 0 if success_flag else 1
        # If score not yet available, note 'score=pending' in status for transparency
        pending_note = "; score=pending" if (success_flag and score_final is None) else ""
        status_msg = ("submitted" if success_flag else (f"chain_error:{chain_codespace}/{chain_code}" if tx_hash else "no_tx_hash")) + pending_note

        # Log success/failure with enriched details
        ws = _window_start_utc(cadence_s=_load_cadence_from_config(root_dir))
        _log_submission(
            root_dir,
            ws,
            topic_id,
            xgb_val,
            wallet,
            int(nonce_out) if nonce_out is not None else None,
            str(tx_hash) if tx_hash else None,
            success_flag,
            exit_code_out,
            status_msg,
            pre_log10_loss,
            score_final,
            reward_final if (reward_final is not None) else "pending",
        )
        # Console diagnostics to aid wrapper parsing and human review
        try:
            nonce_dbg = int(nonce_out) if nonce_out is not None else None
        except Exception:
            nonce_dbg = None
        print(f"submit(client): nonce={nonce_dbg} tx_hash={tx_hash or 'null'} code={(chain_code if chain_code is not None else 'n/a')} status={status_msg}")
        if not tx_hash:
            # Print a short hint to aid future debugging without leaking sensitive data
            try:
                print("submit(client): hint=hash_missing_check_broadcast_mode_and_signature")
            except Exception:
                pass
        if score_final is not None:
            print(f"submit(client): ema_score={score_final}")
        if isinstance(reward_final, (int, float)):
            print(f"submit(client): reward={reward_final}")
        # Cache last nonce
        try:
            with open(os.path.join(root_dir, ".last_nonce.json"), "w", encoding="utf-8") as f:
                json.dump({"topic_id": topic_id, "nonce": int(nonce_out or 0), "address": wallet, "ts": int(time.time())}, f)
        except Exception:
            pass
        # Trigger fallback when no tx hash or chain error, else success
        if (not tx_hash) or (chain_code is not None and chain_code != 0):
            return 2
        return 0
    except Exception as e:
        print(f"ERROR: client-based xgb submit failed: {e}", file=sys.stderr)
        ws = _window_start_utc(cadence_s=_load_cadence_from_config(root_dir))
        _log_submission(root_dir, ws, topic_id, xgb_val if 'xgb_val' in locals() else None, wallet, None, None, False, 1, "client_submit_exception", pre_log10_loss)
        return 1


def _parse_submission_helper_output(stdout: str, stderr: str) -> Tuple[Optional[str], Optional[int], Optional[float], Optional[float], Optional[str]]:
    """Best-effort extraction of tx hash, nonce, score, reward, and status from helper output."""
    text = "\n".join([stdout or "", stderr or ""]).strip()
    tx_hash: Optional[str] = None
    nonce: Optional[int] = None
    score: Optional[float] = None
    reward: Optional[float] = None
    status: Optional[str] = None

    # Try JSON lines first
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate or not (candidate.startswith("{") and candidate.endswith("}")):
            continue
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            if not tx_hash:
                for key in ("tx_hash", "txHash", "txhash", "transactionHash", "hash"):
                    val = obj.get(key)
                    if isinstance(val, str) and len(val) >= 40:
                        tx_hash = val
                        break
            if nonce is None:
                for key in ("nonce", "windowNonce", "block_height", "height"):
                    val = obj.get(key)
                    try:
                        if isinstance(val, str) and val.isdigit():
                            nonce = int(val)
                            break
                        if isinstance(val, (int, float)):
                            nonce = int(val)
                            break
                    except Exception:
                        continue
            if score is None:
                for key in ("score", "ema_score", "inferer_score", "log10_score"):
                    if key in obj:
                        val = obj.get(key)
                        try:
                            score = float(val)
                        except Exception:
                            score = None
                        break
            if reward is None:
                for key in ("reward", "rewards", "amount"):
                    if key in obj:
                        val = obj.get(key)
                        try:
                            reward = float(val)
                        except Exception:
                            reward = None
                        break
            if not status:
                for key in ("status", "message", "result"):
                    val = obj.get(key)
                    if isinstance(val, str) and val:
                        status = val
                        break

    if not tx_hash:
        m = re.search(r"\b[0-9A-Fa-f]{64}\b", text)
        if m:
            tx_hash = m.group(0)

    if nonce is None:
        m = re.search(r"nonce[^0-9]*(\d{3,})", text, flags=re.IGNORECASE)
        if m:
            try:
                nonce = int(m.group(1))
            except Exception:
                nonce = None

    if score is None:
        m = re.search(r"score[^0-9-]*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)", text, flags=re.IGNORECASE)
        if m:
            try:
                score = float(m.group(1))
            except Exception:
                score = None

    if reward is None:
        m = re.search(r"reward[^0-9-]*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)", text, flags=re.IGNORECASE)
        if m:
            try:
                reward = float(m.group(1))
            except Exception:
                reward = None

    if not status and text:
        # Use the last non-empty line as a human-readable status hint
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines:
            status = lines[-1][:128]

    return tx_hash, nonce, score, reward, status


def _submit_via_external_helper(
    topic_id: int,
    value: float,
    root_dir: str,
    pre_log10_loss: Optional[float],
    submit_timeout: int,
) -> Optional[Tuple[int, bool]]:
    """Attempt submission via submit_prediction.py (if available) or similar helper.

    Returns Optional[(exit_code, success_flag)]. When None, no helper was executed.
    """
    candidates = [
        os.path.join(root_dir, "submit_prediction.py"),
        os.path.join(root_dir, "scripts", "submit_prediction.py"),
        os.path.join(root_dir, "tools", "submit_prediction.py"),
    ]
    timeout_bound = max(0, int(submit_timeout or 0))
    wallet = _resolve_wallet_for_logging(root_dir)
    cadence_s = _load_cadence_from_config(root_dir)
    env = os.environ.copy()
    env.setdefault("ALLORA_TOPIC_ID", str(topic_id))
    env.setdefault("ALLORA_PREDICTION_VALUE", str(value))

    for candidate in candidates:
        if not os.path.exists(candidate):
            continue
        cmd = [sys.executable, candidate, "--topic-id", str(topic_id), "--source", "model"]
        if "--mode" not in cmd:
            cmd.extend(["--mode", "cli"])
        if timeout_bound > 0:
            cmd.extend(["--timeout", str(timeout_bound)])
        try:
            cp = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                timeout=(timeout_bound + 30) if timeout_bound > 0 else None,
            )
        except subprocess.TimeoutExpired:
            ws = _window_start_utc(cadence_s=cadence_s)
            _log_submission(
                root_dir,
                ws,
                topic_id,
                value,
                wallet,
                None,
                None,
                False,
                124,
                "submit_helper_timeout",
                pre_log10_loss,
            )
            return (124, False)
        except FileNotFoundError:
            continue
        except Exception as exc:
            ws = _window_start_utc(cadence_s=cadence_s)
            _log_submission(
                root_dir,
                ws,
                topic_id,
                value,
                wallet,
                None,
                None,
                False,
                1,
                f"submit_helper_error:{exc}",
                pre_log10_loss,
            )
            return (1, False)

        tx_hash, nonce, score, reward, status = _parse_submission_helper_output(cp.stdout, cp.stderr)
        success = bool(cp.returncode == 0 and tx_hash)
        exit_code = 0 if success else (cp.returncode if cp.returncode != 0 else 1)
        ws = _window_start_utc(cadence_s=cadence_s)
        _log_submission(
            root_dir,
            ws,
            topic_id,
            value,
            wallet,
            nonce,
            tx_hash,
            success,
            exit_code,
            status or ("submit_helper_success" if success else f"submit_helper_rc={cp.returncode}"),
            pre_log10_loss,
            score,
            reward if reward is not None else ("pending" if success else None),
        )
        if not success:
            print(
                f"submit(helper): helper at {candidate} exited with rc={cp.returncode}; stdout={cp.stdout!r} stderr={cp.stderr!r}",
                file=sys.stderr,
            )
        return (exit_code, success)

    return None


def sleep_until_top_of_hour_utc() -> None:
    """Sleep until the next top of hour in UTC."""
    import time
    now = time.time()
    next_hour = ((now // 3600) + 1) * 3600
    sleep_time = next_hour - now
    if sleep_time > 0:
        print(f"Sleeping {sleep_time:.0f} seconds until top of hour UTC")
        time.sleep(sleep_time)


def _sleep_until_next_window(cadence_s: int) -> None:
    """Align to the next cadence window boundary in UTC."""
    try:
        now = pd.Timestamp.now(tz="UTC")
    except Exception:
        now = pd.Timestamp.utcnow().tz_localize("UTC")
    window_start = _window_start_utc(now=now, cadence_s=cadence_s)
    # If we are within one second of the boundary, skip sleeping
    delta = (now - window_start).total_seconds()
    if delta < 1.0 and delta >= 0.0:
        return
    next_window = window_start + pd.Timedelta(seconds=cadence_s)
    wait = (next_window - now).total_seconds()
    if wait > 0:
        logging.info(f"[loop] aligning to cadence; sleeping {wait:.1f}s until {next_window.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        try:
            time.sleep(wait)
        except Exception:
            pass


def resolve_wallet() -> None:
    """Resolve wallet address using scripts/resolve_wallet.py and set env var."""
    import subprocess
    try:
        result = subprocess.run([sys.executable, "scripts/resolve_wallet.py"], capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            wallet = result.stdout.strip()
            if wallet:
                os.environ["ALLORA_WALLET_ADDR"] = wallet
                print(f"Resolved wallet: {wallet}")
            else:
                print("Warning: resolve_wallet.py returned empty wallet")
        else:
            print(f"Warning: resolve_wallet.py failed: {result.stderr.strip()}")
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"Warning: failed to run resolve_wallet.py: {e}")


def run_pipeline(args, cfg, root_dir) -> int:
    data_cfg: Dict[str, Any] = cfg.get("data", {})
    from_month = getattr(args, "from_month", str(data_cfg.get("from_month", "2025-01")))
    sched_cfg: Dict[str, Any] = cfg.get("schedule", {})
    mode = getattr(args, "_effective_mode", str(getattr(args, "schedule_mode", None) or sched_cfg.get("mode", "single")))
    cadence = getattr(args, "_effective_cadence", str(getattr(args, "cadence", None) or sched_cfg.get("cadence", "1h")))
    start_raw = str(getattr(args, "start_utc", None) or sched_cfg.get("start", "2025-09-16T13:00:00Z"))
    end_raw = str(getattr(args, "end_utc", None) or sched_cfg.get("end", "2025-12-15T13:00:00Z"))
    topic_validation: Dict[str, Any] = {}
    topic_validation_ok = False
    topic_validation_funded = False
    topic_validation_epoch = False
    topic_validation_reason: Optional[str] = None

    def _parse_utc(ts: str) -> pd.Timestamp:
        t = pd.Timestamp(ts)
        if getattr(t, "tz", None) is None:
            return t.tz_localize("UTC")
        return t.tz_convert("UTC")

    workflow = AlloraMLWorkflow(
        data_api_key=_require_api_key(),
        tickers=["btcusd"],
        hours_needed=168,
        number_of_input_candles=168,
        target_length=168
    )
    full_data: pd.DataFrame = workflow.get_full_feature_target_dataframe(from_month=from_month)
    date_index: pd.Index = _to_naive_utc_index(pd.DatetimeIndex(pd.to_datetime(full_data.index.get_level_values("date"))))
    if len(date_index) > 0:
        _min_dt = pd.Timestamp(date_index.min(), tz="UTC")
        _max_dt = pd.Timestamp(date_index.max(), tz="UTC")
    else:
        _min_dt = None
        _max_dt = None

    # Dynamically set end_utc to the latest available timestamp in the data if not overridden
    if args.end_utc:
        end_utc = _parse_utc(args.end_utc)
    else:
        # Use the latest timestamp in the data
        if _max_dt is not None:
            end_utc = _max_dt
            configured_end = _parse_utc(end_raw)
            if end_utc < configured_end:
                print(f"WARNING: Available labeled data ends before the competition end. last_labeled={end_utc} < configured_end={configured_end}. Using effective_end={end_utc}.")
        else:
            end_utc = _parse_utc(end_raw)

    # Dynamically set as_of to latest available timestamp minus 7 days if not overridden
    if args.as_of:
        as_of = _parse_utc(args.as_of)
    elif args.as_of_now:
        try:
            as_of = pd.Timestamp.now(tz="UTC").floor(cadence or "1h")
        except (ValueError, TypeError, AttributeError):
            as_of = pd.Timestamp.now(tz="UTC").floor("1h")
    else:
        # Use latest available timestamp minus 7 days (168h)
        if _max_dt is not None:
            as_of = _max_dt - pd.Timedelta(hours=168)
            # Ensure as_of does not go before start
            if _min_dt is not None and as_of < _min_dt:
                as_of = _min_dt
        else:
            as_of = _parse_utc(end_raw)

    # Snap to cadence (hourly) to avoid off-boundary timestamps
    try:
        as_of = as_of.floor(cadence or "1h")
    except (ValueError, TypeError, AttributeError):
        as_of = as_of.floor("1h")

    # Dynamically set start_utc as before
    start_utc = _parse_utc(start_raw)

    print(f"Schedule: mode={mode} cadence={cadence} start={start_utc} end={end_utc} as_of={as_of}")

    # Validate that the selected date range does not filter out >90% of the data
    total_rows = len(full_data)
    start_naive = _to_naive_utc_ts(start_utc)
    end_naive = _to_naive_utc_ts(end_utc)
    filtered_rows = ((date_index >= start_naive) & (date_index <= end_naive)).sum()
    if total_rows > 0 and filtered_rows / total_rows < 0.1:
        print(f"ERROR: More than 90% of the available data would be filtered out by the selected date range (start={start_utc}, end={end_utc}). Aborting.", file=sys.stderr)
        print(f"[DEBUG] total_rows={total_rows}, filtered_rows={filtered_rows}", file=sys.stderr)
        sys.exit(1)

    # Topic validation and audit (moved out of abort block)
    try:
        topic_id_eff = int(DEFAULT_TOPIC_ID)
        assert topic_id_eff == int(EXPECTED_TOPIC_67["topic_id"]), "Topic ID must be 67 for this workflow"
        topic_validation = _validate_topic_creation_and_funding(topic_id_eff, EXPECTED_TOPIC_67)
        topic_validation_ok = bool(topic_validation.get("ok"))
        topic_validation_funded = bool(topic_validation.get("funded"))
        topic_fields = cast(Dict[str, Any], topic_validation.get("fields", {}) or {})
        topic_validation_epoch = bool(topic_fields.get("epoch_length"))
        mism = topic_validation.get("mismatches") or []
        if mism:
            topic_validation_reason = ",".join(str(m) for m in mism)
        elif not topic_validation_ok:
            topic_validation_reason = "topic_not_ok"
        elif not topic_validation_funded:
            topic_validation_reason = "topic_unfunded"
        elif not topic_validation_epoch:
            topic_validation_reason = "missing_epoch_length"
        else:
            topic_validation_reason = None
        # Persist audit file for VS Code AI and human review
        audit_dir = os.path.join(root_dir, "data", "artifacts", "logs")
        os.makedirs(audit_dir, exist_ok=True)
        ts_str = pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%SZ")
        with open(os.path.join(audit_dir, f"topic67_validate-{ts_str}.json"), "w", encoding="utf-8") as af:
            json.dump(topic_validation, af, indent=2)
        if not topic_validation.get("ok", False):
            # Print concise reasons; continue to train but submission will be gated later if unfunded or mismatched
            mism = topic_validation.get("mismatches") or []
            print(f"Topic 67 validation: ok={topic_validation.get('ok')} funded={topic_validation.get('funded')} mismatches={mism}")
        else:
            print("Topic 67 validation: OK and funded")
    except Exception as e:
        print(f"Warning: topic creation/funding validation skipped or failed: {e}")
        if topic_validation_reason is None:
            topic_validation_reason = str(e)

    # Enforce non-overlapping targets for 7-day horizon: sample timestamps at least 168h apart
    def _non_overlapping_mask(idx: pd.DatetimeIndex, hours: int) -> pd.Series:
        """Greedy selection mask ensuring each kept timestamp is >= 'hours' after the previous kept."""
        try:
            idx_utc = _to_naive_utc_index(pd.DatetimeIndex(idx))
            ts: pd.Series = pd.to_datetime(idx_utc).to_series(index=idx_utc)
            ts_sorted: pd.Series = ts.sort_values()
            keep: List[pd.Timestamp] = []
            last_kept: Optional[pd.Timestamp] = None
            delta = pd.Timedelta(hours=hours)
            for t in ts_sorted:
                t = _to_naive_utc_ts(pd.Timestamp(t))
                if last_kept is None or t >= last_kept + delta:
                    keep.append(t)
                    last_kept = t
            keep_set: Set[pd.Timestamp] = set(keep)
            left = np.array(idx_utc, dtype='datetime64[ns]')
            right = np.array(list(keep_set), dtype='datetime64[ns]')
            mask_nd: NDArray[np.bool_] = np.isin(left, right)
            return pd.Series(mask_nd.astype(bool), index=idx_utc)
        except (ValueError, TypeError, KeyError):
            idx_fallback = _to_naive_utc_index(pd.DatetimeIndex(idx))
            return pd.Series([True] * len(idx_fallback), index=idx_fallback, dtype=bool)

    # Strict competition window filtering (inclusive) with effective end bound = min(config end, last labeled ts)
    start_naive: pd.Timestamp = _to_naive_utc_ts(start_utc)
    end_naive: pd.Timestamp = _to_naive_utc_ts(end_utc)
    last_labeled_dt = _max_dt
    end_effective = end_naive
    if last_labeled_dt is not None:
        end_effective = min(end_naive, _to_naive_utc_ts(pd.Timestamp(last_labeled_dt)))
    if end_effective < end_naive:
        print(
            "WARNING: Labeled data ends before configured end. "
            f"last_labeled={end_effective} < configured_end={end_naive}. Using effective_end={end_effective}."
        )
    print(f"Effective end for training/inference: {end_effective}")
    mask_window = (date_index >= start_naive) & (date_index <= end_effective)
    if not mask_window.all():
        full_data = full_data.loc[mask_window]
        date_index = _to_naive_utc_index(pd.DatetimeIndex(full_data.index.get_level_values("date")))
        _min_dt, _max_dt = date_index.min(), date_index.max()
        print(f"Window-clipped data date range (effective): {_min_dt} -> {_max_dt}")

    # Coverage check: ensure we had enough post-window data to compute 7d target near the end
    # Since target was computed before clipping, full_data contains only rows with valid future_close
    effective_last_t = _max_dt
    desired_last_t = end_naive
    if effective_last_t is not None:
        try:
            effective_last_cmp = _to_naive_utc_ts(pd.Timestamp(effective_last_t))
        except Exception:
            effective_last_cmp = pd.Timestamp(effective_last_t)
        try:
            desired_last_cmp = _to_naive_utc_ts(pd.Timestamp(desired_last_t)) if desired_last_t is not None else None
        except Exception:
            desired_last_cmp = desired_last_t
    else:
        effective_last_cmp = None
        desired_last_cmp = desired_last_t
    if effective_last_cmp is not None and desired_last_cmp is not None and effective_last_cmp < desired_last_cmp:
        print(
            "WARNING: Available labeled data ends before the competition end. "
            f"last_labeled_t={effective_last_cmp} < end={desired_last_cmp}. "
            "This typically occurs because source data beyond t+7d isn't available yet."
        )

    # Leakage-safe eligible rows: only timestamps with targets fully within history as of 'as_of'
    # Ensure as_of is naive UTC for NumPy/Pandas interop
    if getattr(as_of, "tz", None) is None:
        as_of_aware = as_of.tz_localize("UTC")
    else:
        as_of_aware = as_of.tz_convert("UTC")
    as_of_naive = _to_naive_utc_ts(as_of_aware)
    # For competition training, use labeled rows within [start, min(effective_end, now-7d)] to avoid leakage.
    # Use timezone-aware UTC now; then strip tz to naive UTC for numpy-friendly arithmetic
    now_minus_7d = _to_naive_utc_ts(pd.Timestamp.now(tz="UTC")) - pd.Timedelta(hours=168)
    eligible_cutoff: pd.Timestamp = min(end_effective, now_minus_7d)
    # Apply eligible cutoff to avoid leakage (<= eligible_cutoff)
    eligible_mask = (date_index >= start_naive) & (date_index <= eligible_cutoff)
    df_range: pd.DataFrame = full_data.loc[eligible_mask]
    # Apply non-overlapping decimation with 168h spacing, but relax if too few samples
    if not df_range.empty:
        dec_idx = pd.DatetimeIndex(df_range.index.get_level_values("date"))
        dec_mask: pd.Series = _non_overlapping_mask(dec_idx, hours=int(workflow.target_length))
        mask_arr: NDArray[np.bool_] = dec_mask.to_numpy(dtype=bool)  # align by position
        df_range_decimated = df_range.iloc[mask_arr]
        # If too few samples, relax the decimation
        if len(df_range_decimated) < 10:
            print(f"WARNING: Only {len(df_range_decimated)} samples after decimation, relaxing non-overlapping constraint.")
        else:
            df_range = df_range_decimated

    X_train: pd.DataFrame = pd.DataFrame()
    y_train: pd.Series = pd.Series(dtype=float)
    X_val: pd.DataFrame = pd.DataFrame()
    y_val: pd.Series = pd.Series(dtype=float)
    X_test: pd.DataFrame = pd.DataFrame()
    y_test: pd.Series = pd.Series(dtype=float)

    # If we have enough samples in the fixed window, split proportionally: 70% train, 20% val, 10% test
    if not df_range.empty and len(df_range) >= 30:
        n = len(df_range)
        # Start with 70/20/10 split, then enforce minimum sizes for stability
        train_end_idx = max(1, int(n * 0.7))
        val_end_idx = max(train_end_idx + 4, int(n * 0.9))  # ensure at least 4 val samples
        # Ensure at least 2 test samples
        if n - val_end_idx < 2:
            val_end_idx = max(train_end_idx + 4, n - 2)

        print(
            f"Using fixed window split: total={n}, train=[:{train_end_idx}], val=[{train_end_idx}:{val_end_idx}], test=[{val_end_idx}:]"
        )

        train_df = df_range.iloc[:train_end_idx]
        val_df = df_range.iloc[train_end_idx:val_end_idx]
        test_df = df_range.iloc[val_end_idx:]

        X_train = train_df.drop(columns=["target", "future_close"], errors="ignore") if not train_df.empty else pd.DataFrame()
        y_train = train_df["target"] if not train_df.empty else pd.Series(dtype=float)
        X_val = val_df.drop(columns=["target", "future_close"], errors="ignore") if not val_df.empty else pd.DataFrame()
        y_val = val_df["target"] if not val_df.empty else pd.Series(dtype=float)
        X_test = test_df.drop(columns=["target", "future_close"], errors="ignore") if not test_df.empty else pd.DataFrame()
        y_test = test_df["target"] if not test_df.empty else pd.Series(dtype=float)
    else:
        # Dynamic fallback: pick last K decimated samples within eligible range
        dec_global: pd.Series = _non_overlapping_mask(pd.DatetimeIndex(date_index), hours=int(workflow.target_length))
        mask2: NDArray[np.bool_] = dec_global.to_numpy(dtype=bool)
        full_dec: pd.DataFrame = full_data.iloc[mask2]
        di_elig: pd.DatetimeIndex = _to_naive_utc_index(pd.DatetimeIndex(full_dec.index.get_level_values("date")))
        eligible_dec_mask_arr: NDArray[np.bool_] = np.asarray((di_elig >= start_naive) & (di_elig <= eligible_cutoff), dtype=bool)
        full_dec = full_dec.iloc[eligible_dec_mask_arr]
        k = min(30, len(full_dec))
        tail = full_dec.tail(k)
        n = len(tail)
        if n >= 5:
            train_end_idx = max(1, int(n * 0.7))
            val_end_idx = max(train_end_idx + 2, int(n * 0.9))
            if n - val_end_idx < 2:
                val_end_idx = max(train_end_idx + 2, n - 2)
            train_df = tail.iloc[:train_end_idx]
            val_df = tail.iloc[train_end_idx:val_end_idx]
            test_df = tail.iloc[val_end_idx:]
        else:
            train_df = tail.iloc[: max(0, n - 2)]
            val_df = tail.iloc[max(0, n - 2): max(0, n - 1)]
            test_df = tail.iloc[max(0, n - 1):]
        X_train = train_df.drop(columns=["target", "future_close"], errors="ignore") if not train_df.empty else pd.DataFrame()
        y_train = train_df["target"] if not train_df.empty else pd.Series(dtype=float)
        X_val = val_df.drop(columns=["target", "future_close"], errors="ignore") if not val_df.empty else pd.DataFrame()
        y_val = val_df["target"] if not val_df.empty else pd.Series(dtype=float)
        X_test = test_df.drop(columns=["target", "future_close"], errors="ignore") if not test_df.empty else pd.DataFrame()
        y_test = test_df["target"] if not test_df.empty else pd.Series(dtype=float)

    # Validate targets
    if not y_train.empty:
        assert all(np.isfinite(y_train)), "Training targets must be finite"
        assert y_train.min() > -10 and y_train.max() < 10, "Training targets out of expected range"
    if not y_val.empty:
        assert all(np.isfinite(y_val)), "Validation targets must be finite"
        assert y_val.min() > -10 and y_val.max() < 10, "Validation targets out of expected range"
    if not y_test.empty:
        assert all(np.isfinite(y_test)), "Test targets must be finite"
        assert y_test.min() > -10 and y_test.max() < 10, "Test targets out of expected range"

    # If we still don't have a test sample, force the last available row as test
    if X_test.empty:
        _, _max_dt3 = date_index.min(), date_index.max()
        last_time = pd.Timestamp(_max_dt3) if _max_dt3 else pd.Timestamp.today()
        forced_mask = date_index == last_time
        if not forced_mask.any():
            forced_mask = date_index >= (last_time - pd.Timedelta(minutes=5))
        if forced_mask.any():
            X_test = full_data.loc[forced_mask].drop(columns=["target", "future_close"], errors="ignore")  # type: ignore
            y_test = full_data.loc[forced_mask]["target"]  # type: ignore

    # If training is still empty, widen to the first half of available data as a last resort
    if X_train.empty:
        _min_dt4, _max_dt4 = date_index.min(), date_index.max()
        if _min_dt4 and _max_dt4:
            cut = pd.Timestamp(_min_dt4) + (pd.Timestamp(_max_dt4) - pd.Timestamp(_min_dt4)) / 2
        else:
            cut = pd.Timestamp.today() - pd.Timedelta(days=3)
        widen_mask = date_index < cut
        X_train = full_data.loc[widen_mask].drop(columns=["target", "future_close"], errors="ignore") if widen_mask.any() else pd.DataFrame()
        y_train = full_data.loc[widen_mask]["target"] if widen_mask.any() else pd.Series(dtype=float)
        # keep validation as-is

    # Store for evaluation will be set just before metrics, after all fallbacks are applied

    # 4) Feature engineering: augment with alpha features, ETH correlations, and optional external CSVs
    # Build base close series and log-return for BTCUSD
    # Expect columns like ohlcv and rolling features; derive base from 'close' if present
    flat = X_train.copy()
    if "close" in flat.columns:
        close_series = flat["close"]
    else:
        price_candidates = [c for c in flat.columns if "close" in c or c.endswith("_close")]
        close_series = flat[price_candidates[0]] if price_candidates else pd.Series(index=flat.index, dtype=float)

    # Load ETH series for cross-asset correlations if configured; use workflow to fetch ETH features too
    features_cfg: Dict[str, Any] = cast(Dict[str, Any], cfg.get("features", {}) or {})
    use_eth = bool(features_cfg.get("use_eth", True))
    extra_map: Dict[str, pd.Series] = {}
    if use_eth:
        # Try to fetch ETH close series directly via workflow's HTTP client
        try:
            eth_ohlc = workflow.fetch_ohlcv_data("ethusd", f"{from_month}-01")
            if not eth_ohlc.empty and "date" in eth_ohlc.columns and "close" in eth_ohlc.columns:
                eth_ohlc["date"] = pd.to_datetime(eth_ohlc["date"])  # ensure datetime
                # Normalize to naive UTC to align with primary dataset
                try:
                    if getattr(eth_ohlc["date"].dtype, "tz", None) is not None:
                        eth_ohlc["date"] = eth_ohlc["date"].dt.tz_convert("UTC").dt.tz_localize(None)
                    else:
                        # If a timezone-naive datetime, assume UTC
                        pass
                except (ValueError, TypeError, AttributeError):
                    # Best effort: attempt to coerce to UTC then strip tz
                    try:
                        eth_ohlc["date"] = pd.to_datetime(eth_ohlc["date"], utc=True).dt.tz_convert("UTC").dt.tz_localize(None)
                    except (ValueError, TypeError, AttributeError):
                        eth_ohlc["date"] = eth_ohlc["date"]
                # Clip ETH series to competition window
                eth_idx = eth_ohlc["date"] if isinstance(eth_ohlc["date"].dtype, pd.DatetimeTZDtype) else eth_ohlc["date"]
                # Ensure index used for masking is naive UTC
                try:
                    eth_idx = eth_idx.dt.tz_localize(None)
                except (AttributeError, TypeError, ValueError):
                    # Already naive
                    pass
                mask_e = (eth_idx >= start_naive) & (eth_idx <= end_effective)
                eth_ohlc = eth_ohlc.loc[mask_e]
                eth_close = pd.Series(pd.to_numeric(eth_ohlc["close"], errors="coerce").values, index=eth_ohlc["date"], name="eth_close")
                extra_map["eth"] = eth_close
        except KeyboardInterrupt:
            # Treat user cancel during optional ETH fetch as non-fatal; continue training
            print("Warning: ETH fetch cancelled by user (non-fatal); continuing without ETH features")
        except (OSError, IOError, ValueError, KeyError, AttributeError, RuntimeError, requests.RequestException) as e:  # network/auth errors are non-fatal for training
            print(f"Warning: ETH fetch failed (non-fatal): {e}")

    # Build alpha features on BTC close series; align by datetime index (train+val+test combined to avoid leakage in stat fits)
    # Reconstruct a continuous close series for combined set using X_train's base; if missing, skip advanced features
    if len(close_series) > 0:
        # We don't use series values directly to avoid leakage; indicators rely on past-only operations
        feats_alpha = build_alpha_features(close_series, extra=(extra_map if extra_map else None))
    else:
        feats_alpha = pd.DataFrame(index=X_train.index)

    # Merge optional external feature CSVs
    use_ext = bool(features_cfg.get("use_external", False))
    ext_paths: List[str] = []
    _ext_raw = features_cfg.get("external_files", [])
    if isinstance(_ext_raw, list):
        ext_paths = [str(x) for x in _ext_raw]
    ext_frames: Dict[str, pd.DataFrame] = {}
    if use_ext and ext_paths:
        for fn in ext_paths:
            fn_str = str(fn)
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "external", fn_str)
            if os.path.exists(p):
                try:
                    df_ext: pd.DataFrame = pd.read_csv(p, parse_dates=True, index_col=0)
                    ext_frames[os.path.splitext(os.path.basename(fn_str))[0]] = df_ext.select_dtypes(include=["number"]).copy()
                except (OSError, IOError, ValueError) as e:
                    print(f"Warning: failed reading external file {fn}: {e}")
    if ext_frames:
        base_index_dt = pd.DatetimeIndex(feats_alpha.index)
        ext_merged = merge_external_features(base_index_dt, ext_frames)
        feats_alpha = pd.concat([feats_alpha, ext_merged], axis=1)

    # Add alpha features to each split where index overlaps
    def _align_add(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        idx = df.index
        # normalize index to datetime if multiindex
        dt_idx = pd.to_datetime(idx.get_level_values("date")) if isinstance(idx, pd.MultiIndex) else pd.to_datetime(idx)
        # Ensure naive UTC before any NumPy conversion/merge operations
        try:
            dt_idx = _to_naive_utc_index(pd.DatetimeIndex(dt_idx))
        except (ValueError, TypeError, AttributeError):
            pass
        # align by timestamp; assume feats_alpha has DatetimeIndex
        fa = feats_alpha.reindex(dt_idx)
        # Ensure identical index types for safe concatenation: force alpha index to match left df index
        try:
            fa.index = df.index
            return pd.concat([df, fa], axis=1)
        except (ValueError, TypeError, KeyError, RuntimeError):
            # Fallback: reset and merge on datetime, then restore original index
            left = df.copy()
            left_reset = left.reset_index()
            # Ensure the helper merge key is timezone-naive to avoid numpy tz warnings
            left_reset["__dt__"] = _to_naive_utc_index(pd.DatetimeIndex(dt_idx)).to_numpy()
            right_reset = fa.rename_axis("__dt__").reset_index()
            merged = pd.merge(left_reset, right_reset, on="__dt__", how="left")
            merged = merged.drop(columns=["__dt__"])  # remove helper column
            # Restore original index structure
            if isinstance(idx, pd.MultiIndex):
                merged = merged.set_index(list(idx.names))
            else:
                # If original index had no name, set it back to the original index values
                merged.index = idx
            return merged

    X_train = _align_add(X_train)
    X_val = _align_add(X_val)
    X_test = _align_add(X_test)

    # Basic anomaly filtering/denoising: remove rows with extreme z-scores on returns
    def _clip_outliers(df: pd.DataFrame, cols: List[str], z: float = 6.0) -> pd.DataFrame:
        out = df.copy()
        for c in cols:
            if c in out.columns:
                s = pd.to_numeric(out[c], errors="coerce")
                # Avoid RuntimeWarning on empty/near-empty columns
                if s.count() >= 2:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", category=RuntimeWarning)
                        mu, sd = float(np.nanmean(s)), float(np.nanstd(s))
                    if sd > 0 and math.isfinite(sd):
                        out[c] = s.clip(lower=mu - z * sd, upper=mu + z * sd)
        return out

    X_train = _clip_outliers(X_train, ["logret_1h"]) if "logret_1h" in X_train.columns else X_train
    X_val = _clip_outliers(X_val, ["logret_1h"]) if not X_val.empty and "logret_1h" in X_val.columns else X_val
    X_test = _clip_outliers(X_test, ["logret_1h"]) if "logret_1h" in X_test.columns else X_test

    # 5) Feature selection: ensure aligned numeric columns across splits with debug logs
    def _print_cols(df: pd.DataFrame, name: str) -> None:
        """Log a truncated list of column names to avoid gigantic stdout lines."""
        cols = list(df.columns)
        if not cols:
            print(f"{name} columns (0): []")
            return
        max_preview = 25
        preview = cols[:max_preview]
        remainder = len(cols) - len(preview)
        preview_str = ", ".join(str(c) for c in preview)
        if remainder > 0:
            preview_str = f"{preview_str}, ... (+{remainder} more)"
        print(f"{name} columns ({len(cols)}): [{preview_str}]")

    _print_cols(X_train, "X_train")
    _print_cols(X_val, "X_val")
    _print_cols(X_test, "X_test")

    num_train = X_train.select_dtypes(include=["number"]).columns.tolist()
    num_val = X_val.select_dtypes(include=["number"]).columns.tolist() if not X_val.empty else num_train
    num_test = X_test.select_dtypes(include=["number"]).columns.tolist() if not X_test.empty else num_train
    feature_cols = sorted(set(num_train) & set(num_val) & set(num_test))
    print(f"Numeric features by split -> train:{len(num_train)} val:{len(num_val)} test:{len(num_test)}; intersection:{len(feature_cols)}")

    # If misaligned or empty, fallback to proportional split within eligible range
    if (X_train.empty or X_val.empty or len(feature_cols) == 0):
        print("Feature misalignment or empty splits detected. Falling back to proportional split within eligible range.")
        if not df_range.empty:
            df_any = df_range.sort_index()
        else:
            eligible_all = full_data.loc[eligible_mask]
            df_any = eligible_all.sort_index() if not eligible_all.empty else full_data.sort_index()
        n2 = len(df_any)
        if n2 < 3:
            # Degenerate case: force minimal splits
            train_df2 = df_any.iloc[: max(0, n2 - 2)]
            val_df2 = df_any.iloc[max(0, n2 - 2): max(0, n2 - 1)]
            test_df2 = df_any.iloc[max(0, n2 - 1):]
        else:
            train_end_idx2 = max(1, int(n2 * 0.7))
            val_end_idx2 = max(train_end_idx2 + 1, int(n2 * 0.9))
            if n2 - val_end_idx2 < 1:
                val_end_idx2 = max(train_end_idx2 + 1, n2 - 1)
            train_df2 = df_any.iloc[:train_end_idx2]
            val_df2 = df_any.iloc[train_end_idx2:val_end_idx2]
            test_df2 = df_any.iloc[val_end_idx2:]
        X_train = train_df2.drop(columns=["target", "future_close"], errors="ignore") if not train_df2.empty else pd.DataFrame()
        y_train = train_df2["target"] if not train_df2.empty else pd.Series(dtype=float)
        X_val = val_df2.drop(columns=["target", "future_close"], errors="ignore") if not val_df2.empty else pd.DataFrame()
        y_val = val_df2["target"] if not val_df2.empty else pd.Series(dtype=float)
        X_test = test_df2.drop(columns=["target", "future_close"], errors="ignore") if not test_df2.empty else pd.DataFrame()
        y_test = test_df2["target"] if not test_df2.empty else pd.Series(dtype=float)
        _print_cols(X_train, "X_train[fallback]")
        _print_cols(X_val, "X_val[fallback]")
        _print_cols(X_test, "X_test[fallback]")
        num_train = X_train.select_dtypes(include=["number"]).columns.tolist()
        num_val = X_val.select_dtypes(include=["number"]).columns.tolist() if not X_val.empty else num_train
        num_test = X_test.select_dtypes(include=["number"]).columns.tolist() if not X_test.empty else num_train
        feature_cols = sorted(set(num_train) & set(num_val) & set(num_test))
        print(f"After fallback, intersection numeric features: {len(feature_cols)} -> {feature_cols}")

    if not feature_cols:
        raise RuntimeError("No common numeric feature columns across train/val/test after fallback. Cannot train model.")

    # 6) Train base learner (XGBoost-only)

    # Prepare matrices
    X_tr = pd.concat([X_train[feature_cols], X_val[feature_cols]]) if not X_val.empty else X_train[feature_cols]
    y_tr = pd.concat([y_train, y_val]) if not X_val.empty else y_train
    X_te = X_test[feature_cols]
    y_te = y_test

    # Expanding-window CV splits
    def expanding_splits(n: int, k: int = 5):
        step = max(2, n // (k + 1))
        for i in range(1, k + 1):
            tr_end = i * step
            va_end = min(n, tr_end + step)
            if va_end - tr_end < 2:
                continue
            yield list(range(0, tr_end)), list(range(tr_end, va_end))

    # Volatility stratification: weight folds by recent volatility
    def fold_score(y_true: pd.Series, y_pred: pd.Series) -> float:
        # prioritize correlation and lower absolute errors; simple blend
        a = y_true.to_numpy(dtype=float)
        b = y_pred.to_numpy(dtype=float)
        with np.errstate(divide='ignore', invalid='ignore'):
            corr = np.corrcoef(a, b)[0, 1]
        rmse = float(np.sqrt(np.nanmean((a - b) ** 2)))
        if not math.isfinite(corr):
            corr = 0.0
        return float(corr) - 0.1 * rmse

    # Hyperparameter config (still read, but we ignore LGBM-related settings)
    model_cfg: Dict[str, Any] = cast(Dict[str, Any], cfg.get("model", {}) or {})

    # XGBoost (required for forecasts)
    model_preds_val: Dict[str, pd.Series] = {}
    model_preds_test: Dict[str, pd.Series] = {}
    live_predictors: Dict[str, Any] = {}
    try:
        from xgboost import XGBRegressor  # type: ignore
        xgb_model = XGBRegressor(
            n_estimators=800,
            learning_rate=0.05,
            max_depth=6,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.0,
            reg_lambda=1.0,
            random_state=42,
            n_jobs=-1,
            tree_method="hist",
        )
        # Enforce XGBoost-only policy
        assert xgb_model.__class__.__name__ == "XGBRegressor", "Only XGBoost models are allowed."
        xgb_model.fit(X_tr[feature_cols].to_numpy(dtype=float), y_tr.to_numpy(dtype=float))
        live_predictors["xgb"] = xgb_model
        if not X_val.empty:
            model_preds_val["xgb"] = pd.Series(cast(np.ndarray, xgb_model.predict(X_val[feature_cols].to_numpy(dtype=float))), index=y_val.index)
        model_preds_test["xgb"] = pd.Series(cast(np.ndarray, xgb_model.predict(X_te.to_numpy(dtype=float))), index=y_te.index)
    except Exception as _xgbe:
        xgb_model = None
    # No other learners are used; forecasts must come from XGB only.
    if not model_preds_test:
        print("ERROR: XGBoost failed to train or predict; forecasts will not be submitted.", file=sys.stderr)

    # Enforce single-model: XGB only
    if set(live_predictors.keys()) - {"xgb"}:
        raise RuntimeError("Detected non-XGB predictors; only XGBoost is allowed.")
    # With XGB-only, predictions come directly from the XGB model
    y_pred_series = model_preds_test.get("xgb", pd.Series(0.0, index=y_te.index))

    # (removed unused local helper _metrics to reduce linter warnings)

    # Build training matrix
    X_tr = pd.concat([X_train[feature_cols], X_val[feature_cols]]) if not X_val.empty else X_train[feature_cols]
    y_tr = pd.concat([y_train, y_val]) if not X_val.empty else y_train
    if X_tr.empty:
        raise RuntimeError("Training feature matrix is empty after numeric selection.")
    if X_test[feature_cols].empty:
        raise RuntimeError("Test feature matrix is empty after numeric selection.")

    print("Base learner: XGBRegressor(hist)")
    # Debug: basic prediction stats (avoid warnings on empty)
    if len(y_pred_series) > 0:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            m = float(np.nanmean(y_pred_series))
            sd = float(np.nanstd(y_pred_series))
            mn = float(np.nanmin(y_pred_series))
            mx = float(np.nanmax(y_pred_series))
        print(f"Pred stats -> count:{len(y_pred_series)} mean:{m:.6g} std:{sd:.6g} min:{mn:.6g} max:{mx:.6g}")
    else:
        print("Pred stats -> count:0")
    # Only compute metrics if we have at least 2 test samples
    if len(y_test) >= 2:
        # Ensure evaluation target index matches prediction index
        workflow.test_targets = y_test
        y_pred_series = y_pred_series.reindex(y_test.index)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            metrics = workflow.evaluate_test_data(y_pred_series)
        if metrics:
            if "correlation" in metrics and metrics["correlation"] is not None:
                print(f"Correlation: {metrics['correlation']:.4f}")
            else:
                print("Correlation: n/a (insufficient variance)")
            if "directional_accuracy" in metrics and metrics["directional_accuracy"] is not None:
                print(f"Directional Accuracy: {metrics['directional_accuracy']:.4f}")
            else:
                print("Directional Accuracy: n/a")
        # Competition ZPTAE with rolling 100-period std reference; write metrics.json
        try:
            y_true_list = y_test.to_numpy(dtype=float).tolist()
            y_pred_list = y_pred_series.reindex(y_test.index).to_numpy(dtype=float).tolist()
            zpt = zptae_log10_loss(y_true_list, y_pred_list, window=100, p=3.0)
            # Sanitize metrics: if ZPTAE still non-finite, fall back to log10(MAE)
            l10 = float(zpt.get("log10_loss") or float("nan"))
            mae = float(zpt.get("mae") or float("nan"))
            mse = float(zpt.get("mse") or float("nan"))
            if not np.isfinite(l10):
                if np.isfinite(mae):
                    l10 = float(np.log10(max(mae, 1e-12)))
                else:
                    l10 = None  # cannot compute
            metrics_out: Dict[str, Any] = {"log10_loss": l10, "source": "test", "mae": mae, "mse": mse, "n": int(len(y_test))}
            art_dir = os.path.join(root_dir, "data", "artifacts")
            os.makedirs(art_dir, exist_ok=True)
            # Ensure strict JSON (no NaN/Inf) and write atomically
            safe = {k: (None if (isinstance(v, float) and not np.isfinite(v)) else v) for k, v in metrics_out.items()}
            _atomic_json_write(os.path.join(art_dir, "metrics.json"), safe)
            print(f"Wrote metrics.json with log10_loss={metrics_out['log10_loss']}")
        except (OSError, IOError, ValueError, RuntimeError, ImportError) as e:
            print(f"Warning: failed to compute/write ZPTAE metrics: {e}")
    else:
        # Fallback: if test too small, compute validation metrics when possible
        if len(y_val) >= 2 and xgb_model is not None:
            try:
                # Predict on validation split using the trained XGB model
                y_val_pred_series = pd.Series(cast(np.ndarray, xgb_model.predict(X_val[feature_cols].to_numpy(dtype=float))), index=y_val.index)
                # Optional quick stats
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=RuntimeWarning)
                    m = float(np.nanmean(y_val_pred_series))
                    sd = float(np.nanstd(y_val_pred_series))
                print(f"Val pred stats -> count:{len(y_val_pred_series)} mean:{m:.6g} std:{sd:.6g}")

                # Compute ZPTAE on validation as a proxy when test is too small
                y_true_list = y_val.to_numpy(dtype=float).tolist()
                y_pred_list = y_val_pred_series.reindex(y_val.index).to_numpy(dtype=float).tolist()
                zpt = zptae_log10_loss(y_true_list, y_pred_list, window=100, p=3.0)
                l10 = float(zpt.get("log10_loss") or float("nan"))
                mae = float(zpt.get("mae") or float("nan"))
                mse = float(zpt.get("mse") or float("nan"))
                if not np.isfinite(l10):
                    if np.isfinite(mae):
                        l10 = float(np.log10(max(mae, 1e-12)))
                    else:
                        l10 = None
                metrics_out: Dict[str, Any] = {"log10_loss": l10, "source": "validation", "mae": mae, "mse": mse, "n": int(len(y_val))}
                art_dir = os.path.join(root_dir, "data", "artifacts")
                os.makedirs(art_dir, exist_ok=True)
                safe = {k: (None if (isinstance(v, float) and not np.isfinite(v)) else v) for k, v in metrics_out.items()}
                _atomic_json_write(os.path.join(art_dir, "metrics.json"), safe)
                print(f"Wrote metrics.json (validation fallback) with log10_loss={metrics_out['log10_loss']}")
            except (OSError, IOError, ValueError, RuntimeError, ImportError) as e:
                print(f"Warning: failed to compute/write validation ZPTAE metrics: {e}")
        else:
            # If we cannot compute a metric, write a warning placeholder for traceability
            print("Skipped metrics: both test and validation too small (<2 samples)")
            try:
                art_dir = os.path.join(root_dir, "data", "artifacts")
                os.makedirs(art_dir, exist_ok=True)
                placeholder = {"log10_loss": None, "source": "none", "warning": "insufficient ground truth (<2 samples)", "n": 0}
                _atomic_json_write(os.path.join(art_dir, "metrics.json"), placeholder)
            except (OSError, IOError, ValueError, RuntimeError):
                pass

    # Live-as-of prediction for current submission window
    # Build features up to 'as_of' and compute base predictions
    try:
        # Filter full data up to as_of for base close series
        asof_mask = (date_index >= start_naive) & (date_index <= min(as_of_naive, end_effective))
        full_asof = full_data.loc[asof_mask]
        flat_any = full_asof.copy()
        if "close" in flat_any.columns:
            close_series_any = flat_any["close"]
        else:
            price_candidates = [c for c in flat_any.columns if "close" in c or c.endswith("_close")]
            close_series_any = flat_any[price_candidates[0]] if price_candidates else pd.Series(index=flat_any.index, dtype=float)
        alpha_asof = build_alpha_features(close_series_any, extra=(extra_map if extra_map else None))

        # Add simple volume-based features (rolling mean/std and z-score, 24h and 168h)
        try:
            if "volume" in flat_any.columns:
                vol_series = pd.Series(pd.to_numeric(flat_any["volume"], errors="coerce"), index=pd.to_datetime(flat_any.index.get_level_values("date")))
                vol_h = vol_series.resample("h").last()
                for w in (24, 168):
                    ma = vol_h.rolling(window=w, min_periods=max(2, w//4)).mean()
                    sd = vol_h.rolling(window=w, min_periods=max(2, w//4)).std(ddof=0)
                    alpha_asof[f"vol_ma_{w}"] = ma
                    alpha_asof[f"vol_sd_{w}"] = sd
                    alpha_asof[f"vol_z_{w}"] = (vol_h - ma) / (sd.replace(0.0, np.nan))
                    alpha_asof[f"vol_ma_ratio_{w}"] = vol_h / ma.replace(0.0, np.nan)
        except Exception:
            pass

        # Compose live feature row aligned to training feature set
        live_row = alpha_asof.tail(1).copy()
        live_row = live_row.reindex(columns=feature_cols, fill_value=0.0)

        # XGB-only live prediction
        live_member_preds: Dict[str, float] = {}
        if "xgb" in live_predictors:
            try:
                pred = float(np.asarray(live_predictors["xgb"].predict(live_row.to_numpy(dtype=float))).reshape(-1)[-1])
            except Exception:
                pred = 0.0
            live_member_preds["xgb"] = pred
            live_value = pred
        else:
            live_value = 0.0
        # Persist a small artifact for forecast construction in the submit step
        try:
            preds_arr = np.array(list(live_member_preds.values()), dtype=float)
            stddev = float(np.nanstd(preds_arr)) if preds_arr.size > 0 else None
            art_dir = os.path.join(root_dir, "data", "artifacts")
            os.makedirs(art_dir, exist_ok=True)
            lf_payload = {
                "as_of": str(as_of_naive),
                "topic_id": int(DEFAULT_TOPIC_ID),
                "member_preds": live_member_preds,
                "weights": {k: 1.0 for k in live_member_preds.keys()},
                "stddev": stddev,
            }
            _atomic_json_write(os.path.join(art_dir, "live_forecast.json"), lf_payload)
        except Exception:
            pass
    except (ValueError, TypeError, KeyError, RuntimeError) as e:
        print(f"Warning: live-as-of feature build failed: {e}")
        # Fallback: use last y_pred_series if available
        live_value = float(y_pred_series.iloc[-1]) if len(y_pred_series) else 1e-4

    # Signal damping and safety checks
    if np.isfinite(live_value) and abs(live_value) < 1e-5:
        live_value = float(np.sign(live_value) or 1.0) * 1e-5
        print(f"Signal damping applied; clamped live_value to {live_value}")
    if not (np.isfinite(live_value)) or abs(live_value) < 1e-8:
        print("Warning: invalid or near-zero live_value; applying fallback.")
        try:
            if len(y_train) > 0:
                recent = y_train.tail(min(100, len(y_train)))
                m = float(np.nanmean(recent))
                if np.isfinite(m) and abs(m) >= 1e-6:
                    live_value = m
                else:
                    s = float(np.sign(float(recent.iloc[-1]))) if len(recent) > 0 else 1.0
                    live_value = s * 1e-4
            else:
                live_value = 1e-4
        except (ValueError, TypeError, IndexError):
            live_value = 1e-4
        print(f"Using fallback live_value={live_value}")

    # 7) Persist XGB model bundle (model + features) for deterministic, fast inference
    # root_dir defined earlier
    models_dir = os.path.join(root_dir, "models")
    os.makedirs(models_dir, exist_ok=True)
    bundle_path = os.path.join(models_dir, "xgb_model.pkl")
    try:
        with open(bundle_path, "wb") as bf:
            # Persist only the XGB model and its features
            bundle_meta: Dict[str, Any] = {"features": feature_cols, "model_class": "XGBRegressor"}
            xgb_only = cast(Any, live_predictors.get("xgb"))
            pickle.dump({"model": xgb_only, "meta": bundle_meta}, bf)
        print(f"Saved XGB model bundle to {bundle_path}")
        # Verify bundle integrity by loading and reporting features count
        try:
            with open(bundle_path, "rb") as bf2:
                bundle_loaded: Dict[str, Any] = pickle.load(bf2)
            meta_loaded: Dict[str, Any] = cast(Dict[str, Any], bundle_loaded.get("meta") or {})
            features_loaded: List[Any] = cast(List[Any], meta_loaded.get("features") or [])
            n_features = len(features_loaded)
            print(f"bundle_ok model=XGBRegressor features={n_features}")
        except (OSError, IOError, pickle.UnpicklingError, AttributeError, KeyError) as e2:
            print(f"Warning: bundle self-check failed: {e2}")
    except (OSError, IOError) as e:
        print(f"Warning: failed to save model bundle: {e}")

    # 8) Save minimal JSON output ONLY to artifacts path in the new format
    # Required format: { "topic_id": 67, "value": <float> }
    # This replaces the former per-topic-key format like {"<topic_id>": [value]}.
    def save_prediction(prediction: Dict[str, Any], paths: List[str]) -> None:
        for p in paths:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            _atomic_json_write(p, prediction)
            print(f"Wrote prediction artifact -> {p}")

    artifacts_path = os.path.join(root_dir, "data", "artifacts", "predictions.json")
    topic_id_cfg: Optional[int] = None
    try:
        submission_cfg: Dict[str, Any] = cast(Dict[str, Any], cfg.get("submission", {}) or {})
        topic_id_cfg = int(submission_cfg.get("topic_id", 67))
    except (ValueError, TypeError, KeyError):
        topic_id_cfg = 67
    save_prediction({"topic_id": topic_id_cfg or 67, "value": live_value}, [artifacts_path])
    print(f"Final prediction (as_of={as_of}) value: {live_value}")

    # Ensure submission log schema exists and is locked for future writes
    log_csv = os.path.join(root_dir, "submission_log.csv")
    ensure_submission_log_schema(log_csv)
    # Also normalize existing rows to ensure exact 12-column order, lowercase booleans, and 'null' tokens
    normalize_submission_log_file(log_csv)
    # Deduplicate historical rows keeping at most one per (timestamp_utc, topic_id), preferring success rows
    dedupe_submission_log_file(log_csv)

    # 9) Optional: trigger submission now using SDK directly
    if args.submit:
        # Clamp and validate live_value
        if not (np.isfinite(live_value)):
            print("ERROR: live_value is not finite; aborting submission.", file=sys.stderr)
            return 1
        if abs(live_value) > 2.0:
            print("Warning: live prediction magnitude large; clamping to +/-2.", file=sys.stderr)
            live_value = float(max(-2.0, min(2.0, live_value)))

        # Read precomputed log10_loss if available
        pre_log10_loss: Optional[float] = None
        try:
            mpath = os.path.join(root_dir, "data", "artifacts", "metrics.json")
            if os.path.exists(mpath):
                with open(mpath, "r", encoding="utf-8") as mf:
                    _m = json.load(mf) or {}
                if isinstance(_m, dict) and "log10_loss" in _m:
                    v = _m.get("log10_loss")
                    pre_log10_loss = float(v) if v is not None else None
        except (OSError, IOError, ValueError, json.JSONDecodeError):
            pre_log10_loss = None

        if not args.force_submit and not (topic_validation_ok and topic_validation_funded and topic_validation_epoch):
            reason = topic_validation_reason or "topic_validation_failed"
            logging.warning(f"Topic validation guard active; skipping submission because {reason}")
            try:
                ws_now_tv = _window_start_utc(cadence_s=_load_cadence_from_config(root_dir))
                wallet_log = _resolve_wallet_for_logging(root_dir)
                _log_submission(
                    root_dir,
                    ws_now_tv,
                    int(topic_id_cfg or 67),
                    live_value,
                    wallet_log,
                    None,
                    None,
                    False,
                    0,
                    f"topic_validation:{reason}",
                    pre_log10_loss,
                )
            except Exception:
                pass
            return 0

        # Cooldown guard: avoid EMA collisions by limiting one success per 600s window
        def _seconds_since_last_success(csv_path: str) -> Optional[int]:
            try:
                if not os.path.exists(csv_path):
                    return None
                import csv as _csv
                last_ts: Optional[pd.Timestamp] = None
                with open(csv_path, "r", encoding="utf-8") as fh:
                    r = _csv.DictReader(fh)
                    for row in r:
                        succ = (row.get("success", "").strip().lower() in ("true", "1"))
                        ts = (row.get("timestamp_utc") or "").strip()
                        if succ and ts:
                            try:
                                t = pd.Timestamp(ts).tz_localize("UTC") if pd.Timestamp(ts).tzinfo is None else pd.Timestamp(ts).tz_convert("UTC")
                                if (last_ts is None) or (t > last_ts):
                                    last_ts = t
                            except Exception:
                                continue
                if last_ts is None:
                    return None
                now_u = pd.Timestamp.now(tz="UTC")
                return int((now_u - last_ts).total_seconds())
            except Exception:
                return None

        sec_ago = _seconds_since_last_success(log_csv)
        if (sec_ago is not None) and (sec_ago < 600):
            print(f"submit: cooldown active; last success {sec_ago}s ago < 600s; skipping to avoid EMA collision")
            try:
                ws_now_cd = _window_start_utc(cadence_s=_load_cadence_from_config(root_dir))
                w = _resolve_wallet_for_logging(root_dir)
                _log_submission(root_dir, ws_now_cd, int(topic_id_cfg or 67), live_value, w, None, None, False, 0, "cooldown_600s", pre_log10_loss)
            except Exception:
                pass
            return 0

        # High-loss filter: require pre_log10_loss to be within top 25% (lowest losses)
        def _recent_loss_q(csv_path: str, q: float = 0.25, k: int = 40) -> Optional[float]:
            try:
                if not os.path.exists(csv_path):
                    return None
                import csv as _csv
                vals: List[float] = []
                with open(csv_path, "r", encoding="utf-8") as fh:
                    r = _csv.DictReader(fh)
                    for row in r:
                        s = (row.get("log10_loss") or "").strip()
                        if s == "" or s.lower() == "null":
                            continue
                        try:
                            v = float(s)
                        except Exception:
                            continue
                        if np.isfinite(v):
                            vals.append(v)
                if not vals:
                    return None
                arr = np.array(vals[-k:], dtype=float)
                if arr.size < 5:
                    return None
                return float(np.quantile(arr, q))
            except Exception:
                return None

        q25 = _recent_loss_q(log_csv, q=0.25, k=40)
        if (pre_log10_loss is not None) and (q25 is not None):
            # Lower loss is better; require being <= q25
            if not (pre_log10_loss <= q25):
                print(f"submit: filtered out high-loss prediction (loss={pre_log10_loss:.6g} > q25={q25:.6g})")
                try:
                    ws_now_fl = _window_start_utc(cadence_s=_load_cadence_from_config(root_dir))
                    w = _resolve_wallet_for_logging(root_dir)
                    _log_submission(root_dir, ws_now_fl, int(topic_id_cfg or 67), live_value, w, None, None, False, 0, "filtered_high_loss", pre_log10_loss)
                except Exception:
                    pass
                return 0

        # Competition window guard (UTC)
        def _comp_window_from_config(root: str) -> Tuple[pd.Timestamp, pd.Timestamp]:
            try:
                if yaml is not None:
                    cfg_path2 = os.path.join(root, "config", "pipeline.yaml")
                    if os.path.exists(cfg_path2):
                        with open(cfg_path2, "r", encoding="utf-8") as fh2:
                            cfg2 = yaml.safe_load(fh2) or {}
                        if isinstance(cfg2, dict):
                            sch = cfg2.get("schedule", {}) or {}
                            s = sch.get("start")
                            e = sch.get("end")
                            if isinstance(s, str) and isinstance(e, str):
                                sdt = pd.Timestamp(s).tz_localize("UTC") if pd.Timestamp(s).tzinfo is None else pd.Timestamp(s).tz_convert("UTC")
                                edt = pd.Timestamp(e).tz_localize("UTC") if pd.Timestamp(e).tzinfo is None else pd.Timestamp(e).tz_convert("UTC")
                                return sdt, edt
            except (OSError, IOError, ValueError, TypeError):
                pass
            return pd.Timestamp("2025-09-16T13:00:00Z"), pd.Timestamp("2025-12-15T13:00:00Z")

        cadence_s = _load_cadence_from_config(root_dir)
        ws_now = _window_start_utc(cadence_s=cadence_s)
        comp_start, comp_end = _comp_window_from_config(root_dir)
        now_utc = pd.Timestamp.now(tz="UTC")
        if (not args.force_submit) and (not (comp_start <= now_utc < comp_end)):
            print("submit: outside competition window; skipping submission")
            try:
                w = _resolve_wallet_for_logging(root_dir)
                _log_submission(root_dir, ws_now, int(topic_id_cfg or 67), live_value, w, None, None, False, 0, "outside_window")
            except Exception:
                pass
            return 0
        # Duplicate guards
        # If --force-submit is NOT provided, enforce per-window duplicate guard.
        if (not args.force_submit) and _has_submitted_this_hour(log_csv, ws_now):
            print("submit: skipped; successful submission already recorded for this hour (CSV)")
            try:
                w = _resolve_wallet_for_logging(root_dir)
                _log_submission(root_dir, ws_now, int(topic_id_cfg or 67), live_value, w, None, None, False, 0, "skipped_window")
            except Exception:
                pass
            return 0
        intended_env = os.getenv("ALLORA_WALLET_ADDR", "").strip() or None
        if (not args.force_submit) and _guard_already_submitted_this_window(root_dir, cadence_s, intended_env):
            print("submit: skipped; already submitted in current window (guard)")
            try:
                w = intended_env or _resolve_wallet_for_logging(root_dir)
                _log_submission(root_dir, ws_now, int(topic_id_cfg or 67), live_value, w, None, None, False, 0, "skipped_window")
            except Exception:
                pass
            return 0

        # Lifecycle: gate by Active and Churnable states per Allora Topic Life Cycle
        lifecycle = _compute_lifecycle_state(int(topic_id_cfg or 67))
        global _LAST_TOPIC_ACTIVE_STATE
        current_active = bool(lifecycle.get("is_active", False))
        previous_active = _LAST_TOPIC_ACTIVE_STATE
        if current_active and previous_active is not True:
            msg_active = "Topic now active — submitting"
            print(msg_active)
            logging.info(msg_active)
        _LAST_TOPIC_ACTIVE_STATE = current_active
        # Also enforce topic-creation parameter compatibility and funding before submission
        topic_validation = _validate_topic_creation_and_funding(int(topic_id_cfg or 67), EXPECTED_TOPIC_67)
        if not bool(topic_validation.get("funded", False)):
            print("submit: topic not funded; call fund-topic first; skipping submission")
            try:
                w = intended_env or _resolve_wallet_for_logging(root_dir)
                _log_submission(root_dir, ws_now, int(topic_id_cfg or 67), live_value, w, None, None, False, 0, "topic_not_funded", pre_log10_loss)
            except Exception:
                pass
            return 0
        mism = topic_validation.get("mismatches") or []
        if mism:
            # Non-fatal: require at least loss_method/p_norm/allow_negative to be aligned; if not, skip
            def _has_key(prefix: str) -> bool:
                return any((isinstance(x, str) and x.startswith(prefix)) for x in mism)
            if _has_key("loss_method:") or _has_key("p_norm:") or _has_key("allow_negative:"):
                print(f"submit: topic params mismatch detected (critical): {mism}; skipping submission")
                try:
                    w = intended_env or _resolve_wallet_for_logging(root_dir)
                    _log_submission(root_dir, ws_now, int(topic_id_cfg or 67), live_value, w, None, None, False, 0, "topic_params_mismatch", pre_log10_loss)
                except Exception:
                    pass
                return 0
        # Persist lifecycle snapshot for auditability
        try:
            audit_dir = os.path.join(root_dir, "data", "artifacts", "logs")
            os.makedirs(audit_dir, exist_ok=True)
            ts_str = pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%SZ")
            with open(os.path.join(audit_dir, f"lifecycle-{ts_str}.json"), "w", encoding="utf-8") as lf:
                json.dump(lifecycle, lf, indent=2)
        except Exception:
            pass
        # Check Active (funding+stake+reputers)
        if not args.force_submit and not current_active:
            inactive_reasons = lifecycle.get("inactive_reasons") or []
            snapshot = lifecycle.get("activity_snapshot") or {}
            eff = snapshot.get("effective_revenue")
            stk = snapshot.get("delegated_stake")
            reps = snapshot.get("reputers_count")
            reason_list = [str(r) for r in inactive_reasons if r]
            reason_str = ", ".join(reason_list) if reason_list else "unknown"
            snap_str = (
                f"effective_revenue={eff} delegated_stake={stk} reputers_count={reps}"
            )
            msg = (
                "submit: topic not Active; "
                f"reasons={reason_str}; snapshot={snap_str}; skipping submission"
            )
            print(msg)
            logging.warning(msg)
            try:
                detailed_status = "skipped_due_to_topic_status"
                if reason_list:
                    reason_suffix = ";".join(reason_list)
                    detailed_status = f"{detailed_status}:{reason_suffix}"
                detailed_status = "skipped_due_to_topic_status"
                if reason_list:
                    reason_suffix = ";".join(reason_list)
                    detailed_status = f"{detailed_status}:{reason_suffix}"
                _log_submission(
                    root_dir,
                    ws_now,
                    int(topic_id_cfg or 67),
                    live_value,
                    "skipped",
                    None,
                    None,
                    False,
                    0,
                    detailed_status,
                    pre_log10_loss,
                )
            except Exception:
                pass
            return 0
        # Check Churnable (epoch elapsed and weight rank acceptable)
        if not args.force_submit and not lifecycle.get("is_churnable", False):
            reasons = lifecycle.get("churn_reasons") or []
            print(f"submit: topic Active but not Churnable; reasons={reasons}; skipping submission")
            try:
                w = intended_env or _resolve_wallet_for_logging(root_dir)
                status = "active_not_churnable:" + ",".join(reasons) if isinstance(reasons, list) else "active_not_churnable"
                _log_submission(root_dir, ws_now, int(topic_id_cfg or 67), live_value, w, None, None, False, 0, status, pre_log10_loss)
            except Exception:
                pass
            return 0

        # Submit via client using XGB-only policy to ensure non-null forecast
        _env_wallet = os.getenv("ALLORA_WALLET_ADDR", "").strip()
        if _env_wallet and not _env_wallet.endswith("6vma"):
            print(f"Warning: ALLORA_WALLET_ADDR does not end with '6vma' (got ...{_env_wallet[-4:]}); ensure correct worker wallet is configured.", file=sys.stderr)
        helper_result = _submit_via_external_helper(
            int(topic_id_cfg or 67),
            float(live_value),
            root_dir,
            pre_log10_loss,
            int(args.submit_timeout),
        )
        if helper_result is not None:
            helper_rc, helper_success = helper_result
            if helper_success:
                try:
                    _update_window_lock(root_dir, cadence_s, intended_env)
                except Exception:
                    pass
                try:
                    _post_submit_backfill(root_dir, tail=20, attempts=3, delay_s=2.0)
                except Exception:
                    pass
                return helper_rc
            else:
                print("submit(helper): external helper failed, falling back to direct client submission", file=sys.stderr)

        api_key = _require_api_key()
        # Prefer client-based submit to guarantee forecast, fallback to SDK worker if client path fails
        rc_client = asyncio.run(_submit_with_client_xgb(int(topic_id_cfg or 67), float(live_value), root_dir, pre_log10_loss, args.force_submit))
        rc = rc_client
        if rc_client != 0:
            # Always attempt SDK fallback when client path fails; unfulfilled nonces query can be stale
            print("Client-based xgb-only submit failed; attempting SDK worker fallback (forecast may be null)", file=sys.stderr)
            rc = asyncio.run(_submit_with_sdk(int(topic_id_cfg or 67), float(live_value), api_key, int(args.submit_timeout), int(args.submit_retries), root_dir, pre_log10_loss))
        if rc == 0:
            try:
                _update_window_lock(root_dir, cadence_s, intended_env)
            except Exception:
                pass
            # Best-effort score/reward backfill for recent rows
            try:
                _post_submit_backfill(root_dir, tail=20, attempts=3, delay_s=2.0)
            except Exception:
                pass
        # After submission, normalize/dedupe once more in case new rows were added
        try:
            ensure_submission_log_schema(log_csv)
            normalize_submission_log_file(log_csv)
            dedupe_submission_log_file(log_csv)
        except (OSError, IOError, ValueError, RuntimeError):
            pass
        return rc

    return 0

def main() -> int:
    root_dir = os.path.dirname(os.path.abspath(__file__))
    cfg = _load_pipeline_config(root_dir)
    parser = argparse.ArgumentParser(description="Train model and emit predictions.json for Topic 67 (7-day BTC/USD log-return)")
    parser.add_argument("--from-month", default="2025-01")
    parser.add_argument("--schedule-mode", default=None, help="Schedule mode (single, loop, etc.)")
    parser.add_argument("--cadence", default=None, help="Cadence for scheduling (e.g., 1h)")
    parser.add_argument("--start-utc", default=None, help="Start datetime in UTC (ISO format)")
    parser.add_argument("--end-utc", default=None, help="End datetime in UTC (ISO format)")
    parser.add_argument("--as-of", default=None, help="As-of datetime in UTC (ISO format)")
    parser.add_argument("--as-of-now", action="store_true", help="Use current UTC time as as_of")
    parser.add_argument("--submit", action="store_true", help="Submit the prediction after training")
    parser.add_argument("--submit-timeout", type=int, default=30, help="Timeout for submission in seconds")
    parser.add_argument("--submit-retries", type=int, default=3, help="Number of retries for submission")
    parser.add_argument("--force-submit", action="store_true", help="Force submission even if guards are active")
    parser.add_argument("--loop", action="store_true", help="Continuously run training/submission cycles based on cadence")
    parser.add_argument("--once", action="store_true", help="Run exactly one iteration even if config requests loop")
    parser.add_argument("--timeout", type=int, default=0, help="Loop runtime limit in seconds (0 runs indefinitely)")
    args = parser.parse_args()
    data_cfg: Dict[str, Any] = cfg.get("data", {})
    args.from_month = str(data_cfg.get("from_month", args.from_month))
    sched_cfg: Dict[str, Any] = cfg.get("schedule", {})
    mode_cfg = str(args.schedule_mode or sched_cfg.get("mode", "single"))
    if getattr(args, "once", False):
        effective_mode = "once"
    elif args.loop or mode_cfg.lower() == "loop":
        effective_mode = "loop"
    else:
        effective_mode = mode_cfg
    if effective_mode.lower() == "loop":
        cadence = "1h"
    else:
        cadence = str(args.cadence or sched_cfg.get("cadence", "1h"))
    setattr(args, "_effective_mode", effective_mode)
    setattr(args, "_effective_cadence", cadence)
    cadence_s = _parse_cadence(cadence)
    def _run_once() -> int:
        return run_pipeline(args, cfg, root_dir)
    if effective_mode.lower() != "loop":
        return _run_once()
    iteration = 0
    loop_timeout = max(0, int(getattr(args, "timeout", 0) or 0))
    start_wall = time.time()
    _sleep_until_next_window(cadence_s)
    last_rc = 0
    while True:
        if loop_timeout and (time.time() - start_wall) >= loop_timeout:
            logging.info("[loop] timeout reached before next iteration; exiting loop")
            return last_rc
        iteration += 1
        logging.info(f"[loop] iteration={iteration} start")
        rc = _run_once()
        last_rc = rc
        logging.info(f"[loop] iteration={iteration} completed with rc={rc}")
        now_utc = pd.Timestamp.now(tz="UTC")
        window_start = _window_start_utc(now=now_utc, cadence_s=cadence_s)
        next_window = window_start + pd.Timedelta(seconds=cadence_s)
        sleep_seconds = max(0.0, (next_window - now_utc).total_seconds())
        logging.info(f"[loop] sleeping {sleep_seconds:.1f}s until {next_window.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        try:
            time.sleep(sleep_seconds)
        except KeyboardInterrupt:
            logging.info("[loop] received KeyboardInterrupt; exiting loop")
            return rc
        if loop_timeout and (time.time() - start_wall) >= loop_timeout:
            logging.info("[loop] timeout reached after iteration; exiting loop")
            return last_rc

    return 0


if __name__ == "__main__":
    sys.exit(main())
