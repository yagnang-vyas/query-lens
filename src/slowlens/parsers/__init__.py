"""Log format detection and parser lookup."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from typing import Literal

from slowlens.errors import InputError
from slowlens.models import LogEntry, ParseStats
from slowlens.parsers import mysql, postgres

LogFormat = Literal["postgres", "mysql"]
Parser = Callable[[Iterable[str], str, ParseStats], Iterator[LogEntry]]

#: How many leading lines of the first input are inspected to detect the format.
DETECT_LINES = 200

_POSTGRES_MARKER = re.compile(r"LOG:\s+duration:")
_MYSQL_MARKER = re.compile(r"^#\s*Query_time:")

_PARSERS: dict[LogFormat, Parser] = {"postgres": postgres.parse, "mysql": mysql.parse}


def detect_format(lines: Iterable[str]) -> LogFormat:
    """Guess the log format from the first :data:`DETECT_LINES` lines.

    Raises :class:`~slowlens.errors.InputError` when neither format is recognised.
    """
    for number, line in enumerate(lines):
        if number >= DETECT_LINES:
            break
        if _MYSQL_MARKER.match(line):
            return "mysql"
        if _POSTGRES_MARKER.search(line):
            return "postgres"
    raise InputError(
        "could not detect the log format in the first "
        f"{DETECT_LINES} lines; pass --format postgres or --format mysql"
    )


def get_parser(log_format: LogFormat) -> Parser:
    """Return the parse function for ``log_format``."""
    return _PARSERS[log_format]
