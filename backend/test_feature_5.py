"""
Automated Test Suite for Feature 5: Production-Grade Observability + CI/CD.
Validates:
1. Thread-safe Prometheus metric primitives (Counter, Gauge, Histogram, quantiles P50/P90/P95/P99)
2. Standard Prometheus text exposition format (version 0.0.4)
3. Observability ASGI Middleware (W3C traceparent, X-Request-ID, X-Response-Time-Ms, path normalization)
4. Grievance Redressal Multi-Stage Lifecycle Analytics Engine (Submission -> AI -> Assignment -> Action -> Resolution)
5. Observability & Health endpoints (/metrics, /observability/summary, /observability/lifecycle, /health, /health/ready, /health/live)
6. Asynchronous worker instrumentation & queue metrics
"""

import os
import sys
import unittest
import asyncio
import time
from datetime import datetime, timedelta
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.models import Base, User, UserRole, Grievance, GrievanceEvent
from app.observability.metrics import (
    MetricsRegistry,
    Counter,
    Gauge,
    Histogram,
    metrics_registry,
)
from app.observability.middleware import ObservabilityMiddleware, normalize_path
from app.observability.lifecycle_analyzer import (
    GrievanceLifecycleAnalyzer,
    compute_quantiles,
    format_duration,
)
from app.routes.observability import (
    get_prometheus_metrics,
    get_observability_summary,
    get_lifecycle_metrics,
    health_check,
    readiness_probe,
    liveness_probe,
)


class TestFeature5Observability(unittest.TestCase):
    """
    Comprehensive test suite for Feature 5 Observability & Lifecycle metrics.
    """

    def setUp(self):
        # Isolated SQLite in-memory test database
        self.engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # Dedicated isolated metrics registry for unit testing
        self.registry = MetricsRegistry()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)

    # --------------------------------------------------------------------------
    # 1. Metric Primitives (Counter, Gauge, Histogram, Quantiles)
    # --------------------------------------------------------------------------

    def test_counter_increments_and_labels(self):
        """Counters accurately increment and isolate distinct label dimensions."""
        counter = Counter("test_requests_total", "Test counter")
        counter.inc(1.0, labels={"method": "POST", "status": "201"})
        counter.inc(3.0, labels={"method": "POST", "status": "201"})
        counter.inc(2.0, labels={"method": "GET", "status": "200"})

        self.assertEqual(counter.get_value(labels={"method": "POST", "status": "201"}), 4.0)
        self.assertEqual(counter.get_value(labels={"method": "GET", "status": "200"}), 2.0)
        self.assertEqual(counter.get_total(), 6.0)

        with self.assertRaises(ValueError):
            counter.inc(-1.0)

    def test_gauge_operations(self):
        """Gauges correctly support set, inc, and dec."""
        gauge = Gauge("test_queue_depth", "Test gauge")
        gauge.set(10.0, labels={"queue": "primary"})
        self.assertEqual(gauge.get_value(labels={"queue": "primary"}), 10.0)

        gauge.inc(5.0, labels={"queue": "primary"})
        self.assertEqual(gauge.get_value(labels={"queue": "primary"}), 15.0)

        gauge.dec(3.0, labels={"queue": "primary"})
        self.assertEqual(gauge.get_value(labels={"queue": "primary"}), 12.0)

    def test_histogram_quantiles_and_buckets(self):
        """Histograms correctly compute P50, P90, P95, P99, mean and cumulative buckets."""
        hist = Histogram("test_latency_seconds", "Latency histogram", buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 5.0))

        # Observe values from 0.01s to 1.0s (100 samples)
        values = [i * 0.01 for i in range(1, 101)]
        for v in values:
            hist.observe(v, labels={"service": "gemini"})

        summary = hist.get_summary(labels={"service": "gemini"})
        self.assertEqual(summary["count"], 100)
        self.assertAlmostEqual(summary["mean"], 0.505, places=2)
        self.assertAlmostEqual(summary["p50"], 0.505, places=1)
        self.assertAlmostEqual(summary["p90"], 0.901, places=1)
        self.assertAlmostEqual(summary["p95"], 0.95, places=1)
        self.assertEqual(summary["min"], 0.01)
        self.assertEqual(summary["max"], 1.0)

    def test_timing_context_manager(self):
        """TimingContext accurately tracks elapsed execution duration."""
        hist = Histogram("test_block_duration", "Block timer")
        with self.registry.time_block(hist, labels={"op": "db_query"}):
            time.sleep(0.02)

        summary = hist.get_summary(labels={"op": "db_query"})
        self.assertEqual(summary["count"], 1)
        self.assertGreaterEqual(summary["sum"], 0.015)

    # --------------------------------------------------------------------------
    # 2. Prometheus Exposition Format
    # --------------------------------------------------------------------------

    def test_prometheus_exposition_format(self):
        """Registry exports standard Prometheus text format with HELP, TYPE, and buckets."""
        reg = MetricsRegistry()
        reg.http_requests_total.inc(1, labels={"method": "GET", "path": "/health", "status": "200"})
        reg.queue_depth.set(4, labels={"queue": "grievances"})
        reg.http_request_duration_seconds.observe(0.045, labels={"method": "GET", "path": "/health"})

        exposition = reg.generate_prometheus_exposition()
        self.assertIn("# HELP igrs_http_requests_total", exposition)
        self.assertIn("# TYPE igrs_http_requests_total counter", exposition)
        self.assertIn('igrs_http_requests_total{method="GET",path="/health",status="200"} 1.0', exposition)
        self.assertIn("# HELP igrs_queue_depth", exposition)
        self.assertIn("# TYPE igrs_queue_depth gauge", exposition)
        self.assertIn('igrs_queue_depth{queue="grievances"} 4.0', exposition)
        self.assertIn('igrs_http_request_duration_seconds_bucket{le="0.05",method="GET",path="/health"} 1', exposition)
        self.assertIn('igrs_http_request_duration_seconds_bucket{le="+Inf",method="GET",path="/health"} 1', exposition)
        self.assertIn('igrs_http_request_duration_seconds_count{method="GET",path="/health"} 1', exposition)

    # --------------------------------------------------------------------------
    # 3. Observability ASGI Middleware & Trace Headers
    # --------------------------------------------------------------------------

    def test_path_normalization(self):
        """URL paths with dynamic integer IDs or slug parameters are normalized."""
        self.assertEqual(normalize_path("/grievance/42"), "/grievance/{id}")
        self.assertEqual(normalize_path("/grievance/108/status"), "/grievance/{id}/status")
        self.assertEqual(normalize_path("/grievance/55/resolution"), "/grievance/{id}/resolution")
        self.assertEqual(normalize_path("/grievance/9/audit-trail"), "/grievance/{id}/audit-trail")
        self.assertEqual(normalize_path("/analytics/forecast/Water"), "/analytics/forecast/{category}")
        self.assertEqual(normalize_path("/health"), "/health")

    def test_middleware_dispatch_headers_and_metrics(self):
        """Middleware injects X-Request-ID, X-Response-Time-Ms, and W3C traceparent headers."""
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/grievance/12",
            "headers": [(b"host", b"localhost:8000")],
        }
        request = Request(scope)

        dummy_app = lambda req: None
        middleware = ObservabilityMiddleware(dummy_app)

        async def call_next(req):
            await asyncio.sleep(0.01)
            return JSONResponse({"message": "OK"}, status_code=200)

        initial_requests = metrics_registry.http_requests_total.get_total()
        response = asyncio.run(middleware.dispatch(request, call_next))

        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Request-ID", response.headers)
        self.assertIn("X-Response-Time-Ms", response.headers)
        self.assertIn("traceparent", response.headers)

        traceparent = response.headers["traceparent"]
        parts = traceparent.split("-")
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[0], "00")
        self.assertEqual(parts[3], "01")

        new_requests = metrics_registry.http_requests_total.get_total()
        self.assertEqual(new_requests, initial_requests + 1.0)

    def test_middleware_error_metric_tracking(self):
        """4xx and 5xx responses increment error counters in metrics registry."""
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/grievance/999",
            "headers": [],
        }
        request = Request(scope)
        middleware = ObservabilityMiddleware(lambda req: None)

        async def call_next_error(req):
            return JSONResponse({"detail": "Not found"}, status_code=404)

        initial_errors = metrics_registry.http_request_errors_total.get_total()
        response = asyncio.run(middleware.dispatch(request, call_next_error))

        self.assertEqual(response.status_code, 404)
        new_errors = metrics_registry.http_request_errors_total.get_total()
        self.assertEqual(new_errors, initial_errors + 1.0)

    # --------------------------------------------------------------------------
    # 4. Grievance Redressal Lifecycle Metrics Engine
    # --------------------------------------------------------------------------

    def test_format_duration_helper(self):
        """format_duration handles seconds, minutes, hours, and days."""
        self.assertEqual(format_duration(45), "45.0s")
        self.assertEqual(format_duration(120), "2.0m")
        self.assertEqual(format_duration(7200), "2.0h")
        self.assertEqual(format_duration(172800), "2.0d")
        self.assertEqual(format_duration(None), "N/A")

    def test_compute_quantiles_empty_and_populated(self):
        """compute_quantiles handles empty data safely and calculates accurate percentiles."""
        empty_res = compute_quantiles([])
        self.assertEqual(empty_res["count"], 0)
        self.assertEqual(empty_res["mean_seconds"], 0.0)

        data = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        res = compute_quantiles(data)
        self.assertEqual(res["count"], 10)
        self.assertEqual(res["mean_seconds"], 55.0)
        self.assertEqual(res["p50_seconds"], 55.0)
        self.assertEqual(res["min_seconds"], 10.0)
        self.assertEqual(res["max_seconds"], 100.0)

    def test_grievance_lifecycle_analysis_end_to_end(self):
        """
        Simulates end-to-end lifecycle for multiple grievances:
        Submission -> AI Classification -> Assignment -> Officer Action -> Resolution.
        Verifies calculated Average, P50, P95 resolution times, AI duration, and SLA compliance.
        """
        now = datetime.utcnow()

        # Seed User and Officer
        citizen = User(name="Test Citizen", email="citizen@test.com", password_hash="hash", role=UserRole.user)
        officer = User(name="Test Officer", email="officer@test.com", password_hash="hash", role=UserRole.officer, department="Water", region="Lucknow")
        self.db.add_all([citizen, officer])
        self.db.commit()

        # Grievance 1: Resolved within SLA
        # Timeline:
        # T0: Created
        # T+10s: AI Classified
        # T+30s: Assigned
        # T+90s: Officer Action (In Progress)
        # T+300s: Resolved (5 mins total)
        # SLA: +24h -> Compliant
        t0 = now - timedelta(hours=5)
        g1 = Grievance(
            user_id=citizen.id,
            description="Water burst in Sector 4",
            category="Water",
            priority="HIGH",
            region="Lucknow",
            status="Resolved",
            created_at=t0,
            processed_at=t0 + timedelta(seconds=10),
            assigned_officer_id=officer.id,
            sla_deadline=t0 + timedelta(hours=24),
            sla_breached=False
        )
        self.db.add(g1)
        self.db.commit()

        e1_1 = GrievanceEvent(grievance_id=g1.id, actor_role="citizen", actor_id=citizen.id, event_type="CREATED", old_value=None, new_value="Pending", timestamp=t0)
        e1_2 = GrievanceEvent(grievance_id=g1.id, actor_role="ai_worker", actor_id=None, event_type="AI_CLASSIFIED", old_value="Unclassified", new_value="Water / HIGH", timestamp=t0 + timedelta(seconds=10))
        e1_3 = GrievanceEvent(grievance_id=g1.id, actor_role="system", actor_id=None, event_type="ASSIGNED", old_value=None, new_value=officer.name, timestamp=t0 + timedelta(seconds=30))
        e1_4 = GrievanceEvent(grievance_id=g1.id, actor_role="officer", actor_id=officer.id, event_type="STATUS_UPDATED", old_value="Pending", new_value="In Progress", timestamp=t0 + timedelta(seconds=90))
        e1_5 = GrievanceEvent(grievance_id=g1.id, actor_role="officer", actor_id=officer.id, event_type="RESOLUTION_UPLOADED", old_value="In Progress", new_value="Resolved", timestamp=t0 + timedelta(seconds=300))
        self.db.add_all([e1_1, e1_2, e1_3, e1_4, e1_5])

        # Grievance 2: Resolved after SLA breach
        # Total resolution time = 48 hours (172800s)
        # SLA deadline = 12 hours
        t1 = now - timedelta(days=4)
        g2 = Grievance(
            user_id=citizen.id,
            description="Major pipeline collapse",
            category="Water",
            priority="CRITICAL",
            region="Lucknow",
            status="Resolved",
            created_at=t1,
            processed_at=t1 + timedelta(seconds=15),
            assigned_officer_id=officer.id,
            sla_deadline=t1 + timedelta(hours=12),
            sla_breached=True
        )
        self.db.add(g2)
        self.db.commit()

        e2_1 = GrievanceEvent(grievance_id=g2.id, actor_role="citizen", actor_id=citizen.id, event_type="CREATED", old_value=None, new_value="Pending", timestamp=t1)
        e2_2 = GrievanceEvent(grievance_id=g2.id, actor_role="ai_worker", actor_id=None, event_type="AI_CLASSIFIED", old_value="Unclassified", new_value="Water / CRITICAL", timestamp=t1 + timedelta(seconds=15))
        e2_3 = GrievanceEvent(grievance_id=g2.id, actor_role="system", actor_id=None, event_type="ASSIGNED", old_value=None, new_value=officer.name, timestamp=t1 + timedelta(seconds=60))
        e2_4 = GrievanceEvent(grievance_id=g2.id, actor_role="officer", actor_id=officer.id, event_type="STATUS_UPDATED", old_value="Pending", new_value="In Progress", timestamp=t1 + timedelta(hours=2))
        e2_5 = GrievanceEvent(grievance_id=g2.id, actor_role="officer", actor_id=officer.id, event_type="RESOLUTION_UPLOADED", old_value="In Progress", new_value="Resolved", timestamp=t1 + timedelta(hours=48))
        self.db.add_all([e2_1, e2_2, e2_3, e2_4, e2_5])

        # Grievance 3: Open / In Progress case
        t2 = now - timedelta(minutes=30)
        g3 = Grievance(
            user_id=citizen.id,
            description="Low water pressure",
            category="Water",
            priority="LOW",
            region="Lucknow",
            status="In Progress",
            created_at=t2,
            processed_at=t2 + timedelta(seconds=8),
            assigned_officer_id=officer.id,
            sla_deadline=t2 + timedelta(hours=96),
            sla_breached=False
        )
        self.db.add(g3)
        self.db.commit()

        e3_1 = GrievanceEvent(grievance_id=g3.id, actor_role="citizen", actor_id=citizen.id, event_type="CREATED", old_value=None, new_value="Pending", timestamp=t2)
        e3_2 = GrievanceEvent(grievance_id=g3.id, actor_role="ai_worker", actor_id=None, event_type="AI_CLASSIFIED", old_value="Unclassified", new_value="Water / LOW", timestamp=t2 + timedelta(seconds=8))
        e3_3 = GrievanceEvent(grievance_id=g3.id, actor_role="system", actor_id=None, event_type="ASSIGNED", old_value=None, new_value=officer.name, timestamp=t2 + timedelta(seconds=20))
        self.db.add_all([e3_1, e3_2, e3_3])
        self.db.commit()

        # Run Lifecycle Analyzer
        analyzer = GrievanceLifecycleAnalyzer()
        results = analyzer.analyze_lifecycle(self.db)

        # Assertions
        summary = results["summary"]
        self.assertEqual(summary["total_grievances"], 3)
        self.assertEqual(summary["resolved_count"], 2)
        self.assertEqual(summary["active_count"], 1)
        self.assertEqual(summary["sla_breached_count"], 1)
        self.assertEqual(summary["sla_compliance_rate_pct"], 50.0)  # 1 out of 2 resolved within SLA

        stages = results["lifecycle_stages"]
        # AI processing duration: 3 cases (10s, 15s, 8s) -> mean = 11.0s
        self.assertEqual(stages["ai_processing_time"]["count"], 3)
        self.assertAlmostEqual(stages["ai_processing_time"]["mean_seconds"], 11.0, places=1)

        # Assignment delay: 3 cases (20s, 45s, 12s)
        self.assertEqual(stages["assignment_delay"]["count"], 3)

        # Total resolution time: 2 cases (300s, 172800s)
        self.assertEqual(stages["total_resolution_time"]["count"], 2)
        self.assertGreater(stages["total_resolution_time"]["p95_seconds"], 300)

        # Category and Priority breakdowns
        self.assertIn("Water", results["by_category"])
        self.assertIn("HIGH", results["by_priority"])
        self.assertIn("CRITICAL", results["by_priority"])

    # --------------------------------------------------------------------------
    # 5. Observability Endpoints Direct Function Verification
    # --------------------------------------------------------------------------

    def test_metrics_endpoint_direct(self):
        """get_prometheus_metrics returns text/plain exposition format."""
        res = get_prometheus_metrics()
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.media_type.startswith("text/plain"))
        body = res.body.decode("utf-8")
        self.assertIn("igrs_http_requests_total", body)
        self.assertIn("igrs_system_uptime_seconds", body)

    def test_observability_summary_endpoint_direct(self):
        """get_observability_summary returns comprehensive JSON telemetry."""
        data = get_observability_summary()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("telemetry", data)
        self.assertIn("http", data["telemetry"])
        self.assertIn("ai_pipeline", data["telemetry"])
        self.assertIn("database", data["telemetry"])
        self.assertIn("queue", data["telemetry"])

    def test_observability_lifecycle_endpoint_direct(self):
        """get_lifecycle_metrics returns lifecycle stage metrics."""
        data = get_lifecycle_metrics(self.db)
        self.assertEqual(data["status"], "success")
        self.assertIn("lifecycle_metrics", data)
        self.assertIn("lifecycle_stages", data["lifecycle_metrics"])
        self.assertIn("total_resolution_time", data["lifecycle_metrics"]["lifecycle_stages"])

    def test_health_endpoints_direct(self):
        """health_check, readiness_probe, and liveness_probe succeed."""
        res_health = health_check(self.db)
        self.assertEqual(res_health["status"], "healthy")
        self.assertEqual(res_health["database"], "connected")

        res_ready = readiness_probe(self.db)
        self.assertTrue(res_ready["ready"])

        res_live = liveness_probe()
        self.assertTrue(res_live["alive"])


if __name__ == "__main__":
    unittest.main()
