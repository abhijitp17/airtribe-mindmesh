"""Pure helpers for workstream F (hardening): data-export serialisation and job retry backoff.

No FastAPI/SQLAlchemy imports, so tests/test_hardening.py runs without them.
"""
from __future__ import annotations

import decimal
import enum
import random
import uuid
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

# Never exported, whatever table they appear in.
SECRET_COLUMNS = frozenset({"password_hash"})
EXPORT_FORMAT_VERSION = 1


def to_jsonable(value: Any) -> Any:
    """Convert a DB value to a JSON-safe value. Datetimes/dates/times become ISO 8601.

    Naive datetimes (SQLite drops tzinfo) are assumed to be UTC, which is how the
    app writes them. Raw bytes are never inlined: they are replaced by a size marker.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return value.hex
    if isinstance(value, enum.Enum):
        return to_jsonable(value.value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"omitted_bytes": len(bytes(value))}
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in value]
    return str(value)


def row_to_dict(row: Mapping[str, Any], exclude: Iterable[str] = ()) -> dict[str, Any]:
    """One DB row (column name -> value) to a JSON-safe dict, minus secret/excluded columns."""
    skip = SECRET_COLUMNS | set(exclude)
    return {k: to_jsonable(v) for k, v in row.items() if k not in skip}


def build_export(user_row: Mapping[str, Any], tables: Mapping[str, Iterable[Mapping[str, Any]]],
                 generated_at: datetime) -> dict[str, Any]:
    """Assemble the export document. `tables` maps table name -> rows owned by the user."""
    out_tables = {name: [row_to_dict(r) for r in rows] for name, rows in sorted(tables.items())}
    files = sorted(
        {str(r["storage_key"]) for r in out_tables.get("documents", []) if r.get("storage_key")}
    )
    return {
        "format_version": EXPORT_FORMAT_VERSION,
        "generated_at": to_jsonable(generated_at),
        "user": row_to_dict(user_row),
        "tables": out_tables,
        "files": {
            "note": "Uploaded file contents are not included. These are the storage keys of your files; "
                    "download each one from the Documents page.",
            "storage_keys": files,
        },
        "counts": {name: len(rows) for name, rows in out_tables.items()},
    }


def export_filename(generated_at: datetime) -> str:
    return f"mindmesh-export-{generated_at.strftime('%Y%m%d-%H%M%S')}.json"


# ---------------------------------------------------------------- job retry backoff

BACKOFF_BASE_SECONDS = 10.0
BACKOFF_CAP_SECONDS = 3600.0


def next_run_after(
    attempts: int,
    now: datetime,
    *,
    base: float = BACKOFF_BASE_SECONDS,
    cap: float = BACKOFF_CAP_SECONDS,
    jitter: float = 0.0,
    rng: Callable[[], float] = random.random,
) -> datetime:
    """When to retry after `attempts` failed tries: base * 2**(attempts-1), capped.

    With `jitter` in [0, 1], the delay is scaled by a factor in [1 - jitter, 1]
    ("equal-ish" jitter that never exceeds the cap). attempts <= 0 is treated as 1.
    """
    n = max(1, int(attempts))
    exp = min(n - 1, 62)  # avoid float overflow for silly inputs
    delay = min(cap, base * (2.0 ** exp))
    if jitter > 0:
        j = min(1.0, max(0.0, jitter))
        delay *= 1.0 - j * rng()
    return now + timedelta(seconds=delay)
