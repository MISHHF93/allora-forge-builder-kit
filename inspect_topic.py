#!/usr/bin/env python3
"""Inspect and print metadata for a given Allora topic using the Python SDK."""

import os
import sys
import asyncio
from pathlib import Path

# CORRECTED IMPORT: AlloraAPIClient for Python is in a different module
from allora_sdk.api_client import AlloraAPIClient
from pipeline_utils import setup_logging

LOG_FILE = Path("logs/inspect.log")

async def inspect_topic(topic_id: int):
    logger = setup_logging("inspect", log_file=LOG_FILE)

    # Initialize the API client
    # Note: The Python client initialization differs from TypeScript.
    # It typically does not require a chain slug for basic API queries.
    client = AlloraAPIClient()

    logger.info(f"Fetching all topics to find topic {topic_id}...")
    try:
        topics = await client.get_all_topics()
    except Exception as e:
        logger.error(f"Failed to fetch topics list: {e}")
        return

    matched = [t for t in topics if getattr(t, "topic_id", None) == topic_id]
    if not matched:
        print(f"❗ Topic {topic_id} not found in the network.")
        return

    topic = matched[0]
    print("\n📋 Topic Metadata:")
    for field, value in topic.model_dump().items():
        print(f"  {field}: {value}")

    # The 'is_active' status is included in the topic data from get_all_topics()
    print(f"\n✅ Topic {topic_id} is active: {topic.is_active}")

if __name__ == "__main__":
    # Get topic ID from environment or command line
    if len(sys.argv) > 1:
        tid = int(sys.argv[1])
    else:
        tid = int(os.getenv("TOPIC_ID", "67"))
    asyncio.run(inspect_topic(tid))
