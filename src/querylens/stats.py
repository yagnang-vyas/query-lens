"""Aggregate log entries into per-fingerprint statistics."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from querylens.fingerprint import Dialect, fingerprint_id, normalize_tokens, tokenize
from querylens.models import FingerprintStats, LogEntry, ParseStats
from querylens.rules import evaluate, high_rows_examined

SortKey = Literal["total", "mean", "count", "p95", "max"]
SORT_KEYS: tuple[SortKey, ...] = ("total", "mean", "count", "p95", "max")


@dataclass(slots=True)
class _Group:
    query: str
    durations: list[float] = field(default_factory=list)
    hints: set[str] = field(default_factory=set)
    rows_sent: int | None = None
    rows_examined: int | None = None


def nearest_rank(sorted_values: list[float], percentile: int) -> float:
    """Nearest-rank percentile: ``sorted[ceil(p / 100 * n) - 1]``.

    ``percentile`` is an integer in 1..100 so the rank is computed exactly, without floating
    point rounding. ``sorted_values`` must be sorted ascending and non-empty.
    """
    rank = (percentile * len(sorted_values) + 99) // 100
    return sorted_values[max(rank, 1) - 1]


def aggregate(
    entries: Iterable[LogEntry],
    dialect: Dialect,
    parse_stats: ParseStats,
    *,
    min_duration_ms: float = 0.0,
) -> list[FingerprintStats]:
    """Group ``entries`` by fingerprint and compute statistics (unsorted).

    Entries shorter than ``min_duration_ms`` are dropped before aggregation and counted in
    ``parse_stats.filtered_out``. Raw query text is discarded as soon as it has been normalized.
    """
    groups: dict[str, _Group] = {}
    for entry in entries:
        if entry.duration_ms < min_duration_ms:
            parse_stats.filtered_out += 1
            continue
        tokens = tokenize(entry.query, dialect)
        normalized = normalize_tokens(tokens)
        key = fingerprint_id(normalized)
        group = groups.get(key)
        if group is None:
            group = groups[key] = _Group(normalized)
        group.durations.append(entry.duration_ms)
        group.hints |= evaluate(tokens)
        group.rows_sent = _add(group.rows_sent, entry.rows_sent)
        group.rows_examined = _add(group.rows_examined, entry.rows_examined)
    return _summarize(groups)


def _add(total: int | None, value: int | None) -> int | None:
    if value is None:
        return total
    return value if total is None else total + value


def _summarize(groups: dict[str, _Group]) -> list[FingerprintStats]:
    totals = {key: math.fsum(group.durations) for key, group in groups.items()}
    overall = math.fsum(totals.values())
    result: list[FingerprintStats] = []
    for key, group in groups.items():
        ordered = sorted(group.durations)
        count = len(ordered)
        ratio = _ratio(group.rows_examined, group.rows_sent)
        hints = set(group.hints)
        if high_rows_examined(ratio):
            hints.add("QL007")
        result.append(
            FingerprintStats(
                id=key,
                query=group.query,
                count=count,
                total_ms=totals[key],
                mean_ms=totals[key] / count,
                p50_ms=nearest_rank(ordered, 50),
                p95_ms=nearest_rank(ordered, 95),
                max_ms=ordered[-1],
                share_pct=totals[key] / overall * 100 if overall > 0 else 0.0,
                rows_sent_total=group.rows_sent,
                rows_examined_total=group.rows_examined,
                examined_per_sent=ratio,
                hints=tuple(sorted(hints)),
            )
        )
    return result


def _ratio(examined: int | None, sent: int | None) -> float | None:
    if examined is None or not sent:
        return None
    return examined / sent


def rank(items: Iterable[FingerprintStats], sort: SortKey = "total") -> list[FingerprintStats]:
    """Sort descending by ``sort``; ties are broken by fingerprint ID ascending."""

    def value(item: FingerprintStats) -> float:
        if sort == "total":
            return item.total_ms
        if sort == "mean":
            return item.mean_ms
        if sort == "count":
            return float(item.count)
        if sort == "p95":
            return item.p95_ms
        return item.max_ms

    return sorted(items, key=lambda item: (-value(item), item.id))
