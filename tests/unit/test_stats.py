import math

import pytest

from slowlens.models import FingerprintStats, LogEntry, ParseStats
from slowlens.stats import aggregate, nearest_rank, rank


def entry(sql: str, ms: float, sent: int | None = None, examined: int | None = None) -> LogEntry:
    return LogEntry(sql, ms, None, sent, examined, "t.log", 1)


def by_query(items: list[FingerprintStats]) -> dict[str, FingerprintStats]:
    return {item.query: item for item in items}


@pytest.mark.parametrize(
    ("values", "p50", "p95"),
    [
        ([7.0], 7.0, 7.0),
        ([1.0, 2.0], 1.0, 2.0),
        ([float(i) for i in range(1, 11)], 5.0, 10.0),
        ([float(i) for i in range(1, 21)], 10.0, 19.0),
    ],
)
def test_nearest_rank_hand_computed(values: list[float], p50: float, p95: float) -> None:
    assert nearest_rank(values, 50) == p50
    assert nearest_rank(values, 95) == p95


def test_nearest_rank_100th_percentile_is_max() -> None:
    assert nearest_rank([1.0, 5.0, 9.0], 100) == 9.0


def test_group_statistics() -> None:
    stats = ParseStats()
    items = aggregate(
        [entry(f"select * from t where id = {i}", float(i)) for i in range(1, 21)],
        "generic",
        stats,
    )
    assert len(items) == 1
    item = items[0]
    assert item.count == 20
    assert item.total_ms == 210.0
    assert item.mean_ms == 10.5
    assert item.p50_ms == 10.0
    assert item.p95_ms == 19.0
    assert item.max_ms == 20.0
    assert item.share_pct == 100.0
    assert item.query == "select * from t where id = ?"
    assert item.hints == ("QL001",)
    assert item.rows_sent_total is None
    assert item.examined_per_sent is None


def test_share_percentages_sum_to_100() -> None:
    items = aggregate(
        [
            entry("select a from x where id = 1", 10.0),
            entry("select b from y where id = 1", 20.0),
            entry("select c from z where id = 1", 3.3),
            entry("select c from z where id = 2", 0.1),
        ],
        "generic",
        ParseStats(),
    )
    assert math.isclose(sum(i.share_pct for i in items), 100.0)
    assert math.isclose(by_query(items)["select b from y where id = ?"].share_pct, 20 / 33.4 * 100)


def test_zero_total_time_has_zero_share() -> None:
    items = aggregate([entry("select 1", 0.0)], "generic", ParseStats())
    assert items[0].share_pct == 0.0


def test_empty_input() -> None:
    assert aggregate([], "generic", ParseStats()) == []


def test_min_duration_filters_before_aggregation() -> None:
    stats = ParseStats()
    items = aggregate(
        [entry("select 1", 5.0), entry("select 1", 50.0), entry("select 2", 1.0)],
        "generic",
        stats,
        min_duration_ms=5.0,
    )
    assert stats.filtered_out == 1
    assert len(items) == 1
    assert items[0].count == 2
    assert items[0].share_pct == 100.0


def test_rows_totals_and_ratio_hint() -> None:
    items = aggregate(
        [
            entry("select * from t where a = 1", 1.0, 2, 4000),
            entry("select * from t where a = 2", 1.0, 3, 6000),
            entry("select b from u where a = 1", 1.0, 10, 10000),
            entry("select c from v where a = 1", 1.0, 0, 5),
            entry("select d from w where a = 1", 1.0, None, None),
        ],
        "mysql",
        ParseStats(),
    )
    got = by_query(items)
    big = got["select * from t where a = ?"]
    assert (big.rows_sent_total, big.rows_examined_total) == (5, 10000)
    assert big.examined_per_sent == 2000.0
    assert "QL007" in big.hints
    assert got["select b from u where a = ?"].examined_per_sent == 1000.0  # not above threshold
    assert "QL007" not in got["select b from u where a = ?"].hints
    assert got["select c from v where a = ?"].examined_per_sent is None
    assert got["select d from w where a = ?"].rows_sent_total is None


def test_hints_union_across_entries() -> None:
    items = aggregate(
        [
            entry("select a from t where x = 1 offset 5", 1.0),
            entry("select a from t where x = 1 offset 5", 1.0),
        ],
        "generic",
        ParseStats(),
    )
    assert items[0].hints == ()


def test_dialect_changes_double_quote_meaning() -> None:
    pg = aggregate([entry('select "a" from t', 1.0)], "postgres", ParseStats())
    my = aggregate([entry('select "a" from t', 1.0)], "mysql", ParseStats())
    assert pg[0].query == "select a from t"
    assert my[0].query == "select ? from t"


def make(id_: str, **kwargs: float) -> FingerprintStats:
    base = {"total_ms": 1.0, "mean_ms": 1.0, "p95_ms": 1.0, "max_ms": 1.0}
    base.update(kwargs)
    return FingerprintStats(
        id=id_,
        query=id_,
        count=int(kwargs.get("count", 1)),
        total_ms=base["total_ms"],
        mean_ms=base["mean_ms"],
        p50_ms=1.0,
        p95_ms=base["p95_ms"],
        max_ms=base["max_ms"],
        share_pct=0.0,
        rows_sent_total=None,
        rows_examined_total=None,
        examined_per_sent=None,
    )


@pytest.mark.parametrize(
    ("sort", "field"),
    [
        ("total", "total_ms"),
        ("mean", "mean_ms"),
        ("count", "count"),
        ("p95", "p95_ms"),
        ("max", "max_ms"),
    ],
)
def test_rank_sorts_descending_with_id_tiebreak(sort: str, field: str) -> None:
    items = [make("c", **{field: 5}), make("a", **{field: 5}), make("b", **{field: 9})]
    assert [i.id for i in rank(items, sort)] == ["b", "a", "c"]  # type: ignore[arg-type] # sort is one of the literal keys
