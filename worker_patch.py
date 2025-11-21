"""
Monkey-patch for Allora SDK worker to handle 404 on is_worker_registered_in_topic_id

This patches the AlloraWorker.run() method to gracefully handle the case where
the gRPC endpoint returns 404 (UNIMPLEMENTED) for the is_worker_registered_in_topic_id call.

The error occurs because the testnet gRPC endpoint may not have this service fully
implemented. We bypass the check and proceed directly to submission.
"""

import logging
import asyncio
from allora_sdk.worker.worker import AlloraWorker

logger = logging.getLogger(__name__)

# Save the original run method
_original_run = AlloraWorker.run

async def _patched_run(self, timeout=None):
    """
    Patched version of AlloraWorker.run that gracefully handles
    404 errors on is_worker_registered_in_topic_id
    """
    from allora_sdk.worker.worker import Context
    from allora_sdk.protos.emissions.v9 import IsWorkerRegisteredInTopicIdRequest
    from allora_sdk.rpc_client.tx_manager import FeeTier
    import async_timeout
    
    ctx = Context()
    self._ctx = ctx
    self._prediction_queue = asyncio.Queue()
    
    self._setup_signal_handlers(ctx)
    
    logger.debug(f"Starting Allora worker for topic {self.topic_id}")
    
    try:
        # Try to check if worker is registered
        # This may fail with 404 on testnet if the service is not fully implemented
        worker_registered = False
        try:
            resp = self.client.emissions.query.is_worker_registered_in_topic_id(
                IsWorkerRegisteredInTopicIdRequest(
                    topic_id=self.topic_id,
                    address=str(self.wallet.address()),
                ),
            )
            worker_registered = resp.is_registered
            logger.debug(f"Worker registration status: {worker_registered}")
        except Exception as e:
            # Check if this is a 404 UNIMPLEMENTED error
            error_msg = str(e)
            if "404" in error_msg or "UNIMPLEMENTED" in error_msg:
                logger.warning(f"⚠️  Cannot check worker registration (endpoint error): {type(e).__name__}")
                logger.warning(f"   Details: {error_msg[:200]}")
                logger.info("   Proceeding without pre-registration check...")
                worker_registered = False  # Assume not registered, try to register
            else:
                # Re-raise if it's a different error
                raise
        
        # If not registered, try to register
        if not worker_registered:
            logger.debug(f"Registering worker {str(self.wallet.address())} for topic {self.topic_id}")
            try:
                resp = await self.client.emissions.tx.register(
                    topic_id=self.topic_id,
                    owner_addr=str(self.wallet.address()),
                    sender_addr=str(self.wallet.address()),
                    is_reputer=False,
                    fee_tier=FeeTier.PRIORITY,
                )
                logger.debug(f"Registration response: {resp}")
            except Exception as e:
                # If registration also fails, log but continue
                logger.warning(f"⚠️  Worker registration attempt failed: {type(e).__name__}")
                logger.warning(f"   Details: {str(e)[:200]}")
                logger.info("   Proceeding to submission anyway...")
        
        # Continue with the actual submission
        if timeout:
            try:
                async with async_timeout.timeout(timeout):
                    async for prediction in self._run_with_context(ctx):
                        yield prediction
            except asyncio.TimeoutError:
                logger.debug(f"Worker stopped after {timeout}s timeout")
        else:
            async for prediction in self._run_with_context(ctx):
                yield prediction
                
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.debug("Worker stopped by cancellation")
        ctx.cancel()
    finally:
        ctx.cancel()
        if self.client:
            await self.client.close()


def apply_worker_patch():
    """Apply the patch to AlloraWorker"""
    AlloraWorker.run = _patched_run
    logger.info("✅ Allora Worker patch applied (handles 404 on is_worker_registered_in_topic_id)")


if __name__ == "__main__":
    print("This module should be imported before using AlloraWorker")
    print("Usage: from worker_patch import apply_worker_patch; apply_worker_patch()")
