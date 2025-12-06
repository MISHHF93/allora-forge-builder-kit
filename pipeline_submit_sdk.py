"""Submit predictions to the Allora chain using the official SDK.

This module provides a reliable way to submit worker payloads to the Allora
blockchain using the allora-sdk Python library, which handles:
- Proper protobuf serialization
- Cryptographic signing (secp256k1)
- Transaction broadcasting and confirmation
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional, Tuple

# SDK imports
from allora_sdk import AlloraRPCClient, AlloraNetworkConfig
from allora_sdk.rpc_client.config import AlloraWalletConfig

logger = logging.getLogger(__name__)


class AlloraSubmitter:
    """Handles submission of predictions to the Allora blockchain."""
    
    def __init__(
        self,
        mnemonic: Optional[str] = None,
        mnemonic_file: Optional[str] = None,
        chain_id: str = "allora-testnet-1",
        grpc_url: str = "grpc+https://allora-grpc.testnet.allora.network:443",
    ):
        """Initialize the Allora submitter.
        
        Args:
            mnemonic: The wallet mnemonic phrase
            mnemonic_file: Path to file containing mnemonic
            chain_id: Blockchain chain ID
            grpc_url: gRPC endpoint URL (must start with grpc+ or rest+)
        """
        self.chain_id = chain_id
        self.grpc_url = grpc_url
        
        # Load mnemonic
        if mnemonic:
            self.mnemonic = mnemonic
        elif mnemonic_file:
            with open(mnemonic_file) as f:
                self.mnemonic = f.read().strip()
        else:
            self.mnemonic = os.getenv("MNEMONIC", "")
            # Try to find mnemonic.txt in various locations
            if not self.mnemonic:
                possible_paths = [
                    "mnemonic.txt",
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "mnemonic.txt"),
                    "/workspaces/allora-forge-builder-kit/mnemonic.txt",
                ]
                for path in possible_paths:
                    if os.path.exists(path):
                        with open(path) as f:
                            self.mnemonic = f.read().strip()
                        break
        
        if not self.mnemonic:
            raise ValueError("No mnemonic provided")
        
        self._client: Optional[AlloraRPCClient] = None
    
    def _get_client(self) -> AlloraRPCClient:
        """Get or create the RPC client."""
        if self._client is None:
            wallet_config = AlloraWalletConfig(mnemonic=self.mnemonic)
            network = AlloraNetworkConfig(
                chain_id=self.chain_id,
                url=self.grpc_url,
            )
            self._client = AlloraRPCClient(
                network=network,
                wallet=wallet_config,
            )
        return self._client
    
    @property
    def wallet_address(self) -> str:
        """Get the wallet address."""
        return self._get_client().address
    
    async def get_topic_info(self, topic_id: int) -> dict:
        """Get information about a topic.
        
        Args:
            topic_id: The topic ID to query
            
        Returns:
            Dictionary with topic information
        """
        client = self._get_client()
        from allora_sdk.protos.emissions.v9 import GetTopicRequest
        request = GetTopicRequest(topic_id=topic_id)
        response = client.emissions.query.get_topic(request)
        return {
            "id": response.topic.id,
            "metadata": response.topic.metadata,
            "epoch_last_ended": response.topic.epoch_last_ended,
            "epoch_length": response.topic.epoch_length,
            "worker_submission_window": response.topic.worker_submission_window,
        }
    
    async def get_unfulfilled_nonces(self, topic_id: int) -> list:
        """Get unfulfilled worker nonces for a topic.
        
        Args:
            topic_id: The topic ID to query
            
        Returns:
            List of unfulfilled nonce block heights
        """
        client = self._get_client()
        from allora_sdk.protos.emissions.v9 import GetUnfulfilledWorkerNoncesRequest
        request = GetUnfulfilledWorkerNoncesRequest(topic_id=topic_id)
        response = client.emissions.query.get_unfulfilled_worker_nonces(request)
        return [n.block_height for n in response.nonces.nonces] if response.nonces.nonces else []
    
    async def can_submit(self, topic_id: int) -> bool:
        """Check if the wallet can submit to a topic.
        
        Args:
            topic_id: The topic ID to check
            
        Returns:
            True if submission is allowed
        """
        client = self._get_client()
        from allora_sdk.protos.emissions.v9 import CanSubmitWorkerPayloadRequest
        request = CanSubmitWorkerPayloadRequest(
            topic_id=topic_id,
            address=self.wallet_address,
        )
        response = client.emissions.query.can_submit_worker_payload(request)
        return response.can_submit_worker_payload
    
    async def submit_prediction(
        self,
        topic_id: int,
        value: float,
        nonce: Optional[int] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Submit a prediction to the Allora chain.
        
        Args:
            topic_id: The topic ID to submit to
            value: The prediction value
            nonce: Optional nonce (block height). If not provided, will try to
                   find an unfulfilled nonce.
                   
        Returns:
            Tuple of (success, tx_hash, error_message)
        """
        client = self._get_client()
        
        # If no nonce provided, try to find an unfulfilled one
        if nonce is None:
            try:
                # First, get the topic info to find epoch_last_ended
                topic_info = await self.get_topic_info(topic_id)
                nonce = topic_info["epoch_last_ended"]
                logger.info(f"Using epoch_last_ended as nonce: {nonce}")
            except Exception as e:
                logger.warning(f"Could not get topic info: {e}")
                # Fallback: get unfulfilled nonces
                try:
                    nonces = await self.get_unfulfilled_nonces(topic_id)
                    if nonces:
                        nonce = nonces[0]
                        logger.info(f"Using unfulfilled nonce: {nonce}")
                    else:
                        logger.warning("No unfulfilled nonces available")
                        return False, None, "No unfulfilled nonces available"
                except Exception as e2:
                    logger.error(f"Could not get unfulfilled nonces: {e2}")
                    return False, None, str(e2)
        
        logger.info(f"Submitting prediction: topic={topic_id}, value={value}, nonce={nonce}")
        
        try:
            pending_tx = await client.emissions.tx.insert_worker_payload(
                topic_id=topic_id,
                inference_value=str(value),
                nonce=nonce,
                forecast_elements=None,
            )
            
            # Wait for confirmation
            logger.info("Waiting for transaction confirmation...")
            tx_result = await pending_tx.wait()
            
            # Extract tx hash from the pending tx attributes
            tx_hash = getattr(pending_tx, 'last_tx_hash', None)
            
            logger.info(f"Transaction successful! Hash: {tx_hash}")
            return True, tx_hash, None
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Submission failed: {error_msg}")
            
            # Extract tx hash from error if available
            if "tx_hash=" in error_msg:
                tx_hash = error_msg.split("tx_hash=")[1].split()[0]
                return False, tx_hash, error_msg
            
            return False, None, error_msg


def submit_prediction_to_chain(
    topic_id: int,
    value: float,
    wallet: str,  # Not used, but kept for compatibility
    logger,
    nonce: Optional[int] = None,
) -> Tuple[bool, Optional[str]]:
    """Submit a prediction to the Allora chain.
    
    This is a convenience function for backward compatibility with the
    previous CLI-based implementation.
    
    Args:
        topic_id: The topic ID to submit to
        value: The prediction value
        wallet: Wallet address (ignored, SDK uses mnemonic)
        logger: Logger instance
        nonce: Optional nonce (block height)
        
    Returns:
        Tuple of (success, tx_hash)
    """
    try:
        submitter = AlloraSubmitter()
        success, tx_hash, error = asyncio.run(
            submitter.submit_prediction(topic_id, value, nonce)
        )
        
        if not success:
            logger.error(f"Submission failed: {error}")
        
        return success, tx_hash
        
    except Exception as e:
        logger.error(f"Error creating submitter: {e}")
        return False, None


async def main():
    """Test the submission."""
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    topic_id = int(sys.argv[1]) if len(sys.argv) > 1 else 67
    value = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0123456789
    
    submitter = AlloraSubmitter()
    print(f"Wallet address: {submitter.wallet_address}")
    
    # Check if we can submit
    can_submit = await submitter.can_submit(topic_id)
    print(f"Can submit to topic {topic_id}: {can_submit}")
    
    if not can_submit:
        print("Worker is not whitelisted or cannot submit")
        return
    
    # Get topic info
    topic_info = await submitter.get_topic_info(topic_id)
    print(f"Topic info: {topic_info}")
    
    # Submit prediction
    success, tx_hash, error = await submitter.submit_prediction(topic_id, value)
    
    if success:
        print(f"✅ Submission successful! TX Hash: {tx_hash}")
    else:
        print(f"❌ Submission failed: {error}")


if __name__ == "__main__":
    asyncio.run(main())
