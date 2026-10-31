"""Open log files (plain, gzip or stdin) as lazy streams of text lines."""

from __future__ import annotations

import gzip
import io
import sys
import zlib
from collections.abc import Iterator
from typing import TextIO, cast

from slowlens.errors import InputError

STDIN = "-"
_GZIP_MAGIC = b"\x1f\x8b"


def display_name(path: str) -> str:
    """Name used for a path in reports and error messages."""
    return "<stdin>" if path == STDIN else path


def open_lines(path: str) -> Iterator[str]:
    """Open ``path`` (``-`` for stdin) and return an iterator of lines without line endings.

    The file is opened immediately, so a missing or unreadable file raises
    :class:`~slowlens.errors.InputError` here rather than on first iteration. Gzip is detected by
    magic bytes, text is decoded as UTF-8 with ``errors="replace"`` and CRLF is normalized.
    """
    is_stdin = path == STDIN
    try:
        binary = _stdin_binary() if is_stdin else open(path, "rb")  # noqa: SIM115 # closed by _iterate
    except OSError as exc:
        raise InputError(f"cannot read '{path}': {exc.strerror or exc}") from exc
    try:
        text: TextIO
        if binary.peek(2)[:2] == _GZIP_MAGIC:
            text = gzip.open(binary, mode="rt", encoding="utf-8", errors="replace")  # noqa: SIM115 # closed by _iterate
        else:
            text = io.TextIOWrapper(binary, encoding="utf-8", errors="replace")
    except OSError as exc:
        binary.close()
        raise InputError(f"cannot read '{path}': {exc.strerror or exc}") from exc
    return _iterate(text, path, is_stdin)


def _stdin_binary() -> io.BufferedReader:
    # sys.stdin.buffer is a BufferedReader on a real process; test doubles may only offer readinto.
    return io.BufferedReader(cast(io.RawIOBase, sys.stdin.buffer))


def _iterate(text: TextIO, path: str, is_stdin: bool) -> Iterator[str]:
    try:
        for line in text:
            yield line.rstrip("\n")
    except EOFError as exc:
        raise InputError(
            f"cannot read '{display_name(path)}': compressed data is truncated"
        ) from exc
    except (OSError, zlib.error) as exc:
        raise InputError(f"cannot read '{display_name(path)}': {exc}") from exc
    finally:
        if is_stdin:
            _release_stdin(text)
        else:
            text.close()


def _release_stdin(text: TextIO) -> None:
    """Drop our wrapper without closing the process's stdin."""
    detach = getattr(text, "detach", None)
    if detach is not None:
        detach()
