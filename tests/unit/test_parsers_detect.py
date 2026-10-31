import pytest

from slowlens.errors import InputError
from slowlens.parsers import DETECT_LINES, detect_format, get_parser, mysql, postgres


def test_detect_postgres() -> None:
    lines = ["noise", "2026-10-25 06:30:01 UTC [1] LOG:  duration: 1.0 ms  statement: SELECT 1"]
    assert detect_format(lines) == "postgres"


def test_detect_mysql() -> None:
    assert detect_format(["# Time: x", "# Query_time: 1.0  Lock_time: 0"]) == "mysql"


def test_detect_fails_for_unknown_format() -> None:
    with pytest.raises(InputError, match="--format"):
        detect_format(["hello", "world"])


def test_detect_only_inspects_first_lines() -> None:
    lines = ["x"] * DETECT_LINES + ["# Query_time: 1.0"]
    with pytest.raises(InputError):
        detect_format(lines)


def test_get_parser() -> None:
    assert get_parser("postgres") is postgres.parse
    assert get_parser("mysql") is mysql.parse
