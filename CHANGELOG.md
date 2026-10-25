# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-25

### Added

- Streaming parsers for PostgreSQL `log_min_duration_statement` (stderr format, any
  `log_line_prefix`) and MySQL / MariaDB slow query logs, with format auto-detection.
- Plain, gzip (detected by magic bytes) and stdin inputs; UTF-8 decoding with replacement and CRLF
  normalization.
- Tokenizer-based query normalization and 12-character SHA-1 fingerprints, with `IN (...)` and
  multi-row `VALUES` collapsing.
- Per-fingerprint count, total, mean, nearest-rank p50 and p95, max, share of total time, and MySQL
  rows examined per row sent.
- Heuristic hints `QL001` to `QL008`.
- Text, JSON (schema version 1) and Markdown reports.
- `--top`, `--sort`, `--min-duration`, `--fail-on-hint` and `--fail-over-ms` options and exit codes
  `0`, `1`, `2` and `130`.
- Privacy guarantees: reports contain normalized queries only and `DETAIL:  parameters:` lines are
  dropped.
- Synthetic PostgreSQL and MySQL sample logs, golden-file tests and GitHub Actions CI for Python
  3.10 to 3.13.

[0.1.0]: https://github.com/ChakraCoder/querylens/releases/tag/v0.1.0
