"""
In-process metrics for kerno.
Counters and histograms. Written to a JSONL file.
Replace with Prometheus/StatsD by calling set_metrics().
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional


class Metrics:
    """
    Lightweight in-process metrics collector.

    Tracks:
      - Counters:    cells executed, errors, recoveries
      - Histograms:  cell duration, kernel memory
      - Gauges:      pool size, active tasks
    """

    def __init__(self, output_path: str = ".kerno/metrics.jsonl"):
        self._output_path = Path(output_path)
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock     = threading.Lock()
        self._counters: dict[str, float]       = defaultdict(float)
        self._gauges:   dict[str, float]       = {}
        self._histograms: dict[str, list[float]] = defaultdict(list)

    # ── Recording ──────────────────────────────────────────────────────────────

    def counter(
        self,
        name:  str,
        value: float = 1.0,
        tags:  dict  = None,
    ) -> None:
        key = self._key(name, tags)
        with self._lock:
            self._counters[key] += value
        self._write("counter", name, value, tags)

    def gauge(
        self,
        name:  str,
        value: float,
        tags:  dict = None,
    ) -> None:
        key = self._key(name, tags)
        with self._lock:
            self._gauges[key] = value
        self._write("gauge", name, value, tags)

    def histogram(
        self,
        name:  str,
        value: float,
        tags:  dict = None,
    ) -> None:
        key = self._key(name, tags)
        with self._lock:
            self._histograms[key].append(value)
        self._write("histogram", name, value, tags)

    # ── Named kerno metrics ────────────────────────────────────────────────────

    def record_cell(
        self,
        duration_ms:  float,
        had_error:    bool,
        session_id:   str  = "",
        loop_type:    str  = "",
    ) -> None:
        tags = {"session_id": session_id, "loop": loop_type}
        self.counter("kerno.cells.total",          tags=tags)
        self.histogram("kerno.cell.duration_ms", duration_ms, tags=tags)
        if had_error:
            self.counter("kerno.cells.errors",     tags=tags)

    def record_session_complete(
        self,
        status:         str,
        cells:          int,
        duration_s:     float,
        error_count:    int,
        recovery_count: int,
        session_id:     str = "",
    ) -> None:
        tags = {"status": status, "session_id": session_id}
        self.counter("kerno.sessions.total",        tags=tags)
        self.histogram("kerno.session.cells",       cells,      tags=tags)
        self.histogram("kerno.session.duration_s",  duration_s, tags=tags)
        self.histogram("kerno.session.errors",      error_count, tags=tags)
        self.histogram("kerno.session.recoveries",  recovery_count, tags=tags)

    def record_kernel_memory(self, memory_mb: float, kernel_id: str = "") -> None:
        self.gauge(
            "kerno.kernel.memory_mb",
            memory_mb,
            tags={"kernel_id": kernel_id},
        )

    def record_pool_state(self, available: int, active: int) -> None:
        self.gauge("kerno.pool.available", available)
        self.gauge("kerno.pool.active",    active)

    # ── Snapshot ───────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Return current metric values as a dict."""
        with self._lock:
            return {
                "counters":   dict(self._counters),
                "gauges":     dict(self._gauges),
                "histograms": {
                    k: {
                        "count": len(v),
                        "mean":  sum(v) / len(v) if v else 0,
                        "min":   min(v) if v else 0,
                        "max":   max(v) if v else 0,
                        "p95":   sorted(v)[int(0.95 * len(v))] if v else 0,
                    }
                    for k, v in self._histograms.items()
                },
            }

    # ── Internals ─────────────────────────────────────────────────────────────

    def _key(self, name: str, tags: Optional[dict]) -> str:
        if not tags:
            return name
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name}{{{tag_str}}}"

    def _write(self, kind: str, name: str, value: float, tags: Optional[dict]) -> None:
        record = {
            "ts":    time.time(),
            "kind":  kind,
            "name":  name,
            "value": value,
            "tags":  tags or {},
        }
        with self._lock:
            with open(self._output_path, "a") as f:
                f.write(json.dumps(record) + "\n")


_metrics: Metrics = Metrics()


def get_metrics() -> Metrics:
    return _metrics


def set_metrics(m: Metrics) -> None:
    global _metrics
    _metrics = m
