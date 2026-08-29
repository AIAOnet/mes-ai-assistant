"""Pure deterministic MES analytics. No model-derived calculations."""

from __future__ import annotations

from datetime import datetime
import statistics


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def metric_statistics(readings: list[dict], threshold: float | None = None) -> dict:
    samples = [(item, float(item["value"])) for item in readings
               if isinstance(item.get("value"), (int, float))]
    if not samples:
        return {"sample_count": 0, "available": False, "reason": "No numeric readings in period"}
    values = [value for _, value in samples]
    times = [_time(item["time"]) for item, _ in samples]
    elapsed_hours = (times[-1] - times[0]).total_seconds() / 3600 if len(times) > 1 else 0.0
    x = [(time - times[0]).total_seconds() / 3600 for time in times]
    x_mean = statistics.fmean(x)
    y_mean = statistics.fmean(values)
    denominator = sum((item - x_mean) ** 2 for item in x)
    slope = sum((xv - x_mean) * (yv - y_mean) for xv, yv in zip(x, values)) / denominator if denominator else 0.0
    spread = max(values) - min(values)
    tolerance = max(spread * 0.02, 0.01)
    trend = "INCREASING" if slope > tolerance else "DECREASING" if slope < -tolerance else "STABLE"
    result = {
        "available": True, "sample_count": len(values), "start": values[0], "end": values[-1],
        "minimum": min(values), "maximum": max(values), "mean": statistics.fmean(values),
        "median": statistics.median(values), "standard_deviation": statistics.pstdev(values),
        "delta": values[-1] - values[0], "elapsed_hours": elapsed_hours,
        "rate_of_change_per_hour": (values[-1] - values[0]) / elapsed_hours if elapsed_hours else None,
        "regression_slope_per_hour": slope, "trend": trend,
    }
    if threshold is not None:
        crossings = sum(1 for previous, current in zip(values, values[1:])
                        if previous <= threshold < current)
        seconds_above = sum(
            max(0.0, (times[index + 1] - times[index]).total_seconds())
            for index in range(len(values) - 1) if values[index] > threshold
        )
        result.update({"threshold": threshold, "upward_threshold_crossings": crossings,
                       "estimated_seconds_above_threshold": seconds_above})
    return result


def compare_statistics(left: dict, right: dict) -> dict:
    if not left.get("available") or not right.get("available"):
        return {"available": False, "reason": "Both periods require numeric readings"}
    return {"available": True, "mean_delta": left["mean"] - right["mean"],
            "maximum_delta": left["maximum"] - right["maximum"],
            "minimum_delta": left["minimum"] - right["minimum"],
            "end_delta": left["end"] - right["end"]}


def downtime_statistics(readings: list[dict], start: datetime, end: datetime) -> dict:
    timeline = sorted(readings, key=lambda item: item["time"])
    period_seconds = max(0.0, (end - start).total_seconds())
    if not timeline:
        return {"period_seconds": period_seconds, "downtime_seconds": None,
                "downtime_minutes": None, "availability_percent": None, "stop_count": 0,
                "intervals": [], "coverage": "NO_STATUS_DATA"}
    downtime = 0.0
    stopped_at = None
    intervals = []
    for item in timeline:
        time = _time(item["time"])
        status = str(item.get("value", "")).upper()
        if status == "STOPPED" and stopped_at is None:
            stopped_at = max(time, start)
        elif status != "STOPPED" and stopped_at is not None:
            seconds = max(0.0, (min(time, end) - stopped_at).total_seconds())
            downtime += seconds
            intervals.append({"start": stopped_at.isoformat(), "end": min(time, end).isoformat(),
                              "seconds": seconds})
            stopped_at = None
    if stopped_at is not None:
        seconds = max(0.0, (end - stopped_at).total_seconds())
        downtime += seconds
        intervals.append({"start": stopped_at.isoformat(), "end": end.isoformat(), "seconds": seconds})
    return {"period_seconds": period_seconds, "downtime_seconds": downtime,
            "downtime_minutes": downtime / 60, "availability_percent":
            (period_seconds - downtime) / period_seconds * 100 if period_seconds else None,
            "stop_count": len(intervals), "intervals": intervals,
            "coverage": "FROM_FIRST_STATUS_CHANGE" if timeline else "NO_STATUS_CHANGES"}
