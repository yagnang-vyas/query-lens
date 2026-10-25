"""GitHub-flavoured Markdown report, suitable for pasting into a pull request."""

from __future__ import annotations

import re

from querylens import __version__
from querylens.report import ReportData, one_line

_HEADER = (
    "| # | ID | Query | Count | Total ms | Mean ms | P95 ms | Max ms | Share % | Hints |",
    "|--:|----|-------|------:|---------:|--------:|-------:|-------:|--------:|-------|",
)


def code_span(text: str) -> str:
    """Wrap ``text`` in a Markdown code span that is safe inside a table cell."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    padding = " " if text.startswith("`") or text.endswith("`") else ""
    escaped = text.replace("|", "\\|")
    return f"{fence}{padding}{escaped}{padding}{fence}"


def escape(text: str) -> str:
    """Backslash-escape Markdown punctuation in plain text."""
    return re.sub(r"([\\`*_|])", r"\\\1", text)


def render_markdown(data: ReportData) -> str:
    stats = data.parse_stats
    lines = [
        "# QueryLens report",
        "",
        f"Analyzed {stats.entries} {data.log_format} log entries from "
        f"{', '.join(code_span(name) for name in data.files)} with QueryLens {__version__}: "
        f"{data.unique_fingerprints} unique query fingerprints, {data.total_ms:.3f} ms in total. "
        f"Skipped: {stats.malformed} malformed, {stats.duration_only} duration-only, "
        f"{stats.skipped_phase} parse/bind/admin, {stats.filtered_out} filtered by duration. "
        f"Showing the top {len(data.fingerprints)} by {data.sort}.",
        "",
    ]
    if not data.fingerprints:
        lines.append("No query fingerprints to report.")
        return "\n".join(lines) + "\n"
    lines.extend(_HEADER)
    for rank, item in enumerate(data.fingerprints, start=1):
        hints = ", ".join(item.hints) or "-"
        lines.append(
            f"| {rank} | `{item.id}` | {code_span(one_line(item.query))} | {item.count} | "
            f"{item.total_ms:.3f} | {item.mean_ms:.3f} | {item.p95_ms:.3f} | {item.max_ms:.3f} | "
            f"{item.share_pct:.2f} | {hints} |"
        )
    legend = data.hint_legend()
    if legend:
        lines.extend(["", "## Hints", "", "Hints are heuristics and may be wrong."])
        lines.append("")
        lines.extend(
            f"- `{hint.id}` **{escape(hint.title)}**: {hint.description}" for hint in legend
        )
    return "\n".join(lines) + "\n"
