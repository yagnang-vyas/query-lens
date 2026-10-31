"""JSON report with a stable, documented schema (``schema_version`` 1)."""

from __future__ import annotations

import json
from typing import Any

from slowlens import __version__
from slowlens.models import FingerprintStats
from slowlens.report import ReportData, one_line

SCHEMA_VERSION = 1


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _fingerprint(item: FingerprintStats) -> dict[str, Any]:
    return {
        "id": item.id,
        "query": one_line(item.query),
        "count": item.count,
        "total_ms": round(item.total_ms, 3),
        "mean_ms": round(item.mean_ms, 3),
        "p50_ms": round(item.p50_ms, 3),
        "p95_ms": round(item.p95_ms, 3),
        "max_ms": round(item.max_ms, 3),
        "share_pct": round(item.share_pct, 2),
        "rows_sent_total": item.rows_sent_total,
        "rows_examined_total": item.rows_examined_total,
        "examined_per_sent": _round(item.examined_per_sent, 2),
        "hints": list(item.hints),
    }


def to_dict(data: ReportData) -> dict[str, Any]:
    stats = data.parse_stats
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "slowlens", "version": __version__},
        "input": {
            "format": data.log_format,
            "files": list(data.files),
            "entries": stats.entries,
            "malformed": stats.malformed,
            "duration_only": stats.duration_only,
            "skipped_phase": stats.skipped_phase,
            "filtered_out": stats.filtered_out,
        },
        "summary": {
            "total_ms": round(data.total_ms, 3),
            "unique_fingerprints": data.unique_fingerprints,
            "sort": data.sort,
            "top": data.top,
        },
        "fingerprints": [_fingerprint(item) for item in data.fingerprints],
        "hints": {
            hint.id: {"title": hint.title, "description": hint.description}
            for hint in data.hint_legend()
        },
    }


def render_json(data: ReportData) -> str:
    return json.dumps(to_dict(data), indent=2) + "\n"
