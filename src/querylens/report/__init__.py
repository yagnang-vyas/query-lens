"""Report rendering. Reporters receive only normalized, aggregated data, never raw SQL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from querylens.models import FingerprintStats, Hint, ParseStats
from querylens.rules import HINTS

OutputFormat = Literal["text", "json", "markdown"]
OUTPUT_FORMATS: tuple[OutputFormat, ...] = ("text", "json", "markdown")


@dataclass(frozen=True, slots=True)
class ReportData:
    """Everything a reporter needs. ``fingerprints`` is the already ranked ``--top`` subset."""

    log_format: str
    files: tuple[str, ...]
    parse_stats: ParseStats
    total_ms: float
    unique_fingerprints: int
    sort: str
    top: int
    fingerprints: tuple[FingerprintStats, ...]

    def hint_legend(self) -> list[Hint]:
        """Hints that appear in the reported fingerprints, ordered by ID."""
        seen = {hint_id for item in self.fingerprints for hint_id in item.hints}
        return [HINTS[hint_id] for hint_id in sorted(seen)]


def one_line(query: str) -> str:
    """Collapse any whitespace (including newlines inside quoted identifiers) to single spaces."""
    return " ".join(query.split())


def render(output: OutputFormat, data: ReportData) -> str:
    """Render ``data`` in the requested format. The result always ends with a newline."""
    # Imported lazily so that importing the package does not load every renderer.
    if output == "json":
        from querylens.report.json_report import render_json

        return render_json(data)
    if output == "markdown":
        from querylens.report.markdown import render_markdown

        return render_markdown(data)
    from querylens.report.text import render_text

    return render_text(data)
