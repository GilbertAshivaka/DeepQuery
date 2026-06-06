"""
Deep Query — Redis Client

Manages Redis connections for:
- Query result caching
- Neo4j subgraph caching
- Pub/sub for BM25 index updates and cache invalidation
"""

import json
import logging
from typing import Any, Dict, Optional

import redis.asyncio as aioredis
from redis import Redis

from core.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Redis client for caching and pub/sub operations."""

    def __init__(self):
        self._sync_client: Optional[Redis] = None
        self._async_client: Optional[aioredis.Redis] = None
        self._pubsub = None

    @property
    def sync_client(self) -> Redis:
        """Synchronous Redis client for blocking operations."""
        if self._sync_client is None:
            # Extract host and port from broker URL
            # Format: redis://localhost:6379/0
            parts = settings.celery_broker_url.replace("redis://", "").split("/")
            host_port = parts[0].split(":")
            host = host_port[0]
            port = int(host_port[1]) if len(host_port) > 1 else 6379
            db = int(parts[1]) if len(parts) > 1 else 0

            self._sync_client = Redis(
                host=host,
                port=port,
                db=db,
                decode_responses=True,
            )
            logger.info(f"Connected to Redis (sync) at {host}:{port}/{db}")
        return self._sync_client

    @property
    async def async_client(self) -> aioredis.Redis:
        """Async Redis client for non-blocking operations."""
        if self._async_client is None:
            # Extract connection details
            parts = settings.celery_broker_url.replace("redis://", "").split("/")
            host_port = parts[0].split(":")
            host = host_port[0]
            port = int(host_port[1]) if len(host_port) > 1 else 6379
            db = int(parts[1]) if len(parts) > 1 else 0

            self._async_client = await aioredis.from_url(
                f"redis://{host}:{port}/{db}",
                decode_responses=True,
            )
            logger.info(f"Connected to Redis (async) at {host}:{port}/{db}")
        return self._async_client

    # ── Caching ──────────────────────────────────────────────────

    def get(self, key: str) -> Optional[str]:
        """Get a value from cache."""
        try:
            return self.sync_client.get(key)
        except Exception as e:
            logger.error(f"Redis GET failed for key '{key}': {e}")
            return None

    def set(self, key: str, value: str, ttl_seconds: Optional[int] = None) -> bool:
        """Set a value in cache with optional TTL."""
        try:
            if ttl_seconds:
                self.sync_client.setex(key, ttl_seconds, value)
            else:
                self.sync_client.set(key, value)
            return True
        except Exception as e:
            logger.error(f"Redis SET failed for key '{key}': {e}")
            return False

    def get_json(self, key: str) -> Optional[Dict]:
        """Get and deserialize JSON from cache."""
        try:
            value = self.sync_client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Redis GET JSON failed for key '{key}': {e}")
            return None

    def set_json(self, key: str, data: Dict, ttl_seconds: Optional[int] = None) -> bool:
        """Serialize and set JSON in cache."""
        try:
            value = json.dumps(data)
            return self.set(key, value, ttl_seconds)
        except Exception as e:
            logger.error(f"Redis SET JSON failed for key '{key}': {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        try:
            self.sync_client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Redis DELETE failed for key '{key}': {e}")
            return False

    def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a pattern.

        Args:
            pattern: Redis key pattern (e.g., "query_cache:academic:*")

        Returns:
            Number of keys deleted.
        """
        try:
            keys = self.sync_client.keys(pattern)
            if keys:
                return self.sync_client.delete(*keys)
            return 0
        except Exception as e:
            logger.error(f"Redis DELETE PATTERN failed for '{pattern}': {e}")
            return 0

    def ping(self) -> bool:
        """Check Redis connection health."""
        try:
            return self.sync_client.ping()
        except Exception as e:
            logger.error(f"Redis PING failed: {e}")
            return False

    # ── Pub/Sub ──────────────────────────────────────────────────

    def publish(self, channel: str, message: str) -> bool:
        """Publish a message to a channel."""
        try:
            self.sync_client.publish(channel, message)
            return True
        except Exception as e:
            logger.error(f"Redis PUBLISH failed for channel '{channel}': {e}")
            return False

    def subscribe(self, *channels: str):
        """Subscribe to one or more channels.

        Returns a pubsub object that can be used to listen for messages.
        """
        try:
            pubsub = self.sync_client.pubsub()
            pubsub.subscribe(*channels)
            return pubsub
        except Exception as e:
            logger.error(f"Redis SUBSCRIBE failed: {e}")
            return None

    def close(self):
        """Close Redis connections."""
        if self._sync_client:
            self._sync_client.close()
        if self._async_client:
            # Async client close needs to be awaited, so we log a warning
            logger.warning("Async Redis client should be closed with await redis_client.async_client.close()")


# ── Module-level singleton ───────────────────────────────────
redis_client = RedisClient()
