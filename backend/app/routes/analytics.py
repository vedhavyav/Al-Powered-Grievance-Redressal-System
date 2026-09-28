from fastapi import APIRouter, HTTPException, Query, Response, Depends
from typing import Optional

from app.services.analytics_service import generate_forecast
from app.services.retrain_service import retrain_forecast_models
from app.services.hotspot_service import detect_hotspots
from app.services.hotspot_trend_service import get_hotspot_trends
from app.cache.cache_service import (
    cache_service,
    TTL_FORECAST,
    TTL_HOTSPOTS,
    TTL_TRENDS
)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/forecast/{category}")
def get_forecast(category: str, response: Response):
    """
    Return forecast + smart summary for a grievance category.
    Cached in Redis / memory for 30 minutes (TTL_FORECAST = 1800s).
    """
    cache_key = f"analytics:forecast:{category.strip().lower()}"
    cached = cache_service.get(cache_key)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        cached["cached"] = True
        return cached

    result = generate_forecast(category)
    if "error" in result and result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result["error"])

    # Store in cache
    cache_service.set(cache_key, result, ttl_seconds=TTL_FORECAST)
    response.headers["X-Cache"] = "MISS"
    result["cached"] = False
    return result


@router.get("/hotspots")
def get_hotspots(
    response: Response,
    limit: int = Query(default=10, ge=1, le=100),
    use_clustering: bool = True
):
    """
    Return macro and micro hotspots.
    Cached in Redis / memory for 10 minutes (TTL_HOTSPOTS = 600s).
    """
    cache_key = f"analytics:hotspots:{limit}:{use_clustering}"
    cached = cache_service.get(cache_key)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return cached

    result = detect_hotspots(limit=limit, use_clustering=use_clustering)
    cache_service.set(cache_key, result, ttl_seconds=TTL_HOTSPOTS)
    response.headers["X-Cache"] = "MISS"
    return result


@router.get("/hotspots/trends")
def get_hotspot_trend(
    response: Response,
    limit: int = Query(default=5, ge=1, le=50)
):
    """
    Hybrid insight: real hotspots + predicted trend.
    Cached in Redis / memory for 1 hour (TTL_TRENDS = 3600s).
    """
    cache_key = f"analytics:hotspots:trends:{limit}"
    cached = cache_service.get(cache_key)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return cached

    result = get_hotspot_trends(limit=limit)
    cache_service.set(cache_key, result, ttl_seconds=TTL_TRENDS)
    response.headers["X-Cache"] = "MISS"
    return result


from app.auth.dependencies import require_admin


@router.post("/retrain")
def retrain_model(admin=Depends(require_admin)):
    """
    Force retraining using real grievance data (Admin only).
    Automatically invalidates analytics cache upon retraining.
    """
    success = retrain_forecast_models()
    
    # Invalidate all analytics caches on model update
    invalidated_count = cache_service.delete_pattern("analytics:*")

    if not success:
        return {
            "message": "Not enough data yet. Using trained data model.",
            "invalidated_cache_keys": invalidated_count
        }
    return {
        "message": "Model retrained successfully using real data.",
        "invalidated_cache_keys": invalidated_count
    }


# Cache Telemetry & Management Endpoints

@router.get("/cache/stats")
def get_cache_stats():
    """
    Returns Redis / memory cache metrics:
    hits, misses, hit ratio, active cached keys, backend type.
    """
    return cache_service.get_stats()


@router.post("/cache/clear")
def clear_cache(
    pattern: Optional[str] = Query(default="analytics:*"),
    admin=Depends(require_admin)
):
    """
    Manually invalidates cached keys matching the given pattern (Admin only).
    Use pattern='*' to flush all keys.
    """
    if pattern == "*":
        cache_service.clear()
        return {"message": "All cache entries cleared successfully."}
    
    removed = cache_service.delete_pattern(pattern)
    return {
        "message": f"Cache entries matching pattern '{pattern}' purged.",
        "removed_keys_count": removed
    }