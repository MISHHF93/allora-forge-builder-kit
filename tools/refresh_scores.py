#!/usr/bin/env python
"""
Refresh pending score/reward entries in submission_log.csv by querying the REST API
for each available tx_hash and parsing tx logs for EMA score and transfer rewards.

Usage:
  python tools/refresh_scores.py [--csv submission_log.csv] [--rest https://allora-api.testnet.allora.network] [--tail 10]

Notes:
  - Does not require extra dependencies; uses urllib + json.
  - Only updates rows where score is null/NaN or reward is 'pending'.
  - Writes back to the same CSV file in-place.
"""
import argparse
import csv
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
import re
import subprocess


CANONICAL_HEADER: List[str] = [
    "timestamp_utc",
    "topic_id",
    "value",
    "wallet",
    "nonce",
    "tx_hash",
    "success",
    "exit_code",
    "status",
    "log10_loss",
    "score",
    "reward",
]


def http_get_json(url: str, timeout: float = 15.0) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            return json.loads(data.decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"[WARN] HTTP {e.code} for {url}")
    except urllib.error.URLError as e:
        print(f"[WARN] URL error for {url}: {e}")
    except Exception as e:
        print(f"[WARN] Failed to GET {url}: {e}")
    return None


def parse_reward_from_events(events: List[Dict[str, Any]]) -> Optional[float]:
    """
    Try to extract the ALLO reward amount from transfer/coin_received events.
    Returns amount in ALLO (not uallo).
    """
    candidates: List[str] = []
    for ev in events:
        ev_type = ev.get("type", "")
        attrs = ev.get("attributes", []) or []
        if ev_type in ("transfer", "coin_received", "coin_spent"):
            for a in attrs:
                val = a.get("value") if isinstance(a, dict) else None
                if not isinstance(val, str):
                    continue
                # Common patterns: "123uallo" or "[{denom: uallo, amount: "123"}]" in some chains
                if "uallo" in val:
                    candidates.append(val)
                elif "ALLO" in val:
                    candidates.append(val)

    # Heuristic parse of amounts
    best: Optional[float] = None
    for s in candidates:
        try:
            if s.endswith("uallo"):
                num = s.replace("uallo", "").strip()
                amt = float(num) / 1e6
            elif s.endswith("ALLO"):
                num = s.replace("ALLO", "").strip()
                amt = float(num)
            else:
                # Fallback: extract leading numeric
                num = "".join(ch for ch in s if (ch.isdigit() or ch == "."))
                if not num:
                    continue
                amt = float(num)
            if best is None or amt > best:
                best = amt
        except Exception:
            continue
    return best


def parse_score_from_events(events: List[Dict[str, Any]]) -> Optional[float]:
    """
    Try to extract EMA score from events. We look for emissions-related events and a float-like
    attribute named 'score', 'ema_score', or similar. We pick the first plausible float.
    """
    for ev in events:
        ev_type = ev.get("type", "")
        attrs = ev.get("attributes", []) or []
        # Likely event types: 'allora.emissions.EventEMAScoresSet', 'emascoreset', etc.
        if "ema" in ev_type.lower() or "score" in ev_type.lower() or "emission" in ev_type.lower():
            for a in attrs:
                key = a.get("key", "") if isinstance(a, dict) else ""
                val = a.get("value") if isinstance(a, dict) else None
                if not isinstance(val, str):
                    continue
                if any(k in (key or "").lower() for k in ("score", "ema")):
                    try:
                        return float(val)
                    except Exception:
                        # Sometimes value might be json-like; attempt to extract first float
                        num = "".join(ch for ch in (val or "") if (ch.isdigit() or ch == "."))
                        try:
                            if num:
                                return float(num)
                        except Exception:
                            pass
        else:
            # Generic scan as fallback
            for a in attrs:
                val = a.get("value") if isinstance(a, dict) else None
                if not isinstance(val, str):
                    continue
                # Heuristic: standalone small float in [0,1]
                try:
                    f = float(val)
                    if 0.0 <= f <= 1.0:
                        return f
                except Exception:
                    continue
    return None


def fetch_tx_logs(rest_base: str, tx_hash: str) -> Optional[Tuple[int, List[Dict[str, Any]]]]:
    # Cosmos SDK tx endpoint
    url = f"{rest_base.rstrip('/')}/cosmos/tx/v1beta1/txs/{tx_hash}"
    data = http_get_json(url)
    if not data:
        return None
    # code==0 => success
    code = 0
    try:
        code = int(((data.get("tx_response") or {}).get("code")) or 0)
    except Exception:
        code = 0
    logs = ((data.get("tx_response") or {}).get("logs")) or []
    return code, logs


def load_csv(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [dict(r) for r in reader]
    return rows


def write_csv(path: str, rows: List[Dict[str, Any]]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CANONICAL_HEADER)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in CANONICAL_HEADER})


def is_nullish(x: Any) -> bool:
    if x is None:
        return True
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return True
    if isinstance(x, str) and x.strip().lower() in ("null", "na", "nan", ""):
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh pending score/reward in submission_log.csv by querying tx logs")
    ap.add_argument("--csv", default="submission_log.csv", help="Path to CSV (default: submission_log.csv)")
    ap.add_argument("--rest", default="https://allora-rpc.testnet.allora.network/", help="REST base URL (default: Allora testnet REST)")
    ap.add_argument("--tail", type=int, default=20, help="Only consider last N rows (default: 20); set large to scan all")
    ap.add_argument("--rpc", default=os.getenv("ALLORA_RPC_URL") or os.getenv("ALLORA_NODE") or "https://rpc.ankr.com/allora_testnet", help="RPC URL for CLI queries")
    # chain-id isn't required for the emissions query and may not be supported by some builds; omit for robustness
    ap.add_argument("--sleep", type=float, default=0.2, help="Sleep between network calls (seconds)")
    args = ap.parse_args()

    csv_path = args.csv
    if not os.path.exists(csv_path):
        print(f"[INFO] No CSV at {csv_path}; nothing to refresh.")
        return 0

    rows = load_csv(csv_path)
    if not rows:
        print("[INFO] CSV is empty; nothing to refresh.")
        return 0

    start_idx = max(0, len(rows) - int(args.tail))
    updated = 0
    for i in range(start_idx, len(rows)):
        r = rows[i]
        txh = (r.get("tx_hash") or "").strip()
        need_score = is_nullish(r.get("score"))
        need_reward = (r.get("reward") or "").strip().lower() in ("pending", "", "null", "na", "nan")
        if not txh or (not need_score and not need_reward):
            continue
        # Try tx logs first for reward, but EMA score may be absent there; then CLI for EMA.
        score_from_logs: Optional[float] = None
        reward_from_logs: Optional[float] = None

        out = fetch_tx_logs(args.rest, txh)
        if out:
            code, logs = out
            if code == 0:
                # logs: list of per-msg logs; each has events
                all_events: List[Dict[str, Any]] = []
                for entry in logs:
                    evs = entry.get("events", []) or []
                    all_events.extend(evs)
                score_from_logs = parse_score_from_events(all_events)
                reward_from_logs = parse_reward_from_events(all_events)
            else:
                print(f"[INFO] Tx {txh} not successful yet (code={code}); skipping logs parse")
        else:
            print(f"[WARN] Could not fetch tx {txh}")

        if need_reward and reward_from_logs is not None:
            r["reward"] = f"{reward_from_logs:.12f}"
            updated += 1
            print(f"[OK] Updated reward for tx {txh} -> {r['reward']} ALLO")

        if need_score:
            # Prefer logs if present
            sc = score_from_logs
            if sc is None:
                # Fallback to CLI: allorad q emissions inferer-score-ema <topic> <wallet>
                topic = (r.get("topic_id") or r.get("topic") or "").strip()
                wallet = (r.get("wallet") or "").strip()
                if topic and wallet:
                    cmd = [
                        "allorad", "q", "emissions", "inferer-score-ema", str(int(float(topic))), str(wallet),
                        "--node", str(args.rpc), "--output", "json",
                    ]
                    try:
                        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                        out = (cp.stdout or "").strip() or (cp.stderr or "").strip()
                        # Try JSON parse first
                        got_val: Optional[float] = None
                        try:
                            j = json.loads(out)
                            def _find_num(obj: Any) -> Optional[float]:
                                if isinstance(obj, (int, float)) and math.isfinite(obj):
                                    return float(obj)
                                if isinstance(obj, str):
                                    try:
                                        v = float(obj)
                                        return v if math.isfinite(v) else None
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
                                    for item in obj:
                                        r = _find_num(item)
                                        if r is not None:
                                            return r
                                return None
                            got_val = _find_num(j)
                        except Exception:
                            got_val = None
                        if got_val is None:
                            m = re.search(r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", out)
                            if m:
                                try:
                                    fv = float(m.group(1))
                                    if math.isfinite(fv):
                                        got_val = fv
                                except Exception:
                                    pass
                        if got_val is not None:
                            sc = got_val
                    except FileNotFoundError:
                        print("[WARN] allorad CLI not found; cannot query EMA score via CLI")
                    except Exception as e:
                        print(f"[WARN] EMA CLI query failed: {e}")

            if sc is not None:
                r["score"] = f"{sc:.9f}"
                updated += 1
                print(f"[OK] Updated score for tx {txh} -> {r['score']}")

        time.sleep(args.sleep)

    # Set reward = score for rows where score is set but reward is pending
    for r in rows:
        score_val = r.get("score")
        reward_val = r.get("reward")
        if not is_nullish(score_val) and (is_nullish(reward_val) or reward_val == "pending"):
            r["reward"] = score_val
            updated += 1
            txh = r.get("tx_hash", "unknown")
            print(f"[OK] Set reward = score for tx {txh} -> {r['reward']}")

    if updated:
        write_csv(csv_path, rows)
        print(f"[DONE] Wrote CSV with {updated} field updates -> {csv_path}")
    else:
        print("[INFO] No updates found; CSV unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
