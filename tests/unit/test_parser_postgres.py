from slowlens.models import LogEntry, ParseStats
from slowlens.parsers.postgres import parse


def run(text: str) -> tuple[list[LogEntry], ParseStats]:
    stats = ParseStats()
    entries = list(parse(text.split("\n"), "pg.log", stats))
    return entries, stats


def test_single_line_statement() -> None:
    entries, stats = run(
        "2026-10-25 06:30:01.123 UTC [101] LOG:  duration: 12.5 ms  statement: SELECT 1;"
    )
    assert len(entries) == 1
    entry = entries[0]
    assert entry.query == "SELECT 1;"
    assert entry.duration_ms == 12.5
    assert entry.timestamp == "2026-10-25 06:30:01.123 UTC"
    assert entry.source == "pg.log"
    assert entry.line_no == 1
    assert entry.rows_sent is None
    assert entry.rows_examined is None
    assert stats.entries == 1


def test_multi_line_statement_with_continuation() -> None:
    entries, _ = run(
        "2026-10-25 06:30:01 UTC [1] LOG:  duration: 3.0 ms  statement: SELECT a,\n"
        "\t       b -- note\n"
        "\tFROM t\n"
        "\tWHERE x = 1"
    )
    assert len(entries) == 1
    assert entries[0].query.split("\n") == ["SELECT a,", "b -- note", "FROM t", "WHERE x = 1"]


def test_execute_unnamed_and_named() -> None:
    entries, _ = run(
        "LOG:  duration: 1.0 ms  execute <unnamed>: SELECT * FROM a WHERE id = $1\n"
        "LOG:  duration: 2.0 ms  execute S_1: SELECT * FROM b"
    )
    assert [e.query for e in entries] == ["SELECT * FROM a WHERE id = $1", "SELECT * FROM b"]


def test_parse_and_bind_are_skipped() -> None:
    entries, stats = run(
        "LOG:  duration: 0.1 ms  parse <unnamed>: SELECT 1\n"
        "LOG:  duration: 0.1 ms  bind S_2: SELECT 1\n"
        "LOG:  duration: 0.3 ms  execute S_2: SELECT 1"
    )
    assert len(entries) == 1
    assert stats.skipped_phase == 2


def test_duration_only() -> None:
    entries, stats = run("LOG:  duration: 5.000 ms")
    assert entries == []
    assert stats.duration_only == 1


def test_statement_label_without_text_is_duration_only() -> None:
    entries, stats = run("LOG:  duration: 5.000 ms  statement:\nLOG:  other")
    assert entries == []
    assert stats.duration_only == 1


def test_detail_and_other_lines_end_entry_and_are_ignored() -> None:
    entries, stats = run(
        "LOG:  duration: 1.0 ms  execute <unnamed>: SELECT 1 WHERE a = $1\n"
        "DETAIL:  parameters: $1 = 'secret@example.com'\n"
        "\t continued detail that must not be appended\n"
        "HINT:  something\n"
        "STATEMENT:  SELECT 1\n"
        "ERROR:  boom"
    )
    assert [e.query for e in entries] == ["SELECT 1 WHERE a = $1"]
    assert "secret" not in repr(entries)
    assert stats.malformed == 0


def test_malformed_duration() -> None:
    entries, stats = run(
        "LOG:  duration: abc ms  statement: SELECT 1\n"
        "LOG:  duration: -4 ms  statement: SELECT 2\n"
        "\tstray continuation"
    )
    assert entries == []
    assert stats.malformed == 2


def test_crlf_lines_are_handled_by_inputs_but_tolerated_here() -> None:
    entries, _ = run("LOG:  duration: 1.0 ms  statement: SELECT 1\r")
    assert entries[0].query == "SELECT 1"


def test_alternative_prefix() -> None:
    entries, _ = run(
        "2026-10-25 06:30:01 UTC [77]: [3-1] user=app,db=shop LOG:  duration: 9.9 ms  "
        "statement: SELECT 2"
    )
    assert entries[0].duration_ms == 9.9
    assert entries[0].timestamp == "2026-10-25 06:30:01 UTC"


def test_prefix_without_timestamp_and_timestamp_variants() -> None:
    entries, _ = run(
        "[101] LOG:  duration: 1.0 ms  statement: SELECT 1\n"
        "2026-10-25 06:30:01 LOG:  duration: 1.0 ms  statement: SELECT 2\n"
        "2026-10-25 06:30:01+02 LOG:  duration: 1.0 ms  statement: SELECT 3\n"
        "2026-10-25T06:30:01.5+0530 LOG:  duration: 1.0 ms  statement: SELECT 4"
    )
    assert [e.timestamp for e in entries] == [
        None,
        "2026-10-25 06:30:01",
        "2026-10-25 06:30:01+02",
        "2026-10-25T06:30:01.5+0530",
    ]


def test_auto_explain_plan_is_skipped() -> None:
    entries, stats = run("LOG:  duration: 5.0 ms  plan:\n\tQuery Text: SELECT 1")
    assert entries == []
    assert stats.skipped_phase == 1


def test_blank_lines_and_leading_continuation_are_ignored() -> None:
    entries, _ = run("\tdangling\n\nLOG:  duration: 1.0 ms  statement: SELECT 1\n\n\t FROM t\n")
    assert [e.query for e in entries] == ["SELECT 1\nFROM t"]


def test_consecutive_entries_keep_line_numbers() -> None:
    entries, _ = run(
        "LOG:  duration: 1.0 ms  statement: SELECT 1\n"
        "LOG:  checkpoint starting\n"
        "LOG:  duration: 2.0 ms  statement: SELECT 2"
    )
    assert [e.line_no for e in entries] == [1, 3]


def test_repr_does_not_contain_query() -> None:
    entries, _ = run("LOG:  duration: 1.0 ms  statement: SELECT 'secret@example.com'")
    assert "secret" not in repr(entries[0])
