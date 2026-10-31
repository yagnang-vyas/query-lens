"""Plain-text report: no colour codes, no third-party libraries."""

from __future__ import annotations

import textwrap

from slowlens import __version__
from slowlens.report import ReportData, one_line

QUERY_WIDTH = 120
_COLUMNS = ("#", "ID", "Count", "Total ms", "Mean ms", "P95 ms", "Max ms", "Share %", "Hints")


def truncate(query: str, width: int = QUERY_WIDTH) -> str:
    """Shorten ``query`` to at most ``width`` characters, ending with an ellipsis if cut."""
    return query if len(query) <= width else query[: width - 1] + "…"


def render_text(data: ReportData) -> str:
    lines = _header(data)
    if not data.fingerprints:
        lines.append("No query fingerprints to report.")
    else:
        lines.extend(_table(data))
        lines.extend(_legend(data))
    return "\n".join(lines) + "\n"


def _header(data: ReportData) -> list[str]:
    stats = data.parse_stats
    return [
        f"QueryLens {__version__} | format: {data.log_format} | files: {', '.join(data.files)}",
        f"entries parsed: {stats.entries} | malformed: {stats.malformed} | "
        f"duration-only: {stats.duration_only} | skipped: {stats.skipped_phase} | "
        f"filtered: {stats.filtered_out}",
        f"total time: {data.total_ms:.3f} ms | unique fingerprints: {data.unique_fingerprints} | "
        f"showing top {len(data.fingerprints)} by {data.sort}",
        "",
    ]


def _table(data: ReportData) -> list[str]:
    rows = [
        (
            str(rank),
            item.id,
            str(item.count),
            f"{item.total_ms:.3f}",
            f"{item.mean_ms:.3f}",
            f"{item.p95_ms:.3f}",
            f"{item.max_ms:.3f}",
            f"{item.share_pct:.2f}",
            ",".join(item.hints) or "-",
        )
        for rank, item in enumerate(data.fingerprints, start=1)
    ]
    widths = [max(len(_COLUMNS[i]), *(len(row[i]) for row in rows)) for i in range(len(_COLUMNS))]

    def format_row(row: tuple[str, ...]) -> str:
        cells = [
            cell.ljust(widths[i]) if i in (1, 8) else cell.rjust(widths[i])
            for i, cell in enumerate(row)
        ]
        return "  ".join(cells).rstrip()

    lines = [format_row(_COLUMNS)]
    for row, item in zip(rows, data.fingerprints, strict=True):
        lines.append(format_row(row))
        lines.append("    " + truncate(one_line(item.query)))
    return lines


def _legend(data: ReportData) -> list[str]:
    legend = data.hint_legend()
    if not legend:
        return []
    lines = ["", "Hints (heuristics, may be wrong; see README):"]
    for hint in legend:
        lines.extend(
            textwrap.wrap(
                f"{hint.id} {hint.title}: {hint.description}",
                width=100,
                initial_indent="  ",
                subsequent_indent="      ",
            )
        )
    return lines
