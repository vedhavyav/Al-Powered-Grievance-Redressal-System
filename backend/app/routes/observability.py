"""
Observability & Health Probes API Routes for IGRS.
Endpoints:
- GET /metrics: Official Prometheus scraper exposition format (0.0.4)
- GET /observability/summary: JSON system telemetry, latency distributions, and error rates
- GET /observability/lifecycle: Multi-stage grievance lifecycle engineering metrics (P50, P95, SLA)
- GET /health: Overall application health status
- GET /health/ready: Readiness probe (DB + Queue connectivity)
- GET /health/live: Liveness probe
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.connection import get_db
from app.observability.metrics import metrics_registry
from app.observability.lifecycle_analyzer import lifecycle_analyzer
from app.queue.queue_service import queue_service
from app.cache.cache_service import cache_service

router = APIRouter(tags=["Observability & Health"])


@router.get(
    "/metrics",
    summary="Prometheus Metrics Exposition",
    response_class=Response,
    responses={
        200: {
            "content": {"text/plain; version=0.0.4; charset=utf-8": {}},
            "description": "Standard Prometheus text exposition format",
        }
    }
)
def get_prometheus_metrics():
    """
    Standard Prometheus exposition endpoint.
    Scraped periodically by Prometheus / Grafana Agent.
    """
    # Sync current queue depths before formatting
    try:
        q_stats = queue_service.get_stats()
        metrics_registry.queue_depth.set(q_stats.get("queue_size", 0))
        metrics_registry.dlq_depth.set(q_stats.get("dlq_size", 0))
    except Exception:
        pass

    exposition = metrics_registry.generate_prometheus_exposition()
    return Response(content=exposition, media_type="text/plain; version=0.0.4; charset=utf-8")


@router.get("/observability/summary", summary="System Telemetry & Metrics Summary")
def get_observability_summary():
    """
    Returns aggregated JSON telemetry including HTTP request latency percentiles (P50, P95, P99),
    error rates, AI inference performance, database latency, and queue depths.
    """
    summary = metrics_registry.get_summary()

    # Enrich with queue and cache stats
    try:
        summary["queue"]["stats"] = queue_service.get_stats()
    except Exception:
        pass

    try:
        summary["cache"] = cache_service.get_stats()
    except Exception:
        pass

    return {
        "status": "healthy",
        "telemetry": summary
    }


@router.get("/observability/lifecycle", summary="Grievance Redressal Lifecycle Metrics")
def get_lifecycle_metrics(db: Session = Depends(get_db)):
    """
    Computes statistical engineering metrics across grievance event timelines:
    Submission -> AI Classification -> Assignment -> Officer Action -> Resolution.
    Includes Mean, P50, P95, Min, Max durations, SLA compliance rates, and category breakdowns.
    """
    lifecycle_data = lifecycle_analyzer.analyze_lifecycle(db)
    return {
        "status": "success",
        "lifecycle_metrics": lifecycle_data
    }


@router.get("/health", summary="Overall Health Check")
def health_check(db: Session = Depends(get_db)):
    """
    Comprehensive health check probing database and queue connectivity.
    """
    db_healthy = False
    try:
        db.execute(text("SELECT 1"))
        db_healthy = True
    except Exception:
        db_healthy = False

    q_stats = queue_service.get_stats()

    is_healthy = db_healthy
    status_str = "healthy" if is_healthy else "degraded"

    return {
        "status": status_str,
        "database": "connected" if db_healthy else "disconnected",
        "queue_backend": q_stats.get("backend", "unknown"),
        "queue_size": q_stats.get("queue_size", 0),
        "dlq_size": q_stats.get("dlq_size", 0),
        "uptime_seconds": round(metrics_registry.system_uptime_seconds.get_value(), 1),
    }


@router.get("/health/ready", summary="Kubernetes Readiness Probe")
def readiness_probe(db: Session = Depends(get_db)):
    """
    Kubernetes readiness check: verifies backend is ready to accept traffic.
    """
    try:
        db.execute(text("SELECT 1"))
        return {"ready": True, "database": "connected"}
    except Exception as e:
        return Response(
            content='{"ready": false, "error": "Database unavailable"}',
            status_code=503,
            media_type="application/json"
        )


@router.get("/health/live", summary="Kubernetes Liveness Probe")
def liveness_probe():
    """
    Kubernetes liveness check: verifies process is alive and responsive.
    """
    return {"alive": True}
