"""
Deep Query — Query Result Cache

Redis-based caching for query results to reduce redundant pipeline executions.
Cache keys are constructed from normalized queries and user access roles.
"""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from core.redis_client import redis_client

logger = logging.getLogger(__name__)

# Cache TTL in seconds (24 hours default)
QUERY_CACHE_TTL = 24 * 60 * 60


def normalize_query(query: str) -> str:
    """Normalize a query string for cache key generation.

    Args:
        query: Raw query string.

    Returns:
        Normalized query (lowercase, stripped, single spaces).
    """
    # Lowercase, strip whitespace, collapse multiple spaces
    normalized = " ".join(query.lower().strip().split())
    return normalized


def build_cache_key(query: str, allowed_collections: List[str]) -> str:
    """Build a cache key from query and allowed collections.

    Args:
        query: User's query string.
        allowed_collections: Collections the user can access.

    Returns:
        SHA-256 hash cache key.
    """
    normalized_query = normalize_query(query)
    sorted_collections = sorted(allowed_collections)
    collections_str = ",".join(sorted_collections)

    # Hash the combination
    key_material = f"{normalized_query}|{collections_str}"
    key_hash = hashlib.sha256(key_material.encode()).hexdigest()

    return f"query_cache:{key_hash}"


def get_cached_result(query: str, allowed_collections: List[str]) -> Optional[Dict[str, Any]]:
    """Retrieve a cached query result.

    Args:
        query: User's query string.
        allowed_collections: Collections the user can access.

    Returns:
        Cached result dict, or None if not found.
    """
    cache_key = build_cache_key(query, allowed_collections)

    try:
        cached = redis_client.get_json(cache_key)
        if cached:
            logger.info(f"Cache HIT for query: {query[:50]}...")
            # Add cache hit indicator
            cached["cache_hit"] = True
            return cached
        else:
            logger.info(f"Cache MISS for query: {query[:50]}...")
            return None
    except Exception as e:
        logger.error(f"Cache GET failed: {e}")
        return None


def cache_query_result(
    query: str,
    allowed_collections: List[str],
    result: Dict[str, Any],
    ttl_seconds: int = QUERY_CACHE_TTL,
) -> bool:
    """Store a query result in cache.

    Args:
        query: User's query string.
        allowed_collections: Collections the user can access.
        result: Query result to cache.
        ttl_seconds: Time-to-live in seconds.

    Returns:
        True if cached successfully, False otherwise.
    """
    # Never cache INSUFFICIENT_CONTEXT responses
    if result.get("self_correction_status") == "INSUFFICIENT_CONTEXT":
        logger.info("Skipping cache for INSUFFICIENT_CONTEXT response")
        return False

    cache_key = build_cache_key(query, allowed_collections)

    try:
        # Add cache metadata
        result_with_meta = result.copy()
        result_with_meta["cache_hit"] = False  # This is a fresh result being cached

        success = redis_client.set_json(cache_key, result_with_meta, ttl_seconds)
        if success:
            logger.info(f"Cached result for query: {query[:50]}... (TTL={ttl_seconds}s)")
        return success
    except Exception as e:
        logger.error(f"Cache SET failed: {e}")
        return False


def invalidate_cache_for_collection(collection_name: str) -> int:
    """Invalidate all cached queries that include a specific collection.

    Args:
        collection_name: Collection name (e.g., 'academic').

    Returns:
        Number of cache entries deleted.
    """
    # Since our cache keys are hashed, we need to delete all query cache entries
    # This is a trade-off: we could store collection metadata separately, but
    # for simplicity, we flush all query cache when any collection is updated
    try:
        pattern = "query_cache:*"
        deleted = redis_client.delete_pattern(pattern)
        logger.info(
            f"Invalidated {deleted} cache entries for collection '{collection_name}'"
        )
        return deleted
    except Exception as e:
        logger.error(f"Cache invalidation failed: {e}")
        return 0


def flush_all_query_cache() -> int:
    """Flush the entire query result cache.

    Returns:
        Number of cache entries deleted.
    """
    try:
        pattern = "query_cache:*"
        deleted = redis_client.delete_pattern(pattern)
        logger.info(f"Flushed {deleted} query cache entries")
        return deleted
    except Exception as e:
        logger.error(f"Cache flush failed: {e}")
        return 0
