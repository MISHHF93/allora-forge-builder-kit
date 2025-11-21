"""
RPC utilities for fetching topic metadata and confirming transactions on Allora testnet.

This module provides functions to:
1. Fetch topic metadata using gRPC (primary) with REST fallback
2. Confirm transactions via multiple RPC endpoints
3. Handle errors gracefully with automatic fallback
"""

import logging
from typing import Optional, Dict, Any
import requests

logger = logging.getLogger(__name__)

# Prioritized gRPC endpoints (gRPC is more reliable)
GRPC_ENDPOINTS = [
    "grpc+https://allora-grpc.testnet.allora.network:443/",
]

# Fallback REST endpoints (Tendermint JSON-RPC)
TENDERMINT_RPC_ENDPOINTS = [
    "https://allora-rpc.testnet.allora.network",
    "https://rpc.ankr.com/allora_testnet",
]

# REST API endpoints (less reliable but still useful)
REST_ENDPOINTS = [
    "https://allora-rpc.testnet.allora.network",
    "https://rpc.ankr.com/allora_testnet",
]


def get_topic_metadata(topic_id: int) -> Optional[Dict[str, Any]]:
    """
    Fetch topic metadata using gRPC (primary method).
    
    Returns dict with: id, creator, reputers_count, epoch_length, epoch_last_ended, etc.
    Returns None if unable to fetch from any endpoint.
    """
    try:
        from allora_sdk.rpc_client.config import AlloraNetworkConfig
        from allora_sdk.rpc_client import AlloraRPCClient
        from allora_sdk.protos.emissions.v9 import GetTopicRequest
        
        for grpc_endpoint in GRPC_ENDPOINTS:
            try:
                logger.debug(f"Fetching topic {topic_id} via gRPC: {grpc_endpoint}")
                
                network_cfg = AlloraNetworkConfig(
                    chain_id="allora-testnet-1",
                    url=grpc_endpoint,
                    fee_denom="uallo",
                    fee_minimum_gas_price=10.0,
                )
                
                client = AlloraRPCClient(network_cfg)
                resp = client.emissions.query.get_topic(GetTopicRequest(topic_id=topic_id))
                topic = resp.topic
                
                metadata = {
                    "id": topic.id,
                    "creator": topic.creator,
                    "metadata": topic.metadata,
                    "epoch_length": topic.epoch_length,
                    "epoch_last_ended": topic.epoch_last_ended,
                    "ground_truth_lag": topic.ground_truth_lag,
                    "worker_submission_window": topic.worker_submission_window,
                    "loss_method": topic.loss_method,
                }
                
                logger.info(f"✅ Topic {topic_id} metadata fetched via gRPC")
                logger.debug(f"   metadata: {metadata['metadata']}")
                logger.debug(f"   epoch_length: {metadata['epoch_length']}")
                
                return metadata
                
            except Exception as e:
                logger.debug(f"gRPC fetch failed for {grpc_endpoint}: {type(e).__name__}: {str(e)[:100]}")
                continue
        
        # If gRPC fails, return None (REST endpoints don't have topic query)
        logger.warning(f"❌ Could not fetch topic {topic_id} metadata from any gRPC endpoint")
        return None
        
    except ImportError:
        logger.error("❌ allora-sdk not installed; cannot fetch topic metadata")
        return None


def confirm_transaction(tx_hash: str) -> bool:
    """
    Confirm that a transaction exists on-chain.
    
    Tries multiple Tendermint RPC endpoints.
    Returns True if transaction found, False otherwise.
    """
    for endpoint in TENDERMINT_RPC_ENDPOINTS:
        try:
            logger.debug(f"Confirming transaction {tx_hash} via {endpoint}")
            
            # Use Tendermint JSON-RPC endpoint
            url = f"{endpoint.rstrip('/')}/tx?hash=0x{tx_hash}"
            response = requests.get(url, timeout=8)
            
            if response.status_code == 200:
                data = response.json()
                result = data.get("result", {})
                height = result.get("height")
                
                logger.info(f"✅ Transaction {tx_hash} confirmed at height {height}")
                return True
            
        except Exception as e:
            logger.debug(f"Transaction confirmation failed on {endpoint}: {type(e).__name__}")
            continue
    
    logger.warning(f"⚠️  Could not confirm transaction {tx_hash} on any endpoint")
    return False


def get_worker_unfulfilled_nonces(wallet_address: str, topic_id: int) -> Optional[list]:
    """
    Fetch unfulfilled nonces for a worker on a given topic.
    
    Returns list of nonces, or None if unable to fetch.
    """
    try:
        from allora_sdk.rpc_client.config import AlloraNetworkConfig
        from allora_sdk.rpc_client import AlloraRPCClient
        from allora_sdk.protos.emissions.v9 import GetUnfulfilledWorkerNoncesRequest
        
        for grpc_endpoint in GRPC_ENDPOINTS:
            try:
                logger.debug(f"Fetching unfulfilled nonces via gRPC: {grpc_endpoint}")
                
                network_cfg = AlloraNetworkConfig(
                    chain_id="allora-testnet-1",
                    url=grpc_endpoint,
                    fee_denom="uallo",
                    fee_minimum_gas_price=10.0,
                )
                
                client = AlloraRPCClient(network_cfg)
                resp = client.emissions.query.get_unfulfilled_worker_nonces(
                    GetUnfulfilledWorkerNoncesRequest(topic_id=topic_id)
                )
                
                if resp.nonces:
                    nonces = [n.block_height for n in resp.nonces.nonces]
                    logger.debug(f"Unfulfilled nonces for topic {topic_id}: {nonces}")
                    return nonces
                
                return []
                
            except Exception as e:
                logger.debug(f"gRPC nonce fetch failed: {type(e).__name__}")
                continue
        
        logger.warning(f"Could not fetch unfulfilled nonces for topic {topic_id}")
        return None
        
    except ImportError:
        logger.error("❌ allora-sdk not installed")
        return None


def verify_leaderboard_visibility(topic_id: int, tx_hash: Optional[str] = None) -> bool:
    """
    Comprehensive check to verify that submissions should be visible on leaderboard.
    
    Returns True if topic is healthy and transaction is confirmed (if hash provided).
    """
    # Step 1: Check topic metadata
    metadata = get_topic_metadata(topic_id)
    if not metadata:
        logger.error(f"Cannot verify leaderboard visibility: Topic {topic_id} metadata unavailable")
        return False
    
    logger.info(f"📡 Topic {topic_id} is healthy:")
    logger.info(f"   - Reputers count: {metadata.get('reputers_count', 'N/A')}")
    logger.info(f"   - Epoch length: {metadata.get('epoch_length', 'N/A')}")
    logger.info(f"   - Worker submission window: {metadata.get('worker_submission_window', 'N/A')}")
    
    # Step 2: Confirm transaction if hash provided
    if tx_hash:
        if confirm_transaction(tx_hash):
            logger.info(f"✅ Leaderboard visibility confirmed for transaction {tx_hash}")
            return True
        else:
            logger.warning(f"⚠️  Transaction {tx_hash} not yet confirmed on-chain")
            return False
    
    return True


def diagnose_rpc_connectivity() -> Dict[str, bool]:
    """
    Diagnose connectivity to all configured RPC endpoints.
    
    Returns dict showing which endpoints are reachable.
    """
    results = {}
    
    # Test gRPC endpoints
    logger.info("Testing gRPC endpoints...")
    for endpoint in GRPC_ENDPOINTS:
        try:
            from allora_sdk.rpc_client.config import AlloraNetworkConfig
            from allora_sdk.rpc_client import AlloraRPCClient
            
            network_cfg = AlloraNetworkConfig(
                chain_id="allora-testnet-1",
                url=endpoint,
                fee_denom="uallo",
                fee_minimum_gas_price=10.0,
            )
            client = AlloraRPCClient(network_cfg)
            
            # Try a simple query
            from allora_sdk.protos.emissions.v9 import GetParamsRequest
            client.emissions.query.get_params(GetParamsRequest())
            
            results[f"gRPC: {endpoint}"] = True
            logger.info(f"✅ {endpoint}")
        except Exception as e:
            results[f"gRPC: {endpoint}"] = False
            logger.warning(f"❌ {endpoint}: {type(e).__name__}")
    
    # Test Tendermint RPC endpoints
    logger.info("Testing Tendermint RPC endpoints...")
    for endpoint in TENDERMINT_RPC_ENDPOINTS:
        try:
            url = f"{endpoint.rstrip('/')}/status"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                results[f"Tendermint RPC: {endpoint}"] = True
                logger.info(f"✅ {endpoint}")
            else:
                results[f"Tendermint RPC: {endpoint}"] = False
                logger.warning(f"❌ {endpoint}: HTTP {response.status_code}")
        except Exception as e:
            results[f"Tendermint RPC: {endpoint}"] = False
            logger.warning(f"❌ {endpoint}: {type(e).__name__}")
    
    return results
