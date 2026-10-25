"""Plain data containers shared across QueryLens modules."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class LogEntry:
    """One parsed slow-query log entry.

    ``query`` is the raw statement and may contain personal data. It lives in memory only and is
    excluded from ``repr`` so that it cannot leak through tracebacks or test output.
    """

    query: str = field(repr=False)
    duration_ms: float
    timestamp: str | None
    rows_sent: int | None
    rows_examined: int | None
    source: str
    line_no: int


@dataclass(slots=True)
class ParseStats:
    """Counters describing what happened while reading the logs."""

    entries: int = 0
    malformed: int = 0
    duration_only: int = 0
    skipped_phase: int = 0
    filtered_out: int = 0


@dataclass(frozen=True, slots=True)
class Hint:
    """Static description of a heuristic hint."""

    id: str
    title: str
    description: str


@dataclass(frozen=True, slots=True)
class FingerprintStats:
    """Aggregated statistics for one query fingerprint. Values are unrounded."""

    id: str
    query: str
    count: int
    total_ms: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float
    share_pct: float
    rows_sent_total: int | None
    rows_examined_total: int | None
    examined_per_sent: float | None
    hints: tuple[str, ...] = ()
