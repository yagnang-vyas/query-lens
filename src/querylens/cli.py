"""Command-line interface."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from querylens import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="querylens",
        description="Analyze PostgreSQL and MySQL slow query logs offline.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0
