"""Command-line interface: argument parsing, orchestration and exit codes."""

from __future__ import annotations

import argparse
import contextlib
import math
import os
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from itertools import chain, islice

from querylens import __version__
from querylens.errors import InputError, QueryLensError
from querylens.inputs import display_name, open_lines
from querylens.models import FingerprintStats, LogEntry, ParseStats
from querylens.parsers import DETECT_LINES, LogFormat, detect_format, get_parser
from querylens.report import OUTPUT_FORMATS, ReportData, render
from querylens.rules import HINTS
from querylens.stats import SORT_KEYS, aggregate, rank

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_ERROR = 2
EXIT_INTERRUPTED = 130
EXIT_BROKEN_PIPE = 141  # 128 + SIGPIPE, what `yes | head` reports for the writer

DEFAULT_TOP = 10
_MAX_LISTED_IDS = 5


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer value: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _milliseconds(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number: {text!r}") from None
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("must be a finite number >= 0")
    return value


def _hint_ids(text: str) -> tuple[str, ...]:
    ids = tuple(part.strip().upper() for part in text.split(","))
    unknown = [hint_id for hint_id in ids if hint_id not in HINTS]
    if unknown:
        known = ", ".join(HINTS)
        shown = ", ".join(repr(hint_id) for hint_id in unknown)
        raise argparse.ArgumentTypeError(f"unknown hint ID {shown} (known: {known})")
    return ids


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="querylens",
        description=(
            "Analyze PostgreSQL and MySQL slow query logs offline: group queries by "
            "fingerprint, rank them by time and flag common anti-patterns. Reports contain "
            "normalized queries only, never literal values."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    _add_input_options(parser)
    _add_report_options(parser)
    _add_fail_options(parser)
    parser.add_argument(
        "files", nargs="+", metavar="FILE", help="slow query log file(s), '-' for stdin, .gz ok"
    )
    return parser


def _add_input_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=("auto", "postgres", "mysql"),
        default="auto",
        help=f"log format (default: auto-detect from the first {DETECT_LINES} lines of the "
        "first file)",
    )
    parser.add_argument(
        "--min-duration",
        type=_milliseconds,
        default=0.0,
        metavar="MS",
        help="drop entries faster than MS milliseconds before aggregation",
    )


def _add_report_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output", choices=OUTPUT_FORMATS, default="text", help="report format (default: text)"
    )
    parser.add_argument(
        "--top",
        type=_positive_int,
        default=DEFAULT_TOP,
        metavar="N",
        help=f"number of fingerprints to report, at least 1 (default: {DEFAULT_TOP})",
    )
    parser.add_argument(
        "--sort",
        choices=SORT_KEYS,
        default="total",
        help="ranking key, descending (default: total)",
    )


def _add_fail_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--fail-on-hint",
        type=_hint_ids,
        default=(),
        metavar="IDS",
        help="comma-separated hint IDs (e.g. QL001,QL003); exit 1 if any fingerprint has one. "
        "Checked on all fingerprints, not only the --top subset",
    )
    parser.add_argument(
        "--fail-over-ms",
        type=_milliseconds,
        default=None,
        metavar="MS",
        help="exit 1 if any fingerprint's p95 exceeds MS milliseconds. "
        "Checked on all fingerprints, not only the --top subset",
    )


@dataclass(frozen=True, slots=True)
class _Thresholds:
    hint_ids: tuple[str, ...]
    over_ms: float | None


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Normalized queries may contain non-ASCII identifiers; never crash on a narrow terminal.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    try:
        return _run(args)
    except QueryLensError as exc:
        print(f"querylens: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    except BrokenPipeError:
        # The reader went away (``querylens big.log | head``). Point stdout at /dev/null so the
        # interpreter's final flush cannot raise again, and exit quietly like other Unix tools.
        _silence_stdout()
        return EXIT_BROKEN_PIPE


def _silence_stdout() -> None:
    with contextlib.suppress(OSError, ValueError, AttributeError):
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)


def _run(args: argparse.Namespace) -> int:
    paths: list[str] = args.files
    parse_stats = ParseStats()
    first = open_lines(paths[0])
    log_format: LogFormat
    if args.format == "auto":
        head = list(islice(first, DETECT_LINES))
        log_format = detect_format(head)
        first = chain(head, first)
    else:
        log_format = args.format
    items = aggregate(
        _entries(paths, first, log_format, parse_stats),
        log_format,
        parse_stats,
        min_duration_ms=args.min_duration,
    )
    if parse_stats.entries == 0:
        raise InputError(
            f"no {log_format} log entries could be parsed (malformed: {parse_stats.malformed}, "
            f"duration-only: {parse_stats.duration_only}, skipped: {parse_stats.skipped_phase})"
        )
    ranked = rank(items, args.sort)
    data = ReportData(
        log_format=log_format,
        files=tuple(display_name(path) for path in paths),
        parse_stats=parse_stats,
        total_ms=math.fsum(item.total_ms for item in items),
        unique_fingerprints=len(items),
        sort=args.sort,
        top=args.top,
        fingerprints=tuple(ranked[: args.top]),
    )
    sys.stdout.write(render(args.output, data))
    sys.stdout.flush()
    reason = _failure_reason(ranked, _Thresholds(args.fail_on_hint, args.fail_over_ms))
    if reason:
        print(f"querylens: failing: {reason}", file=sys.stderr)
        return EXIT_FAILED
    return EXIT_OK


def _entries(
    paths: Sequence[str], first: Iterable[str], log_format: LogFormat, stats: ParseStats
) -> Iterator[LogEntry]:
    """Yield entries from every input, opening later files lazily."""
    parse = get_parser(log_format)
    for index, path in enumerate(paths):
        lines = first if index == 0 else open_lines(path)
        yield from parse(lines, display_name(path), stats)


def _failure_reason(items: Sequence[FingerprintStats], limits: _Thresholds) -> str:
    """Describe which fail conditions hold over *all* fingerprints, or return ``""``."""
    reasons: list[str] = []
    if limits.hint_ids:
        hit = [item for item in items if set(item.hints) & set(limits.hint_ids)]
        if hit:
            reasons.append(f"--fail-on-hint {','.join(limits.hint_ids)} matched {_describe(hit)}")
    if limits.over_ms is not None:
        slow = [item for item in items if item.p95_ms > limits.over_ms]
        if slow:
            reasons.append(f"--fail-over-ms {limits.over_ms:g}: p95 exceeded by {_describe(slow)}")
    return "; ".join(reasons)


def _describe(items: Sequence[FingerprintStats]) -> str:
    ids = ", ".join(item.id for item in items[:_MAX_LISTED_IDS])
    more = len(items) - _MAX_LISTED_IDS
    suffix = f" and {more} more" if more > 0 else ""
    return f"{len(items)} fingerprint(s) ({ids}{suffix})"
