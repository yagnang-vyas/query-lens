# QueryLens specification (v0.1.0)

## Problem

Slow query logs contain thousands of near-identical entries. Developers need to know which query
*shapes* consume the most database time, and which shapes have obvious anti-patterns, without
installing heavy tooling or sending logs to a third-party service.

## Users

Backend developers and small engineering teams running PostgreSQL or MySQL/MariaDB who want a quick,
offline answer to "which queries are hurting us?", locally or as a CI gate.

## Scope

QueryLens reads PostgreSQL and MySQL slow query logs offline, normalizes each query into a
fingerprint, aggregates timing statistics per fingerprint, flags heuristic hints, and prints a report
as text, JSON or Markdown. Exit codes make it usable as a CI gate.

## Non-goals for v0.1.0

- Connecting to a database or running `EXPLAIN`.
- PostgreSQL `csvlog` / `jsonlog` formats and `pg_stat_statements` input.
- A full SQL parser (normalization is tokenizer based).
- Any web UI or dashboard.
- Publishing to PyPI.

## Interface

```
querylens [-h] [--version] [--format {auto,postgres,mysql}]
          [--output {text,json,markdown}] [--top N]
          [--sort {total,mean,count,p95,max}] [--min-duration MS]
          [--fail-on-hint IDS] [--fail-over-ms MS]
          FILE [FILE ...]
```

| Exit code | Meaning |
|---|---|
| 0 | Success |
| 1 | A `--fail-on-hint` or `--fail-over-ms` condition triggered |
| 2 | Usage or input error: bad arguments, missing/unreadable file, undetectable format, zero entries parsed |
| 130 | Interrupted (Ctrl-C) |

Fail conditions are evaluated on all fingerprints, not only the `--top` subset.

## Design

```
inputs.py  ──lines──▶  parsers/{postgres,mysql}.py  ──LogEntry──▶  stats.py  ──▶  report/{text,json,markdown}.py
                                  │                                 ▲
                                  └── rules.py (raw-literal flags) ─┘ fingerprint.py (normalize, id)
```

- **inputs.py** opens files or stdin as a lazy line iterator: gzip detected by magic bytes, UTF-8 with
  `errors="replace"`, CRLF normalized. Nothing is read whole into memory.
- **parsers/** turn lines into `LogEntry` objects with a small state machine per engine, counting
  malformed, duration-only and skipped-phase entries in `ParseStats`.
- **fingerprint.py** is a single-pass tokenizer that strips comments, replaces literals and
  placeholders with `?`, lowercases, collapses whitespace and `IN`/`VALUES` lists. The ID is the
  first 12 hex characters of SHA-1 of the normalized text.
- **rules.py** holds hint rules. Rules that need raw literal values (QL003, QL004) are evaluated on
  the raw entry inside the process and stored only as booleans.
- **stats.py** groups entries by fingerprint, keeping durations per group, and computes count,
  total, mean, nearest-rank p50/p95, max, share and MySQL row ratios.
- **report/** renders the aggregated, already-normalized data. Reports never see raw SQL.

## Acceptance criteria

- [ ] PostgreSQL stderr logs from `log_min_duration_statement` parse correctly regardless of
      `log_line_prefix`, including multi-line statements, `execute <name>`, parse/bind skipping,
      duration-only lines, DETAIL lines, malformed durations and CRLF.
- [ ] MySQL/MariaDB slow logs parse correctly, including entries without `# Time:`, multi-line
      statements, `use`/`SET timestamp` skipping, banner lines, extra fields, administrator
      commands, malformed `Query_time` and entries without a statement.
- [ ] Format auto-detection works from the first 200 lines; undetectable input exits 2.
- [ ] Equivalent query shapes with different literals produce the same fingerprint ID; different
      shapes produce different IDs; normalization is idempotent on every fixture query.
- [ ] Percentiles use nearest-rank and match hand-computed values for n = 1, 2, 10, 20.
- [ ] Share percentages sum to ~100; sorting is deterministic with fingerprint-ID tie-break.
- [ ] Each of the eight hint rules has positive and negative tests, including tricky negatives.
- [ ] Text, JSON and Markdown reports are produced; JSON matches golden files byte for byte.
- [ ] Exit codes 0, 1 (each fail flag) and 2 (missing file, bad flag, undetectable format, empty
      log) are covered by integration tests.
- [ ] `.gz` input and stdin input work end to end.
- [ ] Privacy: a fake email, a fake API-key-like string and a `DETAIL: parameters:` line never
      appear in any output format.
- [ ] `make check` passes: ruff, ruff format, mypy strict, pytest with ≥90% branch coverage.
- [ ] `pip install .` into a fresh virtual environment works and `querylens` runs.
- [ ] Zero runtime dependencies.

## Test plan

- **Unit** (`tests/unit/`): fingerprint rules and edge cases, both parsers, format detection,
  inputs (gzip, stdin, missing file, invalid UTF-8), statistics, every hint rule, report renderers.
- **Integration** (`tests/integration/`): run `python -m querylens` in a subprocess against the
  fixtures; compare JSON with `tests/golden/*.json` (regenerate with `UPDATE_GOLDEN=1 pytest`);
  structural assertions on text and Markdown; every exit code; `.gz` and stdin; privacy.
- **CI**: GitHub Actions on Python 3.10–3.13 runs `make install` and `make check`.

## Security and privacy

- Output contains normalized fingerprints only. Literal values are replaced with `?` before any
  rendering; raw SQL lives in memory only, inside `LogEntry`, and is never passed to a reporter.
- `DETAIL:` lines (including `DETAIL:  parameters:`) are dropped by the PostgreSQL parser.
- Error messages name files and line numbers but never echo log content.
- No network access, no database connection, no telemetry.
- Residual risk: identifiers (table and column names) are kept, and so is anything the tokenizer
  does not recognize as a literal, such as a value in a comment-like construct a real SQL parser
  would understand differently. Do not treat reports as anonymized data.

## Limitations

- Normalization is tokenizer based, not a SQL parser; exotic syntax can produce imperfect grouping.
- Hints are heuristics on query text and simple counters; they can produce false positives and
  false negatives, and they do not know about indexes or table sizes.
- PostgreSQL support is limited to stderr-format logs; `csvlog`/`jsonlog` are not supported.
- Statements are attributed by the duration line; with `log_statement` and
  `log_min_duration_statement` both enabled, only the `duration:` lines are counted.
- All durations for a fingerprint are kept in memory to compute exact percentiles; memory grows
  with the number of entries (eight bytes per entry), not with file size.

## Prior art

- `pt-query-digest` (Percona Toolkit), the reference tool for MySQL slow log digests.
- `pgBadger`, a full-featured PostgreSQL log analyzer with HTML reports.

QueryLens differs by having zero dependencies, privacy-safe output by default, stable JSON for
automation, CI exit codes, and both engines in one tool.

## Decisions

Judgment calls made where the brief was ambiguous. Each one takes the more conservative option.

1. **Local development Python.** Development used Python 3.13; CI covers 3.10–3.13 and the code
   targets 3.10 (ruff `target-version = "py310"`, mypy `python_version = "3.10"`).
2. **Version single-sourcing.** `pyproject.toml` reads the version from `src/querylens/__init__.py`
   via `[tool.hatch.version]`, so it is defined once.
3. **Makefile tools.** `make install` uses `$(PYTHON) -m pip`; the other targets call `ruff`,
   `mypy` and `pytest` from the active virtual environment, exactly as in the brief.
