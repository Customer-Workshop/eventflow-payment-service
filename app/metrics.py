"""Simple in-memory metrics collector exposed at GET /metrics.

Designed for consumption by Metricbeat or a custom Logstash input.
No external dependencies required.
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import APIRouter

router = APIRouter(tags=["metrics"])

_lock = threading.Lock()
_start_time = time.monotonic()


@dataclass
class _TimingStats:
    """Accumulator for duration-style metrics."""

    count: int = 0
    total: float = 0.0
    min_val: float = float("inf")
    max_val: float = 0.0
    values: list[float] = field(default_factory=list)

    def record(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.min_val = min(self.min_val, value)
        self.max_val = max(self.max_val, value)
        self.values.append(value)

    def percentile(self, p: float) -> float:
        if not self.values:
            return 0.0
        sorted_vals = sorted(self.values)
        k = (len(sorted_vals) - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_vals[int(k)]
        return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "sum": round(self.total, 6),
            "min": round(self.min_val, 6) if self.count > 0 else 0,
            "max": round(self.max_val, 6),
            "p50": round(self.percentile(0.50), 6),
            "p95": round(self.percentile(0.95), 6),
            "p99": round(self.percentile(0.99), 6),
        }


class MetricsCollector:
    """Thread-safe in-memory metrics store."""

    def __init__(self) -> None:
        self._http_requests: dict[str, int] = defaultdict(int)
        self._http_duration = _TimingStats()
        self._payments_processed: dict[str, int] = defaultdict(int)
        self._payments_by_currency: dict[str, int] = defaultdict(int)
        self._events_consumed: dict[str, int] = defaultdict(int)
        self._event_processing_duration = _TimingStats()

    # --- recording helpers ---

    def record_request(
        self, method: str, path: str, status_code: int, duration_seconds: float
    ) -> None:
        key = f"{method}|{path}|{status_code}"
        with _lock:
            self._http_requests[key] += 1
            self._http_duration.record(duration_seconds)

    def record_payment(self, status: str, currency: str) -> None:
        with _lock:
            self._payments_processed[status] += 1
            self._payments_by_currency[currency] += 1

    def record_event(self, outcome: str, duration_seconds: float) -> None:
        with _lock:
            self._events_consumed[outcome] += 1
            self._event_processing_duration.record(duration_seconds)

    # --- snapshot ---

    def snapshot(self) -> dict:
        with _lock:
            http_req_breakdown: list[dict] = []
            for key, count in self._http_requests.items():
                method, path, status = key.split("|", 2)
                http_req_breakdown.append(
                    {"method": method, "path": path, "status_code": int(status), "count": count}
                )

            return {
                "service_uptime_seconds": round(time.monotonic() - _start_time, 2),
                "http_requests_total": sum(self._http_requests.values()),
                "http_requests_by_endpoint": http_req_breakdown,
                "http_request_duration_seconds": self._http_duration.to_dict(),
                "payments_processed_total": dict(self._payments_processed),
                "payments_by_currency": dict(self._payments_by_currency),
                "events_consumed_total": dict(self._events_consumed),
                "event_processing_duration_seconds": self._event_processing_duration.to_dict(),
            }


# Module-level singleton
metrics_collector = MetricsCollector()


@router.get("/metrics")
async def get_metrics() -> dict:
    """Return current metrics snapshot."""
    return metrics_collector.snapshot()
