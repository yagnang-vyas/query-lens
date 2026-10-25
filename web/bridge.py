"""Glue between the browser demo and the querylens CLI, run inside Pyodide.

The page writes the uploaded log to ``LOG_PATH`` and calls :func:`analyze`, which drives the real
``querylens.cli.main`` once per output format. Nothing here re-implements analysis, so the demo's
numbers are exactly what the command line prints.
"""

from __future__ import annotations

import contextlib
import io
from collections.abc import Mapping
from typing import Any

from querylens.cli import main

LOG_PATH = "/tmp/querylens-input.log"  # path inside Pyodide's in-memory filesystem
OUTPUTS = ("json", "text", "markdown")
MAX_TOP = 500


def _argv(options: Mapping[str, Any], output: str) -> list[str]:
    argv = [
        "--format", str(options.get("format", "auto")),
        "--output", output,
        "--sort", str(options.get("sort", "total")),
        "--top", str(min(int(options.get("top", 10)), MAX_TOP)),
        "--min-duration", str(options.get("minDuration", 0)),
    ]  # fmt: skip
    if options.get("failOnHint"):
        argv += ["--fail-on-hint", str(options["failOnHint"])]
    if str(options.get("failOverMs", "")) != "":
        argv += ["--fail-over-ms", str(options["failOverMs"])]
    argv.append(LOG_PATH)
    return argv


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    """Run the CLI in-process and return ``(exit code, stdout, stderr)``."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as exc:  # argparse reports bad option values this way
            code = exc.code if isinstance(exc.code, int) else 2
    return code, out.getvalue(), err.getvalue().replace(LOG_PATH, "<input>")


def analyze(options: Mapping[str, Any]) -> dict[str, Any]:
    """Analyze the file at ``LOG_PATH``; ``options`` mirror the CLI flags (see ``_argv``)."""
    result: dict[str, Any] = {"code": 0, "stderr": ""}
    for output in OUTPUTS:
        code, stdout, stderr = run_cli(_argv(options, output))
        result[output] = stdout
        result["code"] = max(result["code"], code)
        if stderr and stderr not in result["stderr"]:
            result["stderr"] += stderr
        if code == 2:  # usage or input error: no report to show
            break
    return result
