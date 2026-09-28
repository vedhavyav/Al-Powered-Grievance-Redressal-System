"""
Production-Grade Prometheus & OpenTelemetry Metrics System for IGRS.
Provides:
- Thread-safe metric primitives (Counter, Gauge, Histogram with configurable buckets)
- Automatic quantile / percentile computation (P50, P75, P90, P95, P99, Mean)
- Prometheus Exposition Format generator (text/plain; version=0.0.4)
- Context managers & decorators for latency timing
- JSON serialization for API monitoring dashboards
"""

import time
import math
import bisect
import threading
from typing import Dict, Any, List, Optional, Tuple, Callable
from collections import defaultdict


def _normalize_labels(labels: Optional[Dict[str, Any]]) -> Tuple[Tuple[str, str], ...]:
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def _labels_to_prometheus_str(labels_tuple: Tuple[Tuple[str, str], ...]) -> str:
    if not labels_tuple:
        return ""
    joined = ",".join(f'{k}="{v}"' for k, v in labels_tuple)
    return f"{{{joined}}}"


class Metric:
    def __init__(self, name: str, description: str, metric_type: str):
        self.name = name
        self.description = description
        self.metric_type = metric_type
        self._lock = threading.Lock()


class Counter(Metric):
    def __init__(self, name: str, description: str):
        super().__init__(name, description, "counter")
        self._values: Dict[Tuple[Tuple[str, str], ...], float] = defaultdict(float)

    def inc(self, amount: float = 1.0, labels: Optional[Dict[str, Any]] = None):
        if amount < 0:
            raise ValueError("Counter increments must be non-negative")
        key = _normalize_labels(labels)
        with self._lock:
            self._values[key] += amount

    def get_value(self, labels: Optional[Dict[str, Any]] = None) -> float:
        key = _normalize_labels(labels)
        with self._lock:
            return self._values.get(key, 0.0)

    def get_total(self) -> float:
        with self._lock:
            return sum(self._values.values())

    def get_all(self) -> Dict[Tuple[Tuple[str, str], ...], float]:
        with self._lock:
            return dict(self._values)


class Gauge(Metric):
    def __init__(self, name: str, description: str):
        super().__init__(name, description, "gauge")
        self._values: Dict[Tuple[Tuple[str, str], ...], float] = defaultdict(float)

    def set(self, value: float, labels: Optional[Dict[str, Any]] = None):
        key = _normalize_labels(labels)
        with self._lock:
            self._values[key] = float(value)

    def inc(self, amount: float = 1.0, labels: Optional[Dict[str, Any]] = None):
        key = _normalize_labels(labels)
        with self._lock:
            self._values[key] += amount

    def dec(self, amount: float = 1.0, labels: Optional[Dict[str, Any]] = None):
        key = _normalize_labels(labels)
        with self._lock:
            self._values[key] -= amount

    def get_value(self, labels: Optional[Dict[str, Any]] = None) -> float:
        key = _normalize_labels(labels)
        with self._lock:
            return self._values.get(key, 0.0)

    def get_all(self) -> Dict[Tuple[Tuple[str, str], ...], float]:
        with self._lock:
            return dict(self._values)


DEFAULT_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class Histogram(Metric):
    def __init__(self, name: str, description: str, buckets: Tuple[float, ...] = DEFAULT_LATENCY_BUCKETS):
        super().__init__(name, description, "histogram")
        self.buckets = tuple(sorted(buckets))
        self._counts: Dict[Tuple[Tuple[str, str], ...], int] = defaultdict(int)
        self._sums: Dict[Tuple[Tuple[str, str], ...], float] = defaultdict(float)
        self._bucket_counts: Dict[Tuple[Tuple[str, str], ...], List[int]] = defaultdict(
            lambda: [0] * len(self.buckets)
        )
        self._samples: Dict[Tuple[Tuple[str, str], ...], List[float]] = defaultdict(list)
        self._max_samples = 2000  # Reservoir sample cap for quantile calculations

    def observe(self, value: float, labels: Optional[Dict[str, Any]] = None):
        value = float(value)
        key = _normalize_labels(labels)
        with self._lock:
            self._counts[key] += 1
            self._sums[key] += value

            # Update Prometheus cumulative bucket counts
            bucket_list = self._bucket_counts[key]
            for idx, b_bound in enumerate(self.buckets):
                if value <= b_bound:
                    bucket_list[idx] += 1

            # Reservoir sample for exact percentile computation
            samples = self._samples[key]
            if len(samples) < self._max_samples:
                samples.append(value)
            else:
                # Replace with probability
                import random
                idx = random.randint(0, self._counts[key] - 1)
                if idx < self._max_samples:
                    samples[idx] = value

    def get_summary(self, labels: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        key = _normalize_labels(labels)
        with self._lock:
            count = self._counts.get(key, 0)
            total_sum = self._sums.get(key, 0.0)
            samples = sorted(self._samples.get(key, []))

        mean = (total_sum / count) if count > 0 else 0.0

        def quantile(q: float) -> float:
            if not samples:
                return 0.0
            k = (len(samples) - 1) * q
            f = math.floor(k)
            c = math.ceil(k)
            if f == c:
                return samples[int(k)]
            d0 = samples[int(f)] * (c - k)
            d1 = samples[int(c)] * (k - f)
            return d0 + d1

        return {
            "count": count,
            "sum": round(total_sum, 4),
            "mean": round(mean, 4),
            "p50": round(quantile(0.50), 4),
            "p75": round(quantile(0.75), 4),
            "p90": round(quantile(0.90), 4),
            "p95": round(quantile(0.95), 4),
            "p99": round(quantile(0.99), 4),
            "min": round(samples[0], 4) if samples else 0.0,
            "max": round(samples[-1], 4) if samples else 0.0,
        }

    def get_global_summary(self) -> Dict[str, Any]:
        """Aggregates all label combinations for global percentile tracking."""
        with self._lock:
            total_count = sum(self._counts.values())
            total_sum = sum(self._sums.values())
            all_samples = []
            for s in self._samples.values():
                all_samples.extend(s)
            all_samples.sort()

        mean = (total_sum / total_count) if total_count > 0 else 0.0

        def quantile(q: float) -> float:
            if not all_samples:
                return 0.0
            k = (len(all_samples) - 1) * q
            f = math.floor(k)
            c = math.ceil(k)
            if f == c:
                return all_samples[int(k)]
            d0 = all_samples[int(f)] * (c - k)
            d1 = all_samples[int(c)] * (k - f)
            return d0 + d1

        return {
            "count": total_count,
            "sum": round(total_sum, 4),
            "mean": round(mean, 4),
            "p50": round(quantile(0.50), 4),
            "p75": round(quantile(0.75), 4),
            "p90": round(quantile(0.90), 4),
            "p95": round(quantile(0.95), 4),
            "p99": round(quantile(0.99), 4),
            "min": round(all_samples[0], 4) if all_samples else 0.0,
            "max": round(all_samples[-1], 4) if all_samples else 0.0,
        }


class TimingContext:
    def __init__(self, histogram: Histogram, labels: Optional[Dict[str, Any]] = None):
        self.histogram = histogram
        self.labels = labels
        self.start_time: float = 0.0
        self.elapsed: float = 0.0

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.elapsed = time.perf_counter() - self.start_time
        self.histogram.observe(self.elapsed, self.labels)


class MetricsRegistry:
    """
    Centralized thread-safe registry housing application metrics.
    Generates standard Prometheus text exposition format (version 0.0.4).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._metrics: Dict[str, Metric] = {}
        self.start_time = time.time()
        self._init_standard_metrics()

    def _init_standard_metrics(self):
        # 1. HTTP Request Latency & Counts
        self.http_requests_total = self.register_counter(
            "igrs_http_requests_total",
            "Total number of HTTP requests processed by IGRS backend"
        )
        self.http_request_errors_total = self.register_counter(
            "igrs_http_request_errors_total",
            "Total number of HTTP requests resulting in 4xx or 5xx responses"
        )
        self.http_request_duration_seconds = self.register_histogram(
            "igrs_http_request_duration_seconds",
            "HTTP request duration in seconds",
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0)
        )

        # 2. AI Pipeline Latency & Success/Failure Rates
        self.ai_requests_total = self.register_counter(
            "igrs_ai_requests_total",
            "Total number of Gemini / NLP AI classification requests"
        )
        self.ai_errors_total = self.register_counter(
            "igrs_ai_errors_total",
            "Total number of AI classification failures"
        )
        self.ai_request_duration_seconds = self.register_histogram(
            "igrs_ai_request_duration_seconds",
            "Duration of AI model inference and solution generation in seconds",
            buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 3.5, 5.0, 8.0, 15.0)
        )

        # 3. Database Query Latency & Performance
        self.database_query_duration_seconds = self.register_histogram(
            "igrs_database_query_duration_seconds",
            "PostgreSQL database query execution duration in seconds",
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
        )

        # 4. Message Queue & Async Processing Latency
        self.queue_wait_duration_seconds = self.register_histogram(
            "igrs_queue_wait_duration_seconds",
            "Duration a grievance job waited in message queue before worker dequeue",
            buckets=(0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
        )
        self.grievance_processing_duration_seconds = self.register_histogram(
            "igrs_grievance_processing_duration_seconds",
            "Total end-to-end asynchronous processing time per complaint",
            buckets=(0.5, 1.0, 2.0, 3.5, 5.0, 10.0, 20.0, 60.0)
        )
        self.queue_depth = self.register_gauge(
            "igrs_queue_depth",
            "Current number of pending grievance jobs in message queue"
        )
        self.dlq_depth = self.register_gauge(
            "igrs_dlq_depth",
            "Current number of failed jobs parked in Dead-Letter Queue"
        )

        # 5. Domain Metrics & Active Cases
        self.active_grievances = self.register_gauge(
            "igrs_active_grievances",
            "Count of active non-terminal grievances in the system"
        )
        self.system_uptime_seconds = self.register_gauge(
            "igrs_system_uptime_seconds",
            "Time elapsed since IGRS backend initialized in seconds"
        )

    def register_counter(self, name: str, description: str) -> Counter:
        with self._lock:
            if name in self._metrics:
                return self._metrics[name]  # type: ignore
            metric = Counter(name, description)
            self._metrics[name] = metric
            return metric

    def register_gauge(self, name: str, description: str) -> Gauge:
        with self._lock:
            if name in self._metrics:
                return self._metrics[name]  # type: ignore
            metric = Gauge(name, description)
            self._metrics[name] = metric
            return metric

    def register_histogram(self, name: str, description: str, buckets: Tuple[float, ...] = DEFAULT_LATENCY_BUCKETS) -> Histogram:
        with self._lock:
            if name in self._metrics:
                return self._metrics[name]  # type: ignore
            metric = Histogram(name, description, buckets)
            self._metrics[name] = metric
            return metric

    def time_block(self, histogram: Histogram, labels: Optional[Dict[str, Any]] = None) -> TimingContext:
        """Context manager to measure execution time of a code block."""
        return TimingContext(histogram, labels)

    def generate_prometheus_exposition(self) -> str:
        """
        Formats all registered metrics according to Prometheus text exposition format (version 0.0.4).
        Compatible with Prometheus scraper, Grafana Agent, and OpenTelemetry collector.
        """
        # Update uptime gauge
        self.system_uptime_seconds.set(time.time() - self.start_time)

        lines: List[str] = []
        with self._lock:
            all_metrics = list(self._metrics.values())

        for metric in all_metrics:
            lines.append(f"# HELP {metric.name} {metric.description}")
            lines.append(f"# TYPE {metric.name} {metric.metric_type}")

            if isinstance(metric, Counter):
                values = metric.get_all()
                if not values:
                    lines.append(f"{metric.name} 0.0")
                else:
                    for labels_tuple, val in sorted(values.items()):
                        label_str = _labels_to_prometheus_str(labels_tuple)
                        lines.append(f"{metric.name}{label_str} {val}")

            elif isinstance(metric, Gauge):
                values = metric.get_all()
                if not values:
                    lines.append(f"{metric.name} 0.0")
                else:
                    for labels_tuple, val in sorted(values.items()):
                        label_str = _labels_to_prometheus_str(labels_tuple)
                        lines.append(f"{metric.name}{label_str} {val}")

            elif isinstance(metric, Histogram):
                with metric._lock:
                    keys = list(metric._counts.keys())
                    if not keys:
                        # Print zeroed default entry
                        for b in metric.buckets:
                            lines.append(f'{metric.name}_bucket{{le="{b}"}} 0')
                        lines.append(f'{metric.name}_bucket{{le="+Inf"}} 0')
                        lines.append(f"{metric.name}_sum 0.0")
                        lines.append(f"{metric.name}_count 0")
                    else:
                        for key in sorted(keys):
                            count = metric._counts[key]
                            total_sum = metric._sums[key]
                            b_counts = metric._bucket_counts[key]

                            base_labels = dict(key)
                            for idx, b_bound in enumerate(metric.buckets):
                                b_labels = dict(base_labels)
                                b_labels["le"] = str(b_bound)
                                l_str = _labels_to_prometheus_str(_normalize_labels(b_labels))
                                lines.append(f"{metric.name}_bucket{l_str} {b_counts[idx]}")

                            inf_labels = dict(base_labels)
                            inf_labels["le"] = "+Inf"
                            inf_l_str = _labels_to_prometheus_str(_normalize_labels(inf_labels))
                            lines.append(f"{metric.name}_bucket{inf_l_str} {count}")

                            sum_l_str = _labels_to_prometheus_str(key)
                            lines.append(f"{metric.name}_sum{sum_l_str} {round(total_sum, 6)}")
                            lines.append(f"{metric.name}_count{sum_l_str} {count}")

            lines.append("")  # Blank line between metrics

        return "\n".join(lines).strip() + "\n"

    def get_summary(self) -> Dict[str, Any]:
        """Provides a structured JSON summary of metrics for monitoring dashboards."""
        total_requests = self.http_requests_total.get_total()
        total_errors = self.http_request_errors_total.get_total()
        error_rate_pct = round((total_errors / total_requests * 100), 2) if total_requests > 0 else 0.0

        ai_total = self.ai_requests_total.get_total()
        ai_errors = self.ai_errors_total.get_total()
        ai_success_rate_pct = round(((ai_total - ai_errors) / ai_total * 100), 2) if ai_total > 0 else 100.0

        return {
            "uptime_seconds": round(time.time() - self.start_time, 1),
            "http": {
                "total_requests": int(total_requests),
                "total_errors": int(total_errors),
                "error_rate_pct": error_rate_pct,
                "latency": self.http_request_duration_seconds.get_global_summary(),
            },
            "ai_pipeline": {
                "total_requests": int(ai_total),
                "total_errors": int(ai_errors),
                "success_rate_pct": ai_success_rate_pct,
                "latency": self.ai_request_duration_seconds.get_global_summary(),
            },
            "database": {
                "query_latency": self.database_query_duration_seconds.get_global_summary(),
            },
            "queue": {
                "wait_duration": self.queue_wait_duration_seconds.get_global_summary(),
                "processing_duration": self.grievance_processing_duration_seconds.get_global_summary(),
                "queue_depth": self.queue_depth.get_value(),
                "dlq_depth": self.dlq_depth.get_value(),
            },
        }


# Global singleton instance
metrics_registry = MetricsRegistry()
