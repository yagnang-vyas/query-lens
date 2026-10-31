# QueryLens

[![CI](https://github.com/yagnang-vyas/query-lens/actions/workflows/ci.yml/badge.svg)](https://github.com/yagnang-vyas/query-lens/actions/workflows/ci.yml)

QueryLens reads PostgreSQL and MySQL slow query logs offline and tells you which query *shapes* cost the most database time, with transparent, heuristic hints about common anti-patterns.

## Why it exists

A slow query log holds thousands of near-identical entries that differ only in their literal values. What you want to know is which *shapes* of query consume the most time and which have obvious problems. QueryLens answers that from a plain log file: no database connection, no `EXPLAIN`, no paid APM, and no runtime dependencies beyond the Python standard library. Its reports contain normalized queries only, so you can paste them into a pull request or a chat without leaking the data that was in your logs.

## Features

- Parses PostgreSQL (`log_min_duration_statement`, stderr format, any `log_line_prefix`) and MySQL / MariaDB slow query logs, including multi-line statements, and auto-detects which one you gave it.
- Groups equivalent queries with a tokenizer-based fingerprint: literals, placeholders and comments are removed, and `IN (...)` (including row-value lists), multi-row `VALUES` and PostgreSQL `ARRAY[...]` literal lists collapse.
- Reports count, total, mean, p50, p95 and max time, share of total time, and (MySQL) rows examined per row sent.
- Eight heuristic hints (`QL001` to `QL008`) that state their own limitations.
- Text, JSON (stable, versioned schema) and Markdown reports.
- CI gates: `--fail-on-hint` and `--fail-over-ms` with documented exit codes.
- Reads files, `.gz` files (detected by content) and stdin; streams line by line.
- Malformed entries are counted and skipped, never fatal.
- Zero runtime dependencies; Python 3.10 to 3.14.

## Live demo

**Try it in your browser: [query-lens.netlify.app](https://query-lens.netlify.app/).** The [web playground](web/README.md) runs this exact Python package in your browser through Pyodide, so your log is analyzed locally and never uploaded. It offers one-click sample logs, file upload or paste, search, sorting and hint filtering, per-pattern details, and the CLI's own text, Markdown and JSON reports. Demo limits: logs up to 5 MB, plain text only (no `.gz` or stdin), up to 500 patterns shown, and an analysis is stopped after 60 seconds. The CLI remains the primary product.

## Installation

From [PyPI](https://pypi.org/project/querylens/) (after the first upload — see
[RELEASING.md](RELEASING.md)):

```bash
pipx install querylens    # or: pip install querylens
querylens --version
```

From a clone (development or before the package is on PyPI):

```bash
git clone https://github.com/yagnang-vyas/query-lens.git
cd query-lens
pipx install .          # or: python -m venv .venv && . .venv/bin/activate && pip install .
querylens --version
```

Maintainer steps for GitHub Releases and PyPI Trusted Publishing are in
[RELEASING.md](RELEASING.md). The live demo stays on Netlify; see [web/README.md](web/README.md).

## Enabling slow query logs

**PostgreSQL** (`postgresql.conf`; reload the server afterwards). Log any statement slower than 200 ms to the standard error log:

```conf
log_min_duration_statement = 200   # milliseconds; 0 logs everything, -1 disables
logging_collector = on             # if you want the output in a file
```

QueryLens finds the `LOG:  duration: ... ms  statement: ...` message wherever it sits on the line, so the default `log_line_prefix` and custom ones both work. Use the `stderr` log format (not `csvlog` or `jsonlog`).

**MySQL / MariaDB** (`my.cnf`, or `SET GLOBAL` at runtime):

```conf
slow_query_log = 1
slow_query_log_file = /var/log/mysql/mysql-slow.log
long_query_time = 0.5              # seconds
```

## Usage

```bash
# Top 10 shapes by total time; the format is auto-detected
querylens examples/postgres-sample.log

# Top 5 by 95th percentile, as Markdown for a pull request comment
querylens --top 5 --sort p95 --output markdown examples/mysql-slow-sample.log

# Machine-readable output, ignoring anything faster than 50 ms
querylens --output json --min-duration 50 examples/postgres-sample.log

# Several files, compressed files and stdin
querylens postgresql-2026-10-24.log postgresql-2026-10-25.log.gz
zcat mysql-slow.log.gz | querylens --format mysql -
```

### Using it as a CI gate

```bash
# Fail the build if any query shape has SELECT * (QL001) or a leading wildcard LIKE (QL003),
# or if any shape has a p95 above 750 ms.
querylens --fail-on-hint QL001,QL003 --fail-over-ms 750 slow.log
```

The report is printed as usual, followed by a one-line reason on stderr, and the exit code is `1`. Fail conditions are evaluated on **all** fingerprints, not only the `--top` subset.

## Sample output

Produced by running `querylens --top 5 examples/postgres-sample.log` on the synthetic sample log in this repository:

```text
QueryLens 0.1.0 | format: postgres | files: examples/postgres-sample.log
entries parsed: 73 | malformed: 1 | duration-only: 1 | skipped: 34 | filtered: 0
total time: 19513.555 ms | unique fingerprints: 10 | showing top 5 by total

#  ID            Count  Total ms   Mean ms    P95 ms    Max ms  Share %  Hints
1  e7949fc430c3      6  6872.643  1145.440  1449.955  1449.955    35.22  QL004
    select id, title from articles where published = true order by id limit ? offset ?
2  d236be3dd0c4      8  4148.673   518.584   838.875   838.875    21.26  QL003
    select id, name, price from products where name ilike ? and active = true
3  4beddc297df7      2  3103.438  1551.719  1768.626  1768.626    15.90  QL002
    update sessions set expires_at = now(), revoked = true
4  002b0a2998f8      9  1761.588   195.732   265.755   265.755     9.03  QL006
    select id, email from users where lower(email) = ?
5  25060abf2d0e     14  1713.947   122.425   217.071   217.071     8.78  QL001
    select * from orders where customer_id = ? order by created_at desc

Hints (heuristics, may be wrong; see README):
  QL001 SELECT *: Heuristic: the select list contains * or table.*, which reads every column and
      breaks covering indexes. It cannot know whether you really need all columns.
  QL002 Unfiltered write: Heuristic: an UPDATE or DELETE has no top-level WHERE clause and touches
      every row. It is sometimes intentional (maintenance jobs) and statements starting with WITH
      are not inspected.
  QL003 Leading-wildcard LIKE: Heuristic: LIKE/ILIKE with a literal pattern starting with %, which
      usually prevents B-tree index use. Patterns built at runtime (CONCAT, ||, parameters) are not
      detected.
  QL004 Large OFFSET: Heuristic: a literal OFFSET (or MySQL LIMIT offset, count) above 1000; the
      database must read and discard all skipped rows. Offsets passed as parameters are not
      detected.
  QL006 Function on filtered column: Heuristic: a column is wrapped in LOWER, UPPER, DATE, CAST,
      COALESCE or EXTRACT inside a WHERE/AND/OR comparison, which can prevent plain index use. An
      expression index may make it fine.
```

## Hint reference

Hints are heuristics on query text (and, for QL007, on log counters). They know nothing about your schema, indexes, table sizes or query plans, so treat them as prompts to investigate, not verdicts.

| ID | Title | Triggers when | Known limits |
|---|---|---|---|
| QL001 | SELECT * | the select list contains `*` or `t.*` | `count(*)`, `a * b` and `exists (select * ...)` are ignored; may be harmless on narrow tables |
| QL002 | Unfiltered write | `UPDATE` / `DELETE` without a top-level `WHERE` | statements starting with `WITH` are not inspected; may be intentional |
| QL003 | Leading-wildcard LIKE | `LIKE` / `ILIKE` with a literal pattern starting with `%` | patterns built at runtime (`CONCAT`, `\|\|`, parameters) are not seen |
| QL004 | Large OFFSET | a literal `OFFSET` above 1000, or MySQL `LIMIT offset, count` with offset above 1000 | offsets passed as parameters are not seen |
| QL005 | Random ordering | `ORDER BY RAND()` / `RANDOM()` | none known beyond the usual heuristic caveats |
| QL006 | Function on filtered column | `WHERE` / `AND` / `OR` comparing `LOWER`, `UPPER`, `DATE`, `CAST`, `COALESCE` or `EXTRACT` of a column | an expression index makes this fine |
| QL007 | High rows examined | MySQL only: total `Rows_examined` / total `Rows_sent` above 1000 for the fingerprint | ratio comes from log counters; undefined (no hint) when no rows were sent |
| QL008 | Unbounded SELECT | a non-aggregate `SELECT ... FROM` with no `WHERE`, `LIMIT` or `GROUP BY` | fine for small lookup tables; statements starting with `WITH` are not inspected |

A fingerprint carries a hint if any of its entries triggered it.

## JSON output schema

`--output json` prints one JSON document (`schema_version` 1). Millisecond values are rounded to 3 decimals and percentages to 2 at output time; key order is fixed, so output is deterministic.

```json
{
  "schema_version": 1,
  "tool": {"name": "querylens", "version": "0.1.0"},
  "input": {
    "format": "postgres",
    "files": ["examples/postgres-sample.log"],
    "entries": 0, "malformed": 0, "duration_only": 0,
    "skipped_phase": 0, "filtered_out": 0
  },
  "summary": {"total_ms": 0.0, "unique_fingerprints": 0, "sort": "total", "top": 10},
  "fingerprints": [
    {
      "id": "a1b2c3d4e5f6", "query": "select ...",
      "count": 0, "total_ms": 0.0, "mean_ms": 0.0, "p50_ms": 0.0,
      "p95_ms": 0.0, "max_ms": 0.0, "share_pct": 0.0,
      "rows_sent_total": null, "rows_examined_total": null,
      "examined_per_sent": null, "hints": ["QL001"]
    }
  ],
  "hints": {"QL001": {"title": "SELECT *", "description": "..."}}
}
```

- `input.entries` is the number of entries parsed; `filtered_out` of them were dropped by `--min-duration` before aggregation. `skipped_phase` counts PostgreSQL `parse`/`bind` durations, `auto_explain` plan lines and MySQL administrator commands.
- `fingerprints` holds the `--top` subset in ranked order; `summary.unique_fingerprints` and `summary.total_ms` cover all of them.
- `rows_*` and `examined_per_sent` are `null` for PostgreSQL and when a ratio is undefined. `examined_per_sent` is rounded to 2 decimals.
- `hints` is the legend for the hint IDs that appear in `fingerprints`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | A `--fail-on-hint` or `--fail-over-ms` condition triggered (the report is still printed) |
| 2 | Usage or input error: bad arguments, missing or unreadable file, undetectable format, or zero entries parsed |
| 130 | Interrupted with Ctrl-C |
| 141 | The output pipe was closed early (for example `querylens big.log \| head`); QueryLens stops quietly, the same code a shell reports for a process killed by `SIGPIPE` |

Errors are printed as `querylens: error: <message>` with no traceback. Messages name files and counts, never log content.

## How it works

1. **Input.** Files are opened lazily and read line by line. gzip is detected from the first two bytes, text is decoded as UTF-8 with replacement characters for invalid bytes, and CRLF is normalized.
2. **Parsing.** A small state machine per engine builds entries from multi-line statements. PostgreSQL `parse` and `bind` durations are skipped so a prepared statement is not counted three times.
3. **Fingerprinting.** A single-pass tokenizer removes comments, replaces strings (including `''`, backslash escapes and `$tag$` quoting), numbers, hex literals and placeholders (`$1`, `?`, `:name`) with `?`, lowercases keywords and identifiers, collapses whitespace and trailing semicolons, and turns `IN (?, ?, ...)` and multi-row `VALUES` into `(?+)`. The fingerprint ID is the first 12 hex characters of the SHA-1 of the normalized text. Normalizing twice gives the same result.
4. **Statistics.** Durations are grouped per fingerprint. Percentiles use the **nearest-rank** method: for `n` samples sorted ascending, the p-th percentile is the value at rank `ceil(p / 100 * n)` (1-based). For 20 samples, p95 is the 19th value. Share is a fingerprint's total time over the total time of all kept entries. Rankings sort descending by the chosen key and break ties by fingerprint ID.
5. **Hints.** Rules run on the token stream of each raw query and keep only a boolean; the report never sees raw SQL.

## Privacy

Logs may contain personal data and secrets. QueryLens never prints raw query text, literal values, or PostgreSQL `DETAIL:  parameters:` lines (those lines are dropped by the parser). Reports show normalized fingerprints with every literal replaced by `?`. Error messages never echo log content. A test checks a fixture with fake e-mail addresses, API-key-like strings and parameter lines against all three report formats.

Normalization is not anonymization: table, column and other identifiers are kept, and so is anything the tokenizer cannot recognise as a literal. Review a report before sharing it outside your team.

## Limitations

- Normalization is tokenizer based, not a SQL parser; exotic syntax can group imperfectly.
- Hints are heuristics (see the table above). They can be wrong in both directions.
- PostgreSQL support covers the stderr format only: no `csvlog`, `jsonlog` or `pg_stat_statements`.
- Statements are timed by their `duration:` message; `log_statement` lines without a duration are not entries.
- All durations of a fingerprint are held in memory to compute exact percentiles, so memory grows with the number of entries, not with file size.
- Auto-detection looks at the first 200 lines of the first input only; use `--format` for odd files. Mixed-format inputs are not supported.
- No database access, `EXPLAIN` output or index suggestions.

## Prior art

QueryLens stands on the shoulders of [`pt-query-digest`](https://docs.percona.com/percona-toolkit/pt-query-digest.html) from Percona Toolkit (the reference for MySQL slow log digests) and [`pgBadger`](https://github.com/darold/pgbadger) (a full-featured PostgreSQL log analyzer). If you need histograms, per-user breakdowns or HTML dashboards, use them. QueryLens differs by having zero dependencies, privacy-safe output by default, a stable JSON schema for automation, CI exit codes, and both engines in one small tool.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
make install   # editable install with ruff, mypy, pytest, pytest-cov
make check     # ruff, ruff format --check, mypy --strict, pytest with >= 90% branch coverage
make format    # apply ruff formatting and safe fixes
make dist      # build sdist/wheel and run twine check (does not upload)
```

JSON golden files for the sample logs live in `tests/golden/`. After an intentional output change, regenerate them and review the diff:

```bash
UPDATE_GOLDEN=1 pytest tests/integration
```

Test fixtures are synthetic; see `tests/fixtures/README.md`. The design and acceptance criteria are in [SPEC.md](SPEC.md), contribution ground rules in [AGENTS.md](AGENTS.md).

## Roadmap

Ideas for later versions, none of them promised: PostgreSQL `csvlog` / `jsonlog` input, `pg_stat_statements` snapshots, a baseline comparison mode for CI (fail on regressions rather than absolute thresholds), and configurable hint thresholds.

## License

[MIT](LICENSE) © 2026 Yagnang Vyas
