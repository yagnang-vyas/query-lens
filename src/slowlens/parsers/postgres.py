"""Parser for PostgreSQL ``log_min_duration_statement`` logs in the stderr format.

The parser does not depend on ``log_line_prefix``: it looks for the ``LOG:  duration: ...`` message
anywhere in a line and treats everything before it as an opaque prefix (from which a leading
timestamp is extracted when present).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from slowlens.models import LogEntry, ParseStats

_DURATION = re.compile(r"LOG:\s+duration:\s+(?P<ms>\S+)\s+ms\b(?P<rest>.*)")
_STATEMENT = re.compile(
    r"\s+(?P<kind>statement|execute [^:]+|parse [^:]+|bind [^:]+):\s?(?P<sql>.*)", re.DOTALL
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_TIMESTAMP = re.compile(
    r"\s*(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:\s?[+-]\d{2}(?::?\d{2})?| [A-Z]{2,5}(?![\w:]))?)"
)


@dataclass(slots=True)
class _Pending:
    """A statement whose continuation lines may still follow."""

    duration_ms: float
    timestamp: str | None
    line_no: int
    lines: list[str] = field(default_factory=list)


def parse(lines: Iterable[str], source: str, stats: ParseStats) -> Iterator[LogEntry]:
    """Yield one :class:`LogEntry` per timed ``statement:`` / ``execute ...:`` message."""
    pending: _Pending | None = None
    for line_no, line in enumerate(lines, start=1):
        if pending is not None and line[:1] in (" ", "\t"):
            text = line.strip()
            if text:
                pending.lines.append(text)
            continue
        if not line.strip():
            continue
        entry = _finish(pending, source, stats)
        pending = None
        if entry is not None:
            yield entry
        pending = _start(line, line_no, stats)
    entry = _finish(pending, source, stats)
    if entry is not None:
        yield entry


def _start(line: str, line_no: int, stats: ParseStats) -> _Pending | None:
    """Classify a non-continuation line, returning a pending statement if it opens one."""
    match = _DURATION.search(line)
    if match is None:
        return None  # DETAIL:, HINT:, STATEMENT:, unrelated server messages, ...
    if _NUMBER.fullmatch(match["ms"]) is None:
        stats.malformed += 1
        return None
    rest = match["rest"]
    if not rest.strip():
        stats.duration_only += 1
        return None
    statement = _STATEMENT.fullmatch(rest)
    if statement is None:
        stats.skipped_phase += 1  # e.g. auto_explain "plan:" output
        return None
    if not statement["kind"].startswith(("statement", "execute")):
        stats.skipped_phase += 1  # parse/bind durations would double count the execute step
        return None
    pending = _Pending(float(match["ms"]), _timestamp(line[: match.start()]), line_no)
    first = statement["sql"].strip()
    if first:
        pending.lines.append(first)
    return pending


def _timestamp(prefix: str) -> str | None:
    match = _TIMESTAMP.match(prefix)
    return match["ts"] if match else None


def _finish(pending: _Pending | None, source: str, stats: ParseStats) -> LogEntry | None:
    if pending is None:
        return None
    if not pending.lines:
        stats.duration_only += 1
        return None
    stats.entries += 1
    return LogEntry(
        query="\n".join(pending.lines),
        duration_ms=pending.duration_ms,
        timestamp=pending.timestamp,
        rows_sent=None,
        rows_examined=None,
        source=source,
        line_no=pending.line_no,
    )
