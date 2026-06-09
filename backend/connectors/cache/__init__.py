"""Ephemeral read-cache — storage without ingestion (guide §7)."""

from connectors.cache.cache import cache_get, cache_key, cache_set

__all__ = ["cache_get", "cache_set", "cache_key"]
