import os
import json
import time
import fnmatch
import logging
import threading
from typing import Optional, Any, Dict
from datetime import datetime, timezone

logger = logging.getLogger("IGRS.Cache")

# Standard TTLs as specified in architecture specs (Feature 2)
TTL_FORECAST = 1800   # 30 minutes
TTL_HOTSPOTS = 600    # 10 minutes
TTL_TRENDS = 3600     # 1 hour


class CacheService:
    """
    High-performance caching service with Redis and in-memory TTL fallback.
    Provides automatic JSON serialization, pattern-based cache invalidation,
    TTL expiration, and real-time hit/miss observability.
    """

    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis_client = None
        self._memory_cache: Dict[str, tuple[str, float]] = {}
        self._lock = threading.RLock()
        self.backend = "in-memory"
        
        # Telemetry / metrics
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
        }
        self._initialize_backend()

    def _initialize_backend(self):
        """Attempts connection to Redis, falls back to in-memory store if unreachable."""
        try:
            import redis
            client = redis.from_url(
                self.redis_url,
                socket_timeout=2,
                socket_connect_timeout=2,
                decode_responses=True
            )
            client.ping()
            self.redis_client = client
            self.backend = "redis"
            logger.info(f"Connected to Redis cache at {self.redis_url}")
        except Exception as e:
            self.redis_client = None
            self.backend = "in-memory"
            logger.info(
                f"Redis cache unavailable ({e}). Using thread-safe in-memory cache fallback. "
                "Set REDIS_URL to connect to a production Redis instance."
            )

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieves a cached item by key.
        Returns parsed JSON object, or None on cache miss / expiration.
        """
        if self.redis_client:
            try:
                raw = self.redis_client.get(key)
                if raw is not None:
                    with self._lock:
                        self._stats["hits"] += 1
                    return json.loads(raw)
                with self._lock:
                    self._stats["misses"] += 1
                return None
            except Exception as e:
                logger.warning(f"Redis GET failed for key '{key}': {e}. Checking in-memory.")

        # In-memory fallback with TTL check
        with self._lock:
            entry = self._memory_cache.get(key)
            if entry is not None:
                serialized, expires_at = entry
                if time.time() < expires_at:
                    self._stats["hits"] += 1
                    return json.loads(serialized)
                # Expired
                del self._memory_cache[key]

            self._stats["misses"] += 1
            return None

    def set(self, key: str, value: Any, ttl_seconds: int = 300) -> bool:
        """
        Stores an item in the cache with the given TTL in seconds.
        Serializes standard Python objects to JSON.
        """
        try:
            serialized = json.dumps(value, default=str)
        except Exception as e:
            logger.error(f"Failed to serialize cache value for key '{key}': {e}")
            return False

        if self.redis_client:
            try:
                self.redis_client.setex(name=key, time=ttl_seconds, value=serialized)
                with self._lock:
                    self._stats["sets"] += 1
                return True
            except Exception as e:
                logger.warning(f"Redis SETEX failed for key '{key}': {e}. Storing in-memory.")

        with self._lock:
            expires_at = time.time() + ttl_seconds
            self._memory_cache[key] = (serialized, expires_at)
            self._stats["sets"] += 1
            # Periodic cleanup of expired keys in memory
            if len(self._memory_cache) > 500:
                self._cleanup_expired()
            return True

    def delete(self, key: str) -> bool:
        """Deletes a specific key from cache."""
        deleted = False
        if self.redis_client:
            try:
                deleted = bool(self.redis_client.delete(key))
            except Exception as e:
                logger.warning(f"Redis DELETE failed for key '{key}': {e}")

        with self._lock:
            if key in self._memory_cache:
                del self._memory_cache[key]
                deleted = True
            if deleted:
                self._stats["deletes"] += 1
        return deleted

    def delete_pattern(self, pattern: str) -> int:
        """
        Invalidates all keys matching a glob pattern (e.g. 'analytics:*').
        Returns the number of keys removed.
        """
        count = 0
        if self.redis_client:
            try:
                matching_keys = list(self.redis_client.scan_iter(match=pattern))
                if matching_keys:
                    count = self.redis_client.delete(*matching_keys)
                    logger.info(f"Invalidated {count} Redis keys matching '{pattern}'")
            except Exception as e:
                logger.warning(f"Redis delete_pattern error for '{pattern}': {e}")

        # In-memory pattern purge
        with self._lock:
            matched_keys = [k for k in self._memory_cache.keys() if fnmatch.fnmatch(k, pattern)]
            for k in matched_keys:
                del self._memory_cache[k]
                count += 1
            self._stats["deletes"] += len(matched_keys)

        if count > 0:
            logger.info(f"Invalidated total {count} keys matching '{pattern}'")
        return count

    def clear(self) -> bool:
        """Flushes all cached entries."""
        if self.redis_client:
            try:
                self.redis_client.flushdb()
            except Exception as e:
                logger.warning(f"Redis flushdb failed: {e}")

        with self._lock:
            self._memory_cache.clear()
        return True

    def _cleanup_expired(self):
        """Purges expired items from in-memory cache."""
        now = time.time()
        expired = [k for k, (_, exp) in self._memory_cache.items() if now >= exp]
        for k in expired:
            del self._memory_cache[k]

    def get_stats(self) -> Dict[str, Any]:
        """Returns cache telemetry and status metrics."""
        with self._lock:
            hits = self._stats["hits"]
            misses = self._stats["misses"]
            total_requests = hits + misses
            hit_ratio = round((hits / total_requests * 100), 2) if total_requests > 0 else 0.0

            if self.redis_client:
                try:
                    info = self.redis_client.info(section="keyspace")
                    total_keys = sum(db.get("keys", 0) for db in info.values() if isinstance(db, dict))
                except Exception:
                    total_keys = len(self._memory_cache)
            else:
                self._cleanup_expired()
                total_keys = len(self._memory_cache)

            return {
                "backend": self.backend,
                "redis_connected": self.redis_client is not None,
                "hits": hits,
                "misses": misses,
                "hit_ratio_percent": hit_ratio,
                "sets": self._stats["sets"],
                "deletes": self._stats["deletes"],
                "active_cached_keys": total_keys,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }


# Global singleton instance
cache_service = CacheService()
