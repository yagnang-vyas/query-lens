"""Helpers shared by the integration tests."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "golden"
FIXTURES = ROOT / "tests" / "fixtures"
POSTGRES_SAMPLE = "examples/postgres-sample.log"
MYSQL_SAMPLE = "examples/mysql-slow-sample.log"


@dataclass(frozen=True)
class Result:
    code: int
    out: str
    err: str


def run_cli(*args: str, stdin: bytes | None = None) -> Result:
    """Run ``python -m slowlens`` from the repository root and capture its output."""
    completed = subprocess.run(
        [sys.executable, "-m", "slowlens", *args],
        input=stdin if stdin is not None else b"",
        capture_output=True,
        cwd=ROOT,
        check=False,
        timeout=120,
    )
    # Normalize newlines so golden files (LF) match on Windows (CRLF from pipes).
    return Result(
        completed.returncode,
        completed.stdout.decode("utf-8").replace("\r\n", "\n"),
        completed.stderr.decode("utf-8").replace("\r\n", "\n"),
    )
