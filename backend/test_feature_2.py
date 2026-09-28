import os
import sys
import unittest
from starlette.responses import Response

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.cache.cache_service import CacheService, cache_service, TTL_FORECAST, TTL_HOTSPOTS, TTL_TRENDS
from app.db.models import Grievance
from app.routes.analytics import get_cache_stats, clear_cache, get_hotspots, get_forecast, get_hotspot_trend


class TestFeature2CacheAndDatabase(unittest.TestCase):
    """
    Test suite for Feature 2:
    - Redis & In-memory Cache Service
    - Cache TTL, invalidation patterns, and metrics
    - Database composite and single-column indexes on Grievance
    - Analytics endpoints caching behavior (HIT vs MISS headers, cache invalidation)
    """

    def setUp(self):
        # Clear cache before each test
        cache_service.clear()

    def test_cache_service_set_get_miss(self):
        """Test basic cache set, get, miss, and hit accounting."""
        cache = CacheService()
        cache.clear()

        # Miss
        val = cache.get("test:key:1")
        self.assertIsNone(val)

        # Set & Hit
        test_payload = {"status": "ok", "count": 42, "items": ["a", "b"]}
        cache.set("test:key:1", test_payload, ttl_seconds=60)
        cached_val = cache.get("test:key:1")
        self.assertEqual(cached_val, test_payload)

        # Check stats
        stats = cache.get_stats()
        self.assertGreaterEqual(stats["hits"], 1)
        self.assertGreaterEqual(stats["misses"], 1)
        self.assertGreater(stats["hit_ratio_percent"], 0.0)

    def test_cache_pattern_invalidation(self):
        """Test pattern-based invalidation for analytics:* namespaces."""
        cache = CacheService()
        cache.clear()

        cache.set("analytics:forecast:water", {"trend": "up"}, ttl_seconds=1800)
        cache.set("analytics:forecast:electricity", {"trend": "down"}, ttl_seconds=1800)
        cache.set("analytics:hotspots:10:True", {"hotspots": []}, ttl_seconds=600)
        cache.set("user:profile:123", {"name": "Test"}, ttl_seconds=300)

        # Invalidate only analytics:*
        deleted_count = cache.delete_pattern("analytics:*")
        self.assertEqual(deleted_count, 3)

        # Analytics keys should be gone
        self.assertIsNone(cache.get("analytics:forecast:water"))
        self.assertIsNone(cache.get("analytics:forecast:electricity"))
        self.assertIsNone(cache.get("analytics:hotspots:10:True"))

        # Unrelated key remains
        self.assertIsNotNone(cache.get("user:profile:123"))

    def test_database_model_indexes(self):
        """Verify the required PostgreSQL indexes exist on Grievance model."""
        index_names = {idx.name for idx in Grievance.__table__.indexes}
        
        expected_indexes = {
            "idx_grievance_category",
            "idx_grievance_created_at",
            "idx_grievance_region",
            "idx_grievance_status_priority"
        }

        for exp in expected_indexes:
            self.assertIn(
                exp,
                index_names,
                f"Expected index '{exp}' not found in Grievance table indexes: {index_names}"
            )

        # Verify composite columns for idx_grievance_status_priority
        comp_idx = next(idx for idx in Grievance.__table__.indexes if idx.name == "idx_grievance_status_priority")
        col_names = [col.name for col in comp_idx.columns]
        self.assertEqual(col_names, ["status", "priority"])

    def test_analytics_cache_endpoints(self):
        """Test /analytics/cache/stats and /analytics/cache/clear endpoints."""
        # 1. Fetch stats
        data = get_cache_stats()
        self.assertIn("backend", data)
        self.assertIn("hits", data)
        self.assertIn("misses", data)
        self.assertIn("hit_ratio_percent", data)

        # 2. Add item to cache and clear
        cache_service.set("analytics:test:entry", {"foo": "bar"}, ttl_seconds=300)
        clear_res = clear_cache(pattern="analytics:*")
        self.assertIn("purged", clear_res["message"])
        self.assertIsNone(cache_service.get("analytics:test:entry"))

    from unittest.mock import patch

    @patch("app.routes.analytics.detect_hotspots")
    def test_analytics_hotspots_caching(self, mock_detect):
        """Test X-Cache header and caching on /analytics/hotspots."""
        mock_detect.return_value = {
            "region_hotspots": [{"region": "Lucknow", "complaint_count": 12}]
        }
        cache_service.delete_pattern("analytics:hotspots*")

        # First request -> Cache MISS
        res1 = Response()
        data1 = get_hotspots(response=res1, limit=5, use_clustering=False)
        self.assertEqual(res1.headers.get("X-Cache"), "MISS")
        self.assertEqual(mock_detect.call_count, 1)

        # Second request -> Cache HIT (function should NOT be called again)
        res2 = Response()
        data2 = get_hotspots(response=res2, limit=5, use_clustering=False)
        self.assertEqual(res2.headers.get("X-Cache"), "HIT")
        self.assertEqual(mock_detect.call_count, 1)
        self.assertEqual(data1, data2)


if __name__ == "__main__":
    unittest.main()
