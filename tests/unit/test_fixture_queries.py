"""Properties that must hold for every query in the sample logs and fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from slowlens.fingerprint import Dialect, normalize
from slowlens.models import ParseStats
from slowlens.parsers import get_parser

ROOT = Path(__file__).resolve().parents[2]
LOGS: list[tuple[Path, Dialect]] = [
    (ROOT / "examples" / "postgres-sample.log", "postgres"),
    (ROOT / "examples" / "mysql-slow-sample.log", "mysql"),
    (ROOT / "tests" / "fixtures" / "privacy_postgres.log", "postgres"),
    (ROOT / "tests" / "fixtures" / "privacy_mysql.log", "mysql"),
]


@pytest.mark.parametrize(("path", "dialect"), LOGS, ids=[p.name for p, _ in LOGS])
def test_normalize_is_idempotent_for_every_logged_query(path: Path, dialect: Dialect) -> None:
    parse = get_parser("postgres" if dialect == "postgres" else "mysql")
    with path.open(encoding="utf-8") as handle:
        entries = list(parse((line.rstrip("\n") for line in handle), path.name, ParseStats()))
    assert entries
    for entry in entries:
        once = normalize(entry.query, dialect)
        assert once
        assert normalize(once, dialect) == once
