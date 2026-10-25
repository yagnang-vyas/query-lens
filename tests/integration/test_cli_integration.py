"""End-to-end tests that run the real CLI in a subprocess.

Golden files live in ``tests/golden``. To regenerate them after an intentional output change::

    UPDATE_GOLDEN=1 pytest tests/integration

and review the resulting diff before committing.
"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

import pytest
from helpers import FIXTURES, GOLDEN, MYSQL_SAMPLE, POSTGRES_SAMPLE, ROOT, run_cli

GOLDEN_CASES = [
    ("postgres-sample.json", POSTGRES_SAMPLE),
    ("mysql-slow-sample.json", MYSQL_SAMPLE),
]


@pytest.mark.parametrize(("golden", "sample"), GOLDEN_CASES)
def test_json_matches_golden(golden: str, sample: str) -> None:
    result = run_cli("--output", "json", "--top", "100", sample)
    assert result.code == 0, result.err
    path = GOLDEN / golden
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.write_text(result.out, encoding="utf-8")
    assert result.out == path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("sample", "fmt"), [(POSTGRES_SAMPLE, "postgres"), (MYSQL_SAMPLE, "mysql")]
)
def test_json_structure(sample: str, fmt: str) -> None:
    report = json.loads(run_cli("--output", "json", sample).out)
    assert report["schema_version"] == 1
    assert report["tool"]["name"] == "querylens"
    assert report["input"]["format"] == fmt
    assert report["input"]["files"] == [sample]
    assert len(report["fingerprints"]) == min(10, report["summary"]["unique_fingerprints"])
    shares = [f["share_pct"] for f in report["fingerprints"]]
    assert shares == sorted(shares, reverse=True)
    for fingerprint in report["fingerprints"]:
        assert set(fingerprint["hints"]) <= set(report["hints"])


def test_text_output_structure() -> None:
    result = run_cli("--top", "5", POSTGRES_SAMPLE)
    assert result.code == 0
    lines = result.out.splitlines()
    assert lines[0].startswith("QueryLens 0.1.0 | format: postgres")
    assert "entries parsed: 73" in lines[1]
    header = next(line for line in lines if line.lstrip().startswith("#") and "Total ms" in line)
    ranks = [line for line in lines if line[:2].strip().isdigit() and line is not header]
    assert len(ranks) == 5
    assert any(line.startswith("Hints (heuristics") for line in lines)
    assert all(len(line) <= 140 for line in lines if line.startswith("    "))
    assert "\x1b[" not in result.out


def test_markdown_output_structure() -> None:
    result = run_cli("--output", "markdown", "--top", "4", MYSQL_SAMPLE)
    assert result.code == 0
    lines = result.out.splitlines()
    assert lines[0] == "# QueryLens report"
    table = [line for line in lines if line.startswith("|")]
    assert len(table) == 2 + 4  # header, separator, rows
    assert all(line.count("|") >= 10 for line in table)
    assert "## Hints" in lines
    assert any(line.startswith("| 1 | `") and "`select" in line for line in lines)


def test_auto_detection_matches_explicit_format() -> None:
    auto = run_cli("--output", "json", MYSQL_SAMPLE)
    explicit = run_cli("--output", "json", "--format", "mysql", MYSQL_SAMPLE)
    assert auto.out == explicit.out


def test_sort_and_top_options() -> None:
    report = json.loads(
        run_cli("--output", "json", "--sort", "count", "--top", "3", POSTGRES_SAMPLE).out
    )
    counts = [f["count"] for f in report["fingerprints"]]
    assert len(counts) == 3
    assert counts == sorted(counts, reverse=True)
    assert report["summary"]["sort"] == "count"


def test_min_duration_filters_entries() -> None:
    report = json.loads(run_cli("--output", "json", "--min-duration", "100", POSTGRES_SAMPLE).out)
    assert report["input"]["filtered_out"] > 0
    assert all(f["p50_ms"] >= 100 for f in report["fingerprints"])


def test_multiple_files_are_combined() -> None:
    single = json.loads(run_cli("--output", "json", POSTGRES_SAMPLE).out)
    double = json.loads(run_cli("--output", "json", POSTGRES_SAMPLE, POSTGRES_SAMPLE).out)
    assert double["input"]["entries"] == 2 * single["input"]["entries"]
    assert double["input"]["files"] == [POSTGRES_SAMPLE, POSTGRES_SAMPLE]
    assert double["summary"]["unique_fingerprints"] == single["summary"]["unique_fingerprints"]


def test_gzip_input(tmp_path: Path) -> None:
    compressed = tmp_path / "pg.log.gz"
    compressed.write_bytes(gzip.compress((ROOT / POSTGRES_SAMPLE).read_bytes()))
    plain = json.loads(run_cli("--output", "json", POSTGRES_SAMPLE).out)
    zipped = json.loads(run_cli("--output", "json", str(compressed)).out)
    assert zipped["fingerprints"] == plain["fingerprints"]


def test_stdin_input_plain_and_gzip() -> None:
    data = (ROOT / MYSQL_SAMPLE).read_bytes()
    plain = json.loads(run_cli("--output", "json", MYSQL_SAMPLE).out)
    for payload in (data, gzip.compress(data)):
        result = run_cli("--output", "json", "-", stdin=payload)
        assert result.code == 0, result.err
        report = json.loads(result.out)
        assert report["input"]["files"] == ["<stdin>"]
        assert report["fingerprints"] == plain["fingerprints"]


# --- exit codes ------------------------------------------------------------------------------


def test_exit_0_on_success() -> None:
    result = run_cli(POSTGRES_SAMPLE)
    assert (result.code, result.err) == (0, "")


def test_exit_1_fail_on_hint() -> None:
    result = run_cli("--fail-on-hint", "QL001,QL003", POSTGRES_SAMPLE)
    assert result.code == 1
    assert result.out.startswith("QueryLens")  # report is still printed
    assert result.err.count("\n") == 1
    assert result.err.startswith("querylens: failing: --fail-on-hint QL001,QL003 matched 2 ")


def test_fail_conditions_cover_all_fingerprints_not_only_top() -> None:
    result = run_cli("--top", "1", "--fail-on-hint", "ql008", POSTGRES_SAMPLE)
    assert result.code == 1
    assert "QL008" not in result.out.split("Hints (")[0]


def test_exit_0_when_hint_absent() -> None:
    assert run_cli("--fail-on-hint", "QL007", POSTGRES_SAMPLE).code == 0


def test_exit_1_fail_over_ms_and_0_when_under() -> None:
    over = run_cli("--fail-over-ms", "1000", POSTGRES_SAMPLE)
    assert over.code == 1
    assert "--fail-over-ms 1000: p95 exceeded by" in over.err
    assert run_cli("--fail-over-ms", "100000", POSTGRES_SAMPLE).code == 0


def test_both_fail_flags_give_a_single_line() -> None:
    result = run_cli("--fail-on-hint", "QL001", "--fail-over-ms", "1", POSTGRES_SAMPLE)
    assert result.code == 1
    assert result.err.count("\n") == 1
    assert "--fail-on-hint" in result.err
    assert "--fail-over-ms" in result.err


@pytest.mark.parametrize(
    "args",
    [
        ["no-such-file.log"],
        ["--bogus", POSTGRES_SAMPLE],
        ["--top", "0", POSTGRES_SAMPLE],
        ["--top", "abc", POSTGRES_SAMPLE],
        ["--sort", "median", POSTGRES_SAMPLE],
        ["--fail-on-hint", "QL999", POSTGRES_SAMPLE],
        ["--fail-on-hint", "", POSTGRES_SAMPLE],
        ["--fail-over-ms", "-5", POSTGRES_SAMPLE],
        ["--min-duration", "nan", POSTGRES_SAMPLE],
        [],
    ],
)
def test_exit_2_usage_and_input_errors(args: list[str]) -> None:
    result = run_cli(*args)
    assert result.code == 2
    assert result.out == ""
    assert "querylens: error:" in result.err
    assert "Traceback" not in result.err


def test_missing_file_message_is_clear() -> None:
    result = run_cli("no-such-file.log")
    assert result.err.strip() == (
        "querylens: error: cannot read 'no-such-file.log': No such file or directory"
    )


def test_exit_2_undetectable_format(tmp_path: Path) -> None:
    path = tmp_path / "other.log"
    path.write_text("just some text\nnothing to see\n")
    result = run_cli(str(path))
    assert result.code == 2
    assert "pass --format" in result.err
    assert "Traceback" not in result.err


def test_exit_2_empty_log(tmp_path: Path) -> None:
    path = tmp_path / "empty.log"
    path.write_bytes(b"")
    assert run_cli(str(path)).code == 2
    result = run_cli("--format", "mysql", str(path))
    assert result.code == 2
    assert "no mysql log entries could be parsed" in result.err


def test_exit_2_when_nothing_parses(tmp_path: Path) -> None:
    path = tmp_path / "bad.log"
    path.write_text("LOG:  duration: oops ms  statement: SELECT 1\n")
    result = run_cli("--format", "postgres", str(path))
    assert result.code == 2
    assert "malformed: 1" in result.err


def test_everything_filtered_is_not_an_error() -> None:
    result = run_cli("--min-duration", "999999", POSTGRES_SAMPLE)
    assert result.code == 0
    assert "No query fingerprints to report." in result.out


def test_version_and_help() -> None:
    assert run_cli("--version").out == "querylens 0.1.0\n"
    help_text = " ".join(run_cli("--help").out.split())
    assert "Checked on all fingerprints, not only the --top subset" in help_text
    assert "--fail-on-hint IDS" in help_text


# --- privacy ---------------------------------------------------------------------------------

SECRETS = [
    "jane.fake",
    "example.com",
    "sk_test_FAKE",
    "bob.fake",
    "secret-name",
    "malformed-line-secret",
    "malformed-entry-secret",
    "FAKE-HASH",
    "7777",
    "9000",
    "password_hash = '",
    "parameters: $1",
    "DETAIL:",
]


@pytest.mark.parametrize("fixture", ["privacy_postgres.log", "privacy_mysql.log"])
@pytest.mark.parametrize("output", ["text", "json", "markdown"])
def test_no_literals_or_parameters_in_any_output(fixture: str, output: str) -> None:
    result = run_cli(
        "--output",
        output,
        "--fail-on-hint",
        "QL003,QL004",
        "--fail-over-ms",
        "1",
        str(FIXTURES / fixture),
    )
    assert result.code == 1  # the fixtures do trigger hints; make sure we exercised that path
    combined = result.out + result.err
    for secret in SECRETS:
        assert secret not in combined, f"{secret!r} leaked into {output} output"
    assert "?" in result.out  # literals were replaced by placeholders


def test_privacy_fixtures_still_produce_hints() -> None:
    report = json.loads(run_cli("--output", "json", str(FIXTURES / "privacy_postgres.log")).out)
    hint_ids = {h for f in report["fingerprints"] for h in f["hints"]}
    assert {"QL003", "QL004", "QL002"} <= hint_ids
    assert report["input"]["malformed"] == 1


def test_errors_do_not_echo_log_content(tmp_path: Path) -> None:
    path = tmp_path / "secret.log"
    path.write_text("jane.fake@example.com sk_test_FAKE_1234\n")
    result = run_cli(str(path))
    assert result.code == 2
    assert "jane.fake" not in result.err
    assert "sk_test_FAKE" not in result.err
