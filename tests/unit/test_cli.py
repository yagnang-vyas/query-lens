from __future__ import annotations

import gzip
import io
import json
import sys
from pathlib import Path

import pytest

from querylens import cli

ROOT = Path(__file__).resolve().parents[2]
PG = str(ROOT / "examples" / "postgres-sample.log")
MYSQL = str(ROOT / "examples" / "mysql-slow-sample.log")


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_text_report_for_each_format(capsys: pytest.CaptureFixture[str]) -> None:
    for path, fmt in ((PG, "postgres"), (MYSQL, "mysql")):
        code, out, err = run(capsys, "--top", "3", path)
        assert (code, err) == (0, "")
        assert f"format: {fmt}" in out


def test_json_report_is_valid(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "--output", "json", "--sort", "max", PG)
    assert code == 0
    assert json.loads(out)["summary"]["sort"] == "max"


def test_markdown_report(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "--output", "markdown", MYSQL)
    assert code == 0
    assert out.startswith("# QueryLens report")


def test_fail_on_hint_and_over_ms(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "--fail-on-hint", "ql005", "--fail-over-ms", "10", MYSQL)
    assert code == 1
    assert out
    assert err.startswith("querylens: failing: --fail-on-hint QL005 matched 1 fingerprint(s) (")
    assert "--fail-over-ms 10: p95 exceeded by" in err
    assert "more)" in err  # more than five slow fingerprints are summarized


def test_error_exit_code_has_no_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "does-not-exist.log")
    assert (code, out) == (2, "")
    assert err.startswith("querylens: error: cannot read 'does-not-exist.log'")


@pytest.mark.parametrize(
    "argv",
    [
        ["--top", "0", PG],
        ["--fail-on-hint", "QL000", PG],
        ["--min-duration", "x", PG],
        ["--top", "1"],
    ],
)
def test_usage_errors_exit_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2
    assert "querylens: error:" in capsys.readouterr().err


def test_unknown_hint_error_lists_known_ids(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--fail-on-hint", "QL001,NOPE", PG])
    err = capsys.readouterr().err
    assert "unknown hint ID 'NOPE'" in err
    assert "QL008" in err


def test_stdin_input(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    data = gzip.compress(Path(PG).read_bytes())
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data)))
    code, out, _ = run(capsys, "-")
    assert code == 0
    assert "files: <stdin>" in out


def test_keyboard_interrupt_exits_130_quietly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupted(_: object) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_run", interrupted)
    code, out, err = run(capsys, PG)
    assert (code, out, err) == (130, "", "")


def test_second_file_of_other_format_counts_malformed_not_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = tmp_path / "second.log"
    other.write_text("not a postgres log\n")
    code, out, _ = run(capsys, "--output", "json", PG, str(other))
    assert code == 0
    assert json.loads(out)["input"]["files"] == [PG, str(other)]
