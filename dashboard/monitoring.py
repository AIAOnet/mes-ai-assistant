"""Dependency-free application metrics and operational alert evaluation."""

from __future__ import annotations

import math
import threading
import time
from collections import Counter, deque
from typing import Any


class MonitoringRegistry:
    def __init__(self, history_size: int = 60) -> None:
        self._lock = threading.Lock()
        self._started_at = time.monotonic()
        self._requests: Counter[tuple[str, str, int]] = Counter()
        self._durations: deque[float] = deque(maxlen=1000)
        self._recent_statuses: deque[int] = deque(maxlen=20)
        self._history: deque[dict[str, Any]] = deque(maxlen=history_size)

    def record_request(self, method: str, path: str, status: int, duration_seconds: float) -> None:
        route = "/static/*" if path.startswith("/static/") else path[:120]
        with self._lock:
            self._requests[(method, route, status)] += 1
            self._durations.append(duration_seconds)
            self._recent_statuses.append(status)
            total = sum(self._requests.values())
            errors = sum(count for (_, _, code), count in self._requests.items() if code >= 500)
            self._history.append({"time": int(time.time()), "requests": total, "errors": errors, "duration_ms": round(duration_seconds * 1000, 2)})

    def snapshot(self, services: dict[str, dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            request_items = list(self._requests.items())
            durations = sorted(self._durations)
            recent_statuses = list(self._recent_statuses)
            history = list(self._history)
        total = sum(count for _, count in request_items)
        errors = sum(count for (_, _, status), count in request_items if status >= 500)
        average_ms = sum(durations) / len(durations) * 1000 if durations else 0
        p95_ms = durations[max(0, math.ceil(len(durations) * .95) - 1)] * 1000 if durations else 0
        alerts = [{"severity": "critical", "source": name, "message": f"{name.replace('_', ' ').title()} is unavailable"} for name, service in services.items() if name in {"database", "transport"} and not service.get("connected")]
        if sum(status >= 500 for status in recent_statuses) >= 3:
            alerts.append({"severity": "warning", "source": "api", "message": "Repeated API failures detected in the last 20 requests"})
        return {"requests_total": total, "errors_total": errors, "error_rate_percent": round(errors / total * 100, 2) if total else 0, "average_duration_ms": round(average_ms, 2), "p95_duration_ms": round(p95_ms, 2), "uptime_seconds": round(time.monotonic() - self._started_at, 1), "alerts": alerts, "history": history}

    def prometheus(self, services: dict[str, dict[str, Any]]) -> str:
        snapshot = self.snapshot(services)
        with self._lock:
            request_items = sorted(self._requests.items())
            duration_sum = sum(self._durations)
            duration_count = len(self._durations)
        lines = ["# HELP mes_service_up Whether a MES dependency is available.", "# TYPE mes_service_up gauge"]
        lines.extend(f'mes_service_up{{service="{name}"}} {1 if service.get("connected") else 0}' for name, service in sorted(services.items()))
        lines.extend(["# HELP mes_http_requests_total HTTP requests handled by the dashboard.", "# TYPE mes_http_requests_total counter"])
        for (method, path, status), count in request_items:
            safe_path = path.replace('\\', '\\\\').replace('"', '\\"')
            lines.append(f'mes_http_requests_total{{method="{method}",path="{safe_path}",status="{status}"}} {count}')
        lines.extend(["# HELP mes_http_request_duration_seconds Total HTTP request duration.", "# TYPE mes_http_request_duration_seconds summary", f"mes_http_request_duration_seconds_sum {duration_sum:.6f}", f"mes_http_request_duration_seconds_count {duration_count}", "# HELP mes_active_alerts Current operational alerts.", "# TYPE mes_active_alerts gauge", f"mes_active_alerts {len(snapshot['alerts'])}", ""])
        return "\n".join(lines)


monitoring = MonitoringRegistry()
