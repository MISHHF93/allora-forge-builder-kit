from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Optional

from allora_sdk.rpc_client import AlloraRPCClient
from allora_sdk.rpc_client.config import AlloraNetworkConfig, AlloraWalletConfig
from allora_sdk.worker import AlloraWorker

from .environment import require_api_key

DEFAULT_GRPC_URL = "grpc+https://allora-rpc.testnet.allora.network/"
DEFAULT_WEBSOCKET_URL = "wss://allora-rpc.testnet.allora.network/websocket"
DEFAULT_CHAIN_ID = "allora-testnet-1"
DEFAULT_FEE_DENOM = "uallo"
DEFAULT_MIN_GAS_PRICE = 10.0


@dataclass
class SubmissionResult:
    success: bool
    exit_code: int
    status: str
    tx_hash: Optional[str]
    nonce: Optional[int]


def _current_block_height(network_cfg: AlloraNetworkConfig) -> Optional[int]:
    try:
        client = AlloraRPCClient(network_cfg)
        block = client.get_latest_block()
        return int(block.header.height)
    except Exception:
        return None


async def _submit_once(worker: AlloraWorker, nonce: Optional[int]) -> tuple[float, Optional[str], Optional[int]]:
    async for outcome in worker.run(timeout=120):
        if isinstance(outcome, Exception):
            raise outcome
        tx_result = outcome.tx_result
        tx_hash = getattr(tx_result, "hash", None) or getattr(tx_result, "txhash", None) or getattr(tx_result, "transaction_hash", None)
        worker.stop()
        return float(outcome.prediction), tx_hash, nonce
    worker.stop()
    raise RuntimeError("Submission worker finished without emitting a result")


def submit_prediction(value: float, topic_id: int) -> SubmissionResult:
    api_key = require_api_key()
    try:
        wallet_cfg = AlloraWalletConfig.from_env()
    except ValueError as exc:
        return SubmissionResult(False, 1, f"wallet_configuration_error: {exc}", None, None)

    network_cfg = AlloraNetworkConfig(
        chain_id=os.getenv("ALLORA_CHAIN_ID", DEFAULT_CHAIN_ID),
        url=os.getenv("ALLORA_GRPC_URL", DEFAULT_GRPC_URL),
        websocket_url=os.getenv("ALLORA_WEBSOCKET_URL", DEFAULT_WEBSOCKET_URL),
        fee_denom=os.getenv("ALLORA_FEE_DENOM", DEFAULT_FEE_DENOM),
        fee_minimum_gas_price=float(os.getenv("ALLORA_MIN_GAS_PRICE", DEFAULT_MIN_GAS_PRICE)),
    )

    nonce = _current_block_height(network_cfg)
    worker = AlloraWorker(
        run=lambda _: float(value),
        wallet=wallet_cfg,
        network=network_cfg,
        api_key=api_key,
        topic_id=topic_id,
        polling_interval=120,
    )

    try:
        _, tx_hash, final_nonce = asyncio.run(_submit_once(worker, nonce))
        return SubmissionResult(True, 0, "submitted", tx_hash, final_nonce)
    except Exception as exc:  # noqa: BLE001
        worker.stop()
        return SubmissionResult(False, 1, str(exc), None, nonce)
