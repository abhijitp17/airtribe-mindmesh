"""Service metrics in Prometheus text format (P2: SLOs and alerts, docs/slo.md). No dependencies.

Labels never carry user data: requests are labelled by the path with ids replaced
("/api/documents/{id}"), so ids don't leak into metrics or explode cardinality; 404s are
labelled "unmatched". Per process: scrape every API process (or sum in Prometheus).

  mindmesh_http_requests_total{method,route,status}
  mindmesh_http_request_duration_seconds_bucket{route,le}  (+ _sum, _count)
  mindmesh_ai_call_duration_seconds_bucket{task,le}         (+ _sum, _count)
  mindmesh_ai_calls_total{task,outcome}                     outcome: ok | error | refused
  mindmesh_jobs_total{kind,outcome}                         outcome: done | failed | retry
"""
from __future__ import annotations

import re
import threading
from collections import defaultdict

HTTP_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
AI_BUCKETS = (0.5, 1.0, 2.0, 4.0, 8.0, 15.0, 30.0, 60.0)

_lock = threading.Lock()
_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
_hists: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = {}  # bucket counts..., sum, count


def _key(name: str, labels: dict[str, str]) -> tuple[str, tuple[tuple[str, str], ...]]:
    return name, tuple(sorted(labels.items()))


def inc(name: str, value: float = 1.0, **labels: str) -> None:
    with _lock:
        _counters[_key(name, labels)] += value


def observe(name: str, seconds: float, buckets: tuple[float, ...], **labels: str) -> None:
    k = _key(name, labels)
    with _lock:
        h = _hists.setdefault(k, [0.0] * (len(buckets) + 2))
        for i, b in enumerate(buckets):
            if seconds <= b:
                h[i] += 1
        h[-2] += seconds
        h[-1] += 1


def reset() -> None:
    with _lock:
        _counters.clear()
        _hists.clear()


def _fmt_labels(labels: tuple[tuple[str, str], ...], extra: tuple[tuple[str, str], ...] = ()) -> str:
    items = list(labels) + list(extra)
    if not items:
        return ""
    esc = lambda v: str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")  # noqa: E731
    return "{" + ",".join(f'{k}="{esc(v)}"' for k, v in items) + "}"


def render() -> str:
    lines: list[str] = []
    with _lock:
        counters = dict(_counters)
        hists = {k: list(v) for k, v in _hists.items()}
    for name in sorted({n for n, _ in counters}):
        lines.append(f"# TYPE {name} counter")
        for (n, labels), v in sorted(counters.items()):
            if n == name:
                lines.append(f"{name}{_fmt_labels(labels)} {v:g}")
    for name in sorted({n for n, _ in hists}):
        buckets = AI_BUCKETS if name.startswith("mindmesh_ai_") else HTTP_BUCKETS
        lines.append(f"# TYPE {name} histogram")
        for (n, labels), h in sorted(hists.items()):
            if n != name:
                continue
            for b, c in zip(buckets, h):
                lines.append(f"{name}_bucket{_fmt_labels(labels, (('le', f'{b:g}'),))} {c:g}")
            lines.append(f"{name}_bucket{_fmt_labels(labels, (('le', '+Inf'),))} {h[-1]:g}")
            lines.append(f"{name}_sum{_fmt_labels(labels)} {h[-2]:.6f}")
            lines.append(f"{name}_count{_fmt_labels(labels)} {h[-1]:g}")
    return "\n".join(lines) + "\n"


_ID = re.compile(r"/(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\d+)(?=/|$)", re.I)


def route_label(path: str, status: int) -> str:
    """Path with ids replaced ("/api/documents/{id}"). Every 404 is "unmatched", so requests for
    random URLs can't create unbounded label values."""
    if status == 404 or not path.startswith("/api/"):
        return "unmatched"
    return _ID.sub("/{id}", path)


def record_request(method: str, route: str, status: int, seconds: float) -> None:
    inc("mindmesh_http_requests_total", method=method, route=route, status=str(status))
    observe("mindmesh_http_request_duration_seconds", seconds, HTTP_BUCKETS, route=route)


def record_ai_call(task: str, seconds: float, outcome: str) -> None:
    inc("mindmesh_ai_calls_total", task=task, outcome=outcome)
    if outcome == "ok":
        observe("mindmesh_ai_call_duration_seconds", seconds, AI_BUCKETS, task=task)


def record_job(kind: str, outcome: str) -> None:
    inc("mindmesh_jobs_total", kind=kind, outcome=outcome)
