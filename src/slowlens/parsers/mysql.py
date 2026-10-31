"""Parser for the MySQL / MariaDB slow query log."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from slowlens.models import LogEntry, ParseStats

_TIME = re.compile(r"#\s*Time:\s*(?P<ts>.*\S)")
_USER_HOST = re.compile(r"#\s*User@Host:")
_QUERY_TIME = re.compile(r"#\s*Query_time:\s*(?P<qt>\S+)")
_ROWS_SENT = re.compile(r"\bRows_sent:\s*(\d+)")
_ROWS_EXAMINED = re.compile(r"\bRows_examined:\s*(\d+)")
_ADMIN = re.compile(r"#\s*administrator command:")
_USE = re.compile(r"use\s+\S+\s*;\s*$", re.IGNORECASE)
_SET_TIMESTAMP = re.compile(r"SET\s+timestamp\s*=\s*(\d+)\s*;?\s*$", re.IGNORECASE)
_BANNER = re.compile(
    r"(.*\bVersion:.*started with:?)|(Tcp port:.*)|(Time\s+Id\s+Command\s+Argument.*)"
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")


@dataclass(slots=True)
class _Entry:
    line_no: int
    timestamp: str | None = None
    saw_query_time: bool = False
    query_time_ms: float | None = None
    rows_sent: int | None = None
    rows_examined: int | None = None
    epoch: str | None = None
    admin: bool = False
    lines: list[str] = field(default_factory=list)


def parse(lines: Iterable[str], source: str, stats: ParseStats) -> Iterator[LogEntry]:
    """Yield one :class:`LogEntry` per slow-log entry that has a statement and a valid time."""
    current: _Entry | None = None
    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        if _BANNER.fullmatch(line):
            entry = _finish(current, source, stats)
            current = None
            if entry is not None:
                yield entry
            continue
        starts_new = _starts_new_entry(line, current)
        if starts_new:
            entry = _finish(current, source, stats)
            current = None
            if entry is not None:
                yield entry
            current = _Entry(line_no)
        if current is None:
            continue  # text before the first header
        _consume(line, current)
    entry = _finish(current, source, stats)
    if entry is not None:
        yield entry


def _starts_new_entry(line: str, current: _Entry | None) -> bool:
    is_time = _TIME.match(line) is not None
    is_user = _USER_HOST.match(line) is not None
    is_query_time = _QUERY_TIME.match(line) is not None
    if not (is_time or is_user or is_query_time):
        return False
    if current is None or current.lines:
        return True
    if is_query_time:
        return current.saw_query_time
    # A "# Time:" or "# User@Host:" header opens a new entry once query_time was seen; before
    # that, the two headers belong to the same entry. A repeated "# Time:" without any
    # Query_time in between also starts a new (header-only) entry.
    return current.saw_query_time or (is_time and current.timestamp is not None)


def _consume(line: str, entry: _Entry) -> None:
    if entry.lines:
        entry.lines.append(line)  # inside the statement, "# ..." lines are SQL comments
        return
    if time := _TIME.match(line):
        entry.timestamp = time["ts"]
    elif query_time := _QUERY_TIME.match(line):
        entry.saw_query_time = True
        entry.query_time_ms = _seconds_to_ms(query_time["qt"])
        sent = _ROWS_SENT.search(line)
        examined = _ROWS_EXAMINED.search(line)
        entry.rows_sent = int(sent[1]) if sent else None
        entry.rows_examined = int(examined[1]) if examined else None
    elif _ADMIN.match(line):
        entry.admin = True
    elif line.startswith("#") or _USE.match(line):
        return  # User@Host, Thread_id, QC_hit, ... (log_slow_extra / MariaDB) and "use db;"
    elif stamp := _SET_TIMESTAMP.match(line):
        entry.epoch = stamp[1]
    else:
        entry.lines.append(line)


def _seconds_to_ms(text: str) -> float | None:
    if _NUMBER.fullmatch(text) is None:
        return None
    # Decimal keeps "2.000123 s" at exactly 2000.123 ms instead of 2000.1229999999998.
    value = float(Decimal(text) * 1000)
    return value if math.isfinite(value) else None


def _epoch_to_iso(epoch: str) -> str | None:
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError, OSError):
        return None


def _finish(entry: _Entry | None, source: str, stats: ParseStats) -> LogEntry | None:
    if entry is None:
        return None
    if entry.admin:
        stats.skipped_phase += 1
        return None
    if entry.query_time_ms is None or not entry.lines:
        stats.malformed += 1
        return None
    stats.entries += 1
    timestamp = entry.timestamp
    if timestamp is None and entry.epoch is not None:
        timestamp = _epoch_to_iso(entry.epoch)
    return LogEntry(
        query="\n".join(entry.lines),
        duration_ms=entry.query_time_ms,
        timestamp=timestamp,
        rows_sent=entry.rows_sent,
        rows_examined=entry.rows_examined,
        source=source,
        line_no=entry.line_no,
    )
