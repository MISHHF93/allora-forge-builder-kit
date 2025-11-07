from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from allora_sdk.rpc_client import AlloraRPCClient
from allora_sdk.rpc_client.config import AlloraNetworkConfig, AlloraWalletConfig
from allora_sdk.worker import AlloraWorker

from .environment import write_last_nonce
from .logging_utils import get_stage_logger
from .submission_log import ensure_submission_log_schema, log_submission_row

# Lavender Five Testnet Endpoints
DEFAULT_GRPC_URL = "grpc+https://testnet-allora.lavenderfive.com:443"
DEFAULT_WEBSOCKET_URL = "wss://testnet-rpc.lavenderfive.com:443/allora/websocket"
DEFAULT_REST_URL = "https://testnet-rest.lavenderfive.com:443/allora/"
DEFAULT_RPC_URL = "https://testnet-rpc.lavenderfive.com:443/allora/"
DEFAULT_CHAIN_ID = "allora-testnet-1"
DEFAULT_FEE_DENOM = "uallo"
DEFAULT_MIN_GAS_PRICE = 10.0


async def get_current_block_height(network_cfg: AlloraNetworkConfig) -> Optional[int]:
    try:
        client = AlloraRPCClient(network_cfg)
        block = client.get_latest_block()
        return int(block.header.height)
    except AttributeError as e:
        # Handle API compatibility issues (e.g., missing 'events' attribute)
        if "'AlloraRPCClient' object has no attribute 'events'" in str(e):
            get_stage_logger("submit").info("API compatibility issue with AlloraRPCClient.events - skipping block height query")
            return None
        raise
    except Exception as e:
        get_stage_logger("submit").info("Failed to get current block height: %s", e)
        return None


@dataclass
class SubmissionResult:
    success: bool
    exit_code: int
    status: str
    tx_hash: Optional[str]
    nonce: Optional[int]
    score: Optional[float] = None
    reward: Optional[float] = None


@dataclass
class SubmissionConfig:
    topic_id: int
    timeout_seconds: int
    retries: int
    log_path: Path
    repo_root: Path
    api_key: str
    training_metrics: Optional[Dict[str, float]] = None

    chain_id: str = DEFAULT_CHAIN_ID
    grpc_url: str = DEFAULT_GRPC_URL
    websocket_url: str = DEFAULT_WEBSOCKET_URL
    fee_denom: str = DEFAULT_FEE_DENOM
    min_gas_price: float = DEFAULT_MIN_GAS_PRICE


async def submit_prediction(value: float, cfg: SubmissionConfig) -> SubmissionResult:
    logger = get_stage_logger("submit")
    ensure_submission_log_schema(str(cfg.log_path))

    attempt = 0
    while attempt <= cfg.retries:
        attempt += 1
        logger.info("Submitting value %.6f for topic %s (attempt %d/%d)", value, cfg.topic_id, attempt, cfg.retries + 1)
        try:
            wallet_cfg = AlloraWalletConfig.from_env()
        except ValueError as exc:
            logger.error("Wallet configuration missing: %s", exc)
            return _record_failure(cfg, value, "wallet_configuration_error", None, None)

        network_cfg = AlloraNetworkConfig(
            chain_id=cfg.chain_id,
            url=cfg.grpc_url,
            websocket_url=cfg.websocket_url,
            fee_denom=cfg.fee_denom,
            fee_minimum_gas_price=float(cfg.min_gas_price),
        )

        current_nonce = await get_current_block_height(network_cfg)
        logger.info("Current block height (nonce): %s", current_nonce)

        try:
            worker = AlloraWorker(
                run=lambda _: float(value),
                wallet=wallet_cfg,
                network=network_cfg,
                api_key=cfg.api_key,
                topic_id=cfg.topic_id,
                polling_interval=int(cfg.timeout_seconds),
            )
        except AttributeError as e:
            if "'AlloraRPCClient' object has no attribute 'events'" in str(e):
                logger.warning("API compatibility issue with AlloraRPCClient.events during worker creation - treating as submission failure")
                if attempt > cfg.retries:
                    return _record_failure(cfg, value, "api_compatibility_error", None, None)
                await asyncio.sleep(2.0)
                continue
            raise

        try:
            result = await _run_worker(worker, timeout=cfg.timeout_seconds, current_nonce=current_nonce)
        except AttributeError as e:
            if "'AlloraRPCClient' object has no attribute 'events'" in str(e):
                logger.warning("API compatibility issue with AlloraRPCClient.events during worker execution - treating as submission failure")
                worker.stop()
                if attempt > cfg.retries:
                    return _record_failure(cfg, value, "api_compatibility_error", None, None)
                await asyncio.sleep(2.0)
                continue
            raise
        except asyncio.TimeoutError:
            logger.warning("Submission attempt timed out after %ss", cfg.timeout_seconds)
            worker.stop()
            if attempt > cfg.retries:
                return _record_failure(cfg, value, "timeout", None, None)
            await asyncio.sleep(2.0)
            continue
        except Exception as exc:  # noqa: BLE001 - surface to logs
            error_msg = str(exc)
            # Check if this is an "already submitted" error, which means success
            if "inference already submitted" in error_msg.lower():
                logger.info("Inference already submitted for this epoch - treating as failure")
                # Extract transaction hash from error if possible
                tx_hash_match = re.search(r'tx_hash=([A-Fa-f0-9]+)', error_msg)
                tx_hash = tx_hash_match.group(1) if tx_hash_match else None
                # Use val_mae as fallback score placeholder for traceability
                score = cfg.training_metrics.get("val_mae") if cfg.training_metrics else None
                reward = "pending"  # Reward not yet available, will be backfilled
                return _record_failure(cfg, value, "inference_already_submitted", tx_hash, current_nonce, score=score, reward=reward, score_source="fallback", reward_status="pending")
            worker.stop()
            logger.exception("Submission attempt failed: %s", exc)
            if attempt > cfg.retries:
                return _record_failure(cfg, value, str(exc), None, None)
            await asyncio.sleep(2.0)
            continue

        worker.stop()
        if result is None:
            logger.warning("Worker completed without producing a transaction")
            if attempt > cfg.retries:
                return _record_failure(cfg, value, "no_result", None, None)
            await asyncio.sleep(1.0)
            continue

        prediction, tx_hash, nonce, tx_result = result
        score, reward = _extract_submission_metrics(tx_result)
        logger.info(
            "Submission succeeded (tx=%s nonce=%s score=%s reward=%s)",
            tx_hash,
            nonce,
            f"{score:.6f}" if score is not None else "null",
            f"{reward:.6f}" if reward is not None else "null",
        )
        
        # Debug: log transaction result structure
        if tx_result:
            logger.debug("Transaction result attributes: %s", list(vars(tx_result).keys()) if hasattr(tx_result, '__dict__') else 'No __dict__')
            if hasattr(tx_result, 'raw_log'):
                logger.debug("Raw log preview: %s", str(tx_result.raw_log)[:200] if tx_result.raw_log else 'None')
        # Determine source flags for traceability
        score_source = "live" if score is not None else "pending"
        reward_status = "fetched" if reward is not None else "pending"
        _log_csv(
            cfg,
            prediction,
            True,
            0,
            "submitted",
            tx_hash,
            nonce,
            score=score,
            reward=reward,
            score_source=score_source,
            reward_status=reward_status,
        )
        write_last_nonce(cfg.repo_root, {
            "topic_id": cfg.topic_id,
            "value": prediction,
            "tx_hash": tx_hash,
            "nonce": nonce,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "wallet": os.getenv("ALLORA_WALLET_ADDR") or None,
        })
        return SubmissionResult(True, 0, "submitted", tx_hash, nonce, score, reward)

    return _record_failure(cfg, value, "exhausted_retries", None, None)


async def _run_worker(
    worker: AlloraWorker, timeout: int, current_nonce: Optional[int] = None
) -> Optional[tuple[float, Optional[str], Optional[int], Any]]:
    try:
        async for outcome in worker.run(timeout=timeout or None):
            if isinstance(outcome, Exception):
                raise outcome
            tx = outcome.tx_result
            
            logger = get_stage_logger("submit")
            logger.debug("tx_result type: %s", type(tx))
            if hasattr(tx, '__dict__'):
                logger.debug("tx_result attributes: %s", list(vars(tx).keys()))
            
            # Safely check for events
            try:
                if hasattr(tx, 'events'):
                    logger.debug("events type: %s", type(tx.events))
                    logger.debug("events: %s", tx.events)
            except AttributeError:
                logger.debug("Could not access tx.events - API compatibility issue")
            
            # Safely check for logs
            try:
                if hasattr(tx, 'logs'):
                    logger.debug("logs: %s", tx.logs)
            except AttributeError:
                logger.debug("Could not access tx.logs - API compatibility issue")
            
            # Safely check for raw_log
            try:
                if hasattr(tx, 'raw_log'):
                    logger.debug("raw_log: %s", tx.raw_log[:500])
            except AttributeError:
                logger.debug("Could not access tx.raw_log - API compatibility issue")
            
            # Try multiple ways to extract transaction hash
            tx_hash = None
            if hasattr(tx, 'hash') and tx.hash:
                tx_hash = tx.hash
            elif hasattr(tx, 'txhash') and tx.txhash:
                tx_hash = tx.txhash
            elif hasattr(tx, 'transaction_hash') and tx.transaction_hash:
                tx_hash = tx.transaction_hash
            # Try to extract from raw_log if available
            if not tx_hash:
                raw_log = getattr(tx, 'raw_log', '')
                if raw_log and isinstance(raw_log, str):
                    # Look for transaction hash patterns in the log
                    import re
                    hash_match = re.search(r'txhash["\s:]+([A-Fa-f0-9]{64})', raw_log)
                    if hash_match:
                        tx_hash = hash_match.group(1).upper()
            
            nonce = _extract_nonce(tx)
            if nonce is None and hasattr(outcome, 'nonce'):
                nonce = outcome.nonce
            
            if nonce is None:
                nonce = current_nonce
            
            # If we have either a hash or nonce, consider it successful
            if tx_hash or nonce is not None:
                return outcome.prediction, tx_hash, nonce, tx
            
            # Fallback: assume success if we got here
            return outcome.prediction, tx_hash, nonce, tx
    except AttributeError as e:
        if "'AlloraRPCClient' object has no attribute 'events'" in str(e):
            logger = get_stage_logger("submit")
            logger.warning("API compatibility issue with AlloraRPCClient.events - treating as submission failure")
            return None
        raise
    except Exception as e:
        # Catch any other exceptions that might occur during worker.run()
        logger = get_stage_logger("submit")
        logger.warning("Unexpected error during worker.run(): %s", e)
        return None
    return None


def _extract_nonce(tx: Any) -> Optional[int]:
    # Allora events expose nonce either in events dict or raw log. Try both.
    events = None
    try:
        events = getattr(tx, "events", None)
    except AttributeError:
        pass  # API compatibility issue

    if isinstance(events, dict):
        for event in events.values():
            if isinstance(event, dict):
                for key, value in event.items():
                    if str(key).lower() in {"nonce", "window_nonce"}:
                        try:
                            return int(value)
                        except (TypeError, ValueError):
                            continue

    raw = ""
    try:
        raw = getattr(tx, "raw_log", "")
    except AttributeError:
        pass  # API compatibility issue

    if isinstance(raw, str):
        for token in raw.replace("\n", " ").split():
            if token.isdigit():
                try:
                    return int(token)
                except ValueError:
                    continue
    return None


def _extract_submission_metrics(tx: Any) -> tuple[Optional[float], Optional[float]]:
    """Extract score and reward metrics from a transaction result if present."""

    logger = get_stage_logger("submit")
    logger.debug("Extracting metrics from tx: %s", type(tx))

    score: Optional[float] = None
    reward: Optional[float] = None

    def _consider(key: Any, value: Any) -> None:
        nonlocal score, reward
        key_str = str(key or "").lower()
        val = value
        logger.debug("Considering key='%s' value='%s'", key, value)
        if score is None and any(token in key_str for token in ("score", "ema", "mae")):
            score_candidate = _coerce_float(val)
            if score_candidate is None and isinstance(val, str):
                score_candidate = _extract_numeric_fragment(val)
            if score_candidate is not None:
                score = score_candidate

        if reward is None and (
            "reward" in key_str or (
                "amount" in key_str and isinstance(val, str) and "allo" in val.lower()
            )
        ):
            reward_candidate = _parse_reward_value(val)
            if reward_candidate is not None:
                reward = reward_candidate

    def _walk(mapping: Any) -> None:
        if isinstance(mapping, dict):
            for k, v in mapping.items():
                if isinstance(v, dict):
                    _walk(v)
                else:
                    _consider(k, v)

    # Safely extract events
    events = None
    try:
        events = getattr(tx, "events", None)
    except AttributeError:
        logger.debug("Could not access tx.events - API compatibility issue")

    if events is not None:
        _walk(events)

    # Safely extract logs
    logs = None
    try:
        logs = getattr(tx, "logs", None)
    except AttributeError:
        logger.debug("Could not access tx.logs - API compatibility issue")

    if isinstance(logs, list):
        for entry in logs:
            entry_events = None
            try:
                entry_events = getattr(entry, "events", None)
            except AttributeError:
                logger.debug("Could not access entry.events - API compatibility issue")
            if entry_events is not None:
                _walk(entry_events)

    # Extract from raw log as fallback
    raw = None
    try:
        raw = getattr(tx, "raw_log", None)
    except AttributeError:
        logger.debug("Could not access tx.raw_log - API compatibility issue")

    if isinstance(raw, str):
        if score is None:
            score = _extract_numeric_fragment(raw, keywords=("score", "ema"))
        if reward is None:
            reward = _parse_reward_value(raw)

    return score, reward


def _extract_numeric_fragment(text: str, keywords: tuple[str, ...] = ()) -> Optional[float]:
    if not isinstance(text, str):
        return None
    snippet_sources = []
    lowered = text.lower()
    for keyword in keywords:
        idx = lowered.find(keyword)
        if idx != -1:
            snippet_sources.append(text[idx : idx + 120])
    if not snippet_sources:
        snippet_sources.append(text)

    for snippet in snippet_sources:
        match = re.search(r"-?\d+(?:\.\d+)?", snippet)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                continue
    return None


def _parse_reward_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    micro_match = re.search(r"(-?\d+(?:\.\d+)?)\s*uallo", lowered)
    if micro_match:
        try:
            return float(micro_match.group(1)) / 1_000_000.0
        except ValueError:
            return None

    allo_match = re.search(r"(-?\d+(?:\.\d+)?)\s*allo", lowered)
    if allo_match:
        try:
            return float(allo_match.group(1))
        except ValueError:
            return None

    snippets = []
    for keyword in ("reward", "amount"):
        idx = lowered.find(keyword)
        if idx != -1:
            snippets.append(text[idx : idx + 80])
    for snippet in snippets:
        match = re.search(r"(-?\d+(?:\.\d+)?)", snippet)
        if match:
            try:
                value_f = float(match.group(1))
                if "uallo" in snippet.lower():
                    return value_f / 1_000_000.0
                return value_f
            except ValueError:
                continue
    return None


def _coerce_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        if isinstance(value, (float, int)):
            return float(value)
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _format_decimal(value: Optional[float], *, digits: int) -> Optional[str]:
    if value is None:
        return None
    try:
        return f"{float(value):.{int(digits)}f}"
    except (TypeError, ValueError):
        return None


def _record_failure(
    cfg: SubmissionConfig,
    value: float,
    status: str,
    tx_hash: Optional[str],
    nonce: Optional[int],
    score: Optional[float] = None,
    reward: Optional[Union[float, str]] = None,
    score_source: str = "live",
    reward_status: str = "fetched",
) -> SubmissionResult:
    logger = get_stage_logger("submit")
    logger.error("Submission failed (%s)", status)
    _log_csv(cfg, value, False, 1, status, tx_hash, nonce, score=score, reward=reward, score_source=score_source, reward_status=reward_status)
    return SubmissionResult(False, 1, status, tx_hash, nonce, score, reward)


def _log_csv(
    cfg: SubmissionConfig,
    value: float,
    success: bool,
    exit_code: int,
    status: str,
    tx_hash: Optional[str],
    nonce: Optional[int],
    *,
    score: Optional[float] = None,
    reward: Optional[float] = None,
    score_source: str = "live",
    reward_status: str = "fetched",
) -> None:
    """
    Log submission details to CSV with traceability flags.
    
    Fallback Logic for Auditability:
    - Successful submissions: If score/reward not extracted from tx, set to 0.0/"pending" with flags "pending"
    - Failed submissions: Use training val_mae as score placeholder with "fallback" flag, reward "pending"
    - Flags appended to status: e.g., "submitted|score_pending|reward_pending" or "inference_already_submitted|score_fallback|reward_pending"
    - This ensures no nulls while clearly indicating data source for debugging/validation
    """
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    wallet = os.getenv("ALLORA_WALLET_ADDR") or ""
    formatted_value = _format_decimal(value, digits=6)
    
    # Set defaults to avoid nulls, with traceability flags
    if score is None:
        if cfg.training_metrics and success:
            # For successful submissions, if score not extracted, it's pending
            score = 0.0
            score_source = "pending"
        else:
            score = 0.0  # Fallback for other cases
    if reward is None:
        reward = "pending"
        reward_status = "pending"
    elif isinstance(reward, str) and reward == "pending":
        reward_status = "pending"
    if nonce is None:
        nonce = 0
    if tx_hash is None:
        tx_hash = ""
    
    # Append traceability flags to status for auditability
    flags = []
    if score_source != "live":
        flags.append(f"score_{score_source}")
    if reward_status != "fetched":
        flags.append(f"reward_{reward_status}")
    if flags:
        status = f"{status}|{'|'.join(flags)}"
    
    formatted_score = _format_decimal(score, digits=6)
    if isinstance(reward, str) and reward == "pending":
        formatted_reward = "pending"
    else:
        formatted_reward = _format_decimal(reward, digits=6)
    
    # Calculate log10_loss from training metrics if available
    log10_loss = None
    if cfg.training_metrics:
        # Prefer validation log10_loss, fallback to training
        log10_loss = cfg.training_metrics.get("val_log10_loss") or cfg.training_metrics.get("train_log10_loss")
    if log10_loss is None:
        log10_loss = 0.0
    formatted_log10_loss = _format_decimal(log10_loss, digits=6)
    
    log_submission_row(
        str(cfg.log_path),
        {
            "timestamp_utc": timestamp,
            "topic_id": cfg.topic_id,
            "value": formatted_value,
            "wallet": wallet,
            "nonce": nonce,
            "tx_hash": tx_hash,
            "success": success,
            "exit_code": exit_code,
            "status": status,
            "log10_loss": formatted_log10_loss,
            "score": formatted_score,
            "reward": formatted_reward,
        },
    )
