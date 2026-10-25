from querylens.models import LogEntry, ParseStats
from querylens.parsers.mysql import parse


def run(text: str) -> tuple[list[LogEntry], ParseStats]:
    stats = ParseStats()
    entries = list(parse(text.split("\n"), "slow.log", stats))
    return entries, stats


STANDARD = """\
# Time: 2026-10-25T06:30:01.123456Z
# User@Host: app[app] @ localhost []  Id:    12
# Query_time: 2.000123  Lock_time: 0.000100 Rows_sent: 10  Rows_examined: 500000
use shop;
SET timestamp=1761373801;
SELECT * FROM orders WHERE customer_id = 7;"""


def test_standard_entry() -> None:
    entries, stats = run(STANDARD)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.query == "SELECT * FROM orders WHERE customer_id = 7;"
    assert entry.duration_ms == 2000.123
    assert entry.rows_sent == 10
    assert entry.rows_examined == 500000
    assert entry.timestamp == "2026-10-25T06:30:01.123456Z"
    assert entry.line_no == 1
    assert stats.entries == 1


def test_entry_without_time_header() -> None:
    entries, _ = run(
        "# User@Host: app[app] @ localhost []\n"
        "# Query_time: 0.5  Lock_time: 0 Rows_sent: 1  Rows_examined: 1\n"
        "SET timestamp=1761373801;\n"
        "SELECT 1;"
    )
    assert entries[0].timestamp == "2025-10-25T06:30:01Z"
    assert entries[0].duration_ms == 500.0


def test_entry_with_only_query_time_header_and_no_timestamp() -> None:
    entries, _ = run("# Query_time: 0.001\nSELECT 1;")
    assert entries[0].timestamp is None
    assert entries[0].rows_sent is None


def test_multi_line_statement_and_comment_lines() -> None:
    entries, _ = run(
        "# Time: 2026-10-25T06:30:01Z\n"
        "# Query_time: 1.0  Lock_time: 0 Rows_sent: 0  Rows_examined: 0\n"
        "SELECT a,\n"
        "  b\n"
        "# trailing hash comment\n"
        "FROM t;\n"
        "# Time: 2026-10-25T06:30:02Z\n"
        "# Query_time: 1.0  Lock_time: 0 Rows_sent: 0  Rows_examined: 0\n"
        "SELECT 2;"
    )
    assert len(entries) == 2
    assert entries[0].query == "SELECT a,\nb\n# trailing hash comment\nFROM t;"
    assert entries[1].query == "SELECT 2;"


def test_use_and_set_timestamp_skipped() -> None:
    entries, _ = run(
        STANDARD + "\n# Time: x\n# Query_time: 1\nuse db;\nSET timestamp=1;\nSELECT 2;"
    )
    assert [e.query for e in entries] == [
        "SELECT * FROM orders WHERE customer_id = 7;",
        "SELECT 2;",
    ]


def test_banner_lines_ignored_even_mid_entry() -> None:
    text = (
        "/usr/sbin/mysqld, Version: 8.0.35 (MySQL Community Server - GPL). started with:\n"
        "Tcp port: 3306  Unix socket: /var/run/mysqld/mysqld.sock\n"
        "Time                 Id Command    Argument\n" + STANDARD + "\n"
        "/usr/sbin/mysqld, Version: 8.0.35 (MySQL Community Server - GPL). started with:\n"
        "Tcp port: 3306  Unix socket: /var/run/mysqld/mysqld.sock\n"
        "Time                 Id Command    Argument\n"
        "# Time: 2026-10-25T06:31:00Z\n# Query_time: 1\nSELECT 2;"
    )
    entries, stats = run(text)
    assert [e.query for e in entries] == [
        "SELECT * FROM orders WHERE customer_id = 7;",
        "SELECT 2;",
    ]
    assert stats.malformed == 0


def test_extra_fields_do_not_break_parsing() -> None:
    entries, _ = run(
        "# Time: 2026-10-25T06:30:01Z\n"
        "# User@Host: app[app] @  [10.0.0.1]  Id: 5\n"
        "# Query_time: 0.25  Lock_time: 0.00 Rows_sent: 3  Rows_examined: 30  Thread_id: 5"
        "  Errno: 0 Bytes_sent: 99\n"
        "# Thread_id: 5  Schema: shop  QC_hit: No\n"
        "# Full_scan: Yes  Rows_affected: 0\n"
        "SELECT 1;"
    )
    assert entries[0].rows_examined == 30
    assert entries[0].query == "SELECT 1;"


def test_administrator_command_is_skipped() -> None:
    entries, stats = run(
        "# Time: 2026-10-25T06:30:01Z\n"
        "# Query_time: 0.1  Lock_time: 0 Rows_sent: 0  Rows_examined: 0\n"
        "# administrator command: Quit;"
    )
    assert entries == []
    assert stats.skipped_phase == 1


def test_malformed_query_time() -> None:
    entries, stats = run(
        "# Time: 2026-10-25T06:30:01Z\n# Query_time: abc  Lock_time: 0\nSELECT 1;\n"
        "# Time: 2026-10-25T06:30:02Z\n# Query_time: nan\nSELECT 2;\n"
        "# Time: 2026-10-25T06:30:03Z\n# Query_time: 1e999\nSELECT 3;"
    )
    assert entries == []
    assert stats.malformed == 3


def test_entry_without_statement_is_malformed() -> None:
    entries, stats = run(
        "# Time: 2026-10-25T06:30:01Z\n"
        "# Query_time: 1.0  Lock_time: 0 Rows_sent: 0  Rows_examined: 0\n"
        "use shop;\n"
        "SET timestamp=1761373801;\n"
        "# Time: 2026-10-25T06:30:02Z\n"
        "# Query_time: 1.0\nSELECT 1;"
    )
    assert len(entries) == 1
    assert stats.malformed == 1


def test_statement_without_query_time_is_malformed() -> None:
    entries, stats = run("# Time: 2026-10-25T06:30:01Z\n# User@Host: a[a] @ h []\nSELECT 1;")
    assert entries == []
    assert stats.malformed == 1


def test_text_before_first_header_is_ignored() -> None:
    entries, stats = run("garbage\nmore garbage\n" + STANDARD)
    assert len(entries) == 1
    assert stats.malformed == 0


def test_set_timestamp_out_of_range_gives_no_timestamp() -> None:
    entries, _ = run("# Query_time: 1\nSET timestamp=99999999999999999999;\nSELECT 1;")
    assert entries[0].timestamp is None


def test_seconds_with_exponent() -> None:
    entries, _ = run("# Query_time: 1e-3\nSELECT 1;")
    assert entries[0].duration_ms == 1.0
