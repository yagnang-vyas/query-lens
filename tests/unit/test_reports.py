from __future__ import annotations

import json

from querylens.models import FingerprintStats, ParseStats
from querylens.report import ReportData, one_line, render
from querylens.report.markdown import code_span, escape
from querylens.report.text import truncate


def item(
    id_: str = "abc123abc123", query: str = "select ?", hints: tuple[str, ...] = ()
) -> FingerprintStats:
    return FingerprintStats(
        id=id_,
        query=query,
        count=3,
        total_ms=10.123456,
        mean_ms=3.374485,
        p50_ms=3.0,
        p95_ms=4.0,
        max_ms=4.0,
        share_pct=99.999,
        rows_sent_total=None,
        rows_examined_total=None,
        examined_per_sent=None,
        hints=hints,
    )


def data(*items: FingerprintStats) -> ReportData:
    return ReportData(
        log_format="postgres",
        files=("a.log", "b|c.log"),
        parse_stats=ParseStats(entries=3, malformed=1),
        total_ms=10.123456,
        unique_fingerprints=len(items),
        sort="total",
        top=10,
        fingerprints=items,
    )


def test_truncate_and_one_line() -> None:
    assert truncate("x" * 120) == "x" * 120
    assert truncate("x" * 121) == "x" * 119 + "…"
    assert len(truncate("y" * 500)) == 120
    assert one_line("select\n  a,\t b") == "select a, b"


def test_code_span_handles_backticks_and_pipes() -> None:
    assert code_span("a | b") == "`a \\| b`"
    assert code_span("a`b") == "``a`b``"
    assert code_span("`a") == "`` `a ``"


def test_escape() -> None:
    assert escape("SELECT *") == "SELECT \\*"


def test_text_report_rounding_and_long_query() -> None:
    out = render("text", data(item(query="select " + "col, " * 60 + "x from t", hints=("QL001",))))
    assert "10.123" in out
    assert "100.00" in out
    assert "…" in out
    assert "QL001" in out
    assert out.endswith("\n")


def test_empty_reports() -> None:
    for fmt in ("text", "markdown"):
        assert "No query fingerprints to report." in render(fmt, data())  # type: ignore[arg-type] # literal
    parsed = json.loads(render("json", data()))
    assert parsed["fingerprints"] == []
    assert parsed["hints"] == {}


def test_json_rounds_at_output_time_and_is_deterministic() -> None:
    first = render("json", data(item(hints=("QL002", "QL001"))))
    assert first == render("json", data(item(hints=("QL002", "QL001"))))
    parsed = json.loads(first)
    fingerprint = parsed["fingerprints"][0]
    assert fingerprint["total_ms"] == 10.123
    assert fingerprint["share_pct"] == 100.0
    assert fingerprint["examined_per_sent"] is None
    assert list(parsed["hints"]) == ["QL001", "QL002"]
    assert list(parsed) == [
        "schema_version",
        "tool",
        "input",
        "summary",
        "fingerprints",
        "hints",
    ]


def test_markdown_escapes_pipes_in_file_names_and_queries() -> None:
    out = render("markdown", data(item(query="select a || b from t", hints=("QL001",))))
    assert "`b\\|c.log`" in out
    assert "`select a \\|\\| b from t`" in out
    assert "- `QL001` **SELECT \\***" in out


def test_multiline_quoted_identifier_stays_on_one_line() -> None:
    out = render("text", data(item(query='select "a\nb" from t')))
    assert 'select "a b" from t' in out
