"""
ASGI Observability & OpenTelemetry-Compatible Tracing Middleware for FastAPI.
Instruments all inbound HTTP requests with:
- W3C Trace Context (traceparent) and X-Request-ID propagation
- Latency timing and high-precision duration calculation
- Path template normalization to prevent metric label cardinality explosion
- Automatic error classification and error counter increments
- Response telemetry headers (X-Response-Time-Ms, X-Request-ID)
"""

import time
import uuid
import re
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.observability.metrics import metrics_registry

logger = logging.getLogger("IGRS.Observability")

# Route normalization patterns to avoid cardinality explosion in Prometheus metrics
PATH_NORMALIZATION_PATTERNS = [
    (re.compile(r"^/grievance/\d+/status$"), "/grievance/{id}/status"),
    (re.compile(r"^/grievance/\d+/withdraw$"), "/grievance/{id}/withdraw"),
    (re.compile(r"^/grievance/\d+/resolution$"), "/grievance/{id}/resolution"),
    (re.compile(r"^/grievance/\d+/reassign$"), "/grievance/{id}/reassign"),
    (re.compile(r"^/grievance/\d+/auto-route$"), "/grievance/{id}/auto-route"),
    (re.compile(r"^/grievance/\d+/assign$"), "/grievance/{id}/assign"),
    (re.compile(r"^/grievance/\d+/audit-trail$"), "/grievance/{id}/audit-trail"),
    (re.compile(r"^/grievance/\d+/events$"), "/grievance/{id}/events"),
    (re.compile(r"^/grievance/\d+/retry$"), "/grievance/{id}/retry"),
    (re.compile(r"^/grievance/\d+$"), "/grievance/{id}"),
    (re.compile(r"^/analytics/forecast/[^/]+$"), "/analytics/forecast/{category}"),
]


def normalize_path(path: str) -> str:
    """Normalizes URL paths replacing dynamic IDs with placeholders."""
    for pattern, replacement in PATH_NORMALIZATION_PATTERNS:
        if pattern.match(path):
            return replacement
    return path


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # 1. Tracing ID generation or extraction (OpenTelemetry W3C traceparent standard)
        incoming_traceparent = request.headers.get("traceparent")
        incoming_req_id = request.headers.get("x-request-id")

        if incoming_traceparent and len(incoming_traceparent.split("-")) == 4:
            parts = incoming_traceparent.split("-")
            trace_id = parts[1]
            parent_span_id = parts[2]
        else:
            trace_id = uuid.uuid4().hex
            parent_span_id = uuid.uuid4().hex[:16]

        span_id = uuid.uuid4().hex[:16]
        traceparent = f"00-{trace_id}-{span_id}-01"
        request_id = incoming_req_id or str(uuid.uuid4())

        # Store in request state for access in endpoints if needed
        request.state.trace_id = trace_id
        request.state.request_id = request_id

        # 2. Timing
        start_time = time.perf_counter()
        method = request.method
        raw_path = request.url.path
        normalized_path = normalize_path(raw_path)

        # Skip metrics scraping itself from polluting Prometheus counts
        is_metrics_endpoint = raw_path in ["/metrics", "/metrics/"]

        try:
            response = await call_next(request)
            duration = time.perf_counter() - start_time
            status_code = response.status_code

            if not is_metrics_endpoint:
                # Record metrics
                labels = {
                    "method": method,
                    "path": normalized_path,
                    "status": str(status_code),
                }
                metrics_registry.http_requests_total.inc(labels=labels)
                metrics_registry.http_request_duration_seconds.observe(
                    duration,
                    labels={"method": method, "path": normalized_path}
                )

                if status_code >= 400:
                    metrics_registry.http_request_errors_total.inc(
                        labels={
                            "method": method,
                            "path": normalized_path,
                            "error": f"HTTP_{status_code}"
                        }
                    )

            # Inject telemetry headers into response
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time-Ms"] = f"{round(duration * 1000, 2)}ms"
            response.headers["traceparent"] = traceparent

            return response

        except Exception as exc:
            duration = time.perf_counter() - start_time
            if not is_metrics_endpoint:
                metrics_registry.http_requests_total.inc(
                    labels={"method": method, "path": normalized_path, "status": "500"}
                )
                metrics_registry.http_request_duration_seconds.observe(
                    duration,
                    labels={"method": method, "path": normalized_path}
                )
                metrics_registry.http_request_errors_total.inc(
                    labels={
                        "method": method,
                        "path": normalized_path,
                        "error": type(exc).__name__
                    }
                )
            logger.error(f"[Trace: {trace_id}] Unhandled error processing {method} {raw_path}: {exc}")
            raise exc
