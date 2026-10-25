import pytest

from querylens.fingerprint import fingerprint_id, normalize


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT * FROM Users WHERE id = 42", "select * from users where id = ?"),
        ("select 1.5, 2e10, .5, 0x1F, 0b101", "select ?, ?, ?, ?, ?"),
        ("select x'1F', X'ab'", "select ?, ?"),
        (
            "select * from t where a = 'it''s' and b = 'a\\'b'",
            "select * from t where a = ? and b = ?",
        ),
        ("select $$a;b$$, $tag$ -- x $tag$", "select ?, ?"),
        (
            "select * from t where a = $1 and b = ? and c = :name",
            "select * from t where a = ? and b = ? and c = ?",
        ),
        ('select "Mixed Case", `Tick` from "T"', 'select "mixed case", tick from t'),
        ("select 1; ", "select ?"),
        ("select 1;;", "select ?"),
        ("select a -- comment\n from t", "select a from t"),
        ("select /* c */ a /* nested /* x */ y */ from t", "select a from t"),
        ("select 'a -- b', '/* c */', 'x;y'", "select ?, ?, ?"),
        ("select  a\n\tfrom   t", "select a from t"),
        ("select -1, a - 1, a -1, (-2), x=-3", "select ?, a - ?, a - ?, (?), x = ?"),
        ("select a-1", "select a - ?"),
        ("select a::int, b[1], t.c", "select a::int, b[?], t.c"),
        ("select count(*), max (x) from t", "select count(*), max(x) from t"),
        ("select * from t where id in (1, 2, 3)", "select * from t where id in (?+)"),
        ("select * from t where id in (1)", "select * from t where id in (?+)"),
        ("select * from t where id in (select 1)", "select * from t where id in (select ?)"),
        ("select * from t where id in (a, 1)", "select * from t where id in (a, ?)"),
        ("insert into t values (1,'a'), (2,'b'), (3,'c')", "insert into t values (?+)"),
        ("insert into t values (1, null), (2, default)", "insert into t values (?+)"),
        ("insert into t values (now(), 1)", "insert into t values (?+)"),
        ("insert into t values (f(1), 1)", "insert into t values (f(?), ?)"),
        ("insert into t values (1, now()), (2, now())", "insert into t values (?+)"),
        ("insert into t values (1, current_timestamp)", "insert into t values (?+)"),
        ("select * from t where a in (now(), 1)", "select * from t where a in (now(), ?)"),
        ("select * from t where a like '%x'", "select * from t where a like ?"),
        ("select * from t limit 10 offset 5000", "select * from t limit ? offset ?"),
        ("", ""),
        ("-- only a comment", ""),
        ("select 'unterminated", "select ?"),
        ("select /* unterminated", "select"),
    ],
)
def test_normalize(sql: str, expected: str) -> None:
    assert normalize(sql) == expected


def test_postgres_backslash_is_literal_outside_e_strings() -> None:
    sql = r"select 'C:\', a from t where b = 'x'"
    assert normalize(sql, "postgres") == "select ?, a from t where b = ?"
    assert normalize(r"select E'it\'s', a from t", "postgres") == "select ?, a from t"
    assert normalize(r"select 'it\'s', a from t", "mysql") == "select ?, a from t"


def test_mysql_dialect_double_quote_is_string_and_hash_is_comment() -> None:
    assert normalize('select * from t where a = "x" # trailing\n and b = 1', "mysql") == (
        "select * from t where a = ? and b = ?"
    )
    assert normalize("select /* a /* b */ c */ 1", "mysql") == "select c */ ?"


def test_postgres_double_quote_is_identifier() -> None:
    assert normalize('select "Col" from t', "postgres") == "select col from t"


def test_keywords_in_quotes_keep_quotes() -> None:
    assert normalize('select "Select", "a b" from t') == 'select "select", "a b" from t'


def test_literals_are_not_in_output() -> None:
    out = normalize("select * from u where email = 'bob@example.com' and k = 'sk_live_FAKE123'")
    assert "example.com" not in out
    assert "FAKE" not in out


@pytest.mark.parametrize(
    "sql",
    [
        "select * from t where id in (1,2,3) and name = 'x'",
        "insert into t values (1,2),(3,4)",
        "select -1 - -2",
        "select $$x$$ -- c",
        "select a+-1, a=-1, a<>-1",
        "select count (*) from t",
    ],
)
def test_idempotent(sql: str) -> None:
    once = normalize(sql)
    assert normalize(once) == once


def test_same_shape_same_id_different_shape_different_id() -> None:
    a = fingerprint_id(normalize("select * from t where id = 1"))
    b = fingerprint_id(normalize("SELECT *  FROM t WHERE id = 99999"))
    c = fingerprint_id(normalize("select * from t where name = 1"))
    assert a == b
    assert a != c
    assert len(a) == 12
    int(a, 16)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        # Function-call spacing must not split one query shape into two fingerprints.
        ("select count(*) from t", "select count (*) from t"),
        ("insert into t(a, b) values (1, 2)", "insert into t (a, b) values (1, 2)"),
        # Variable-length ARRAY[...] literals, common with "= ANY(ARRAY[...])".
        (
            "select * from t where id = any(array[1, 2, 3])",
            "select * from t where id = any(array[4, 5])",
        ),
        # Row-value IN lists of different lengths.
        (
            "select * from t where (a, b) in ((1, 2), (3, 4))",
            "select * from t where (a, b) in ((5, 6))",
        ),
    ],
)
def test_equivalent_shapes_share_a_fingerprint(a: str, b: str) -> None:
    assert normalize(a, "postgres") == normalize(b, "postgres")


def test_array_and_row_value_lists_collapse() -> None:
    assert normalize("select * from t where id = any(array[1, 2, 3])", "postgres") == (
        "select * from t where id = any (array[?+])"
    )
    assert normalize("select * from t where (a, b) in ((1, 2), (3, 4))") == (
        "select * from t where (a, b) in (?+)"
    )
    # Not literal-only: left alone.
    assert normalize("select array[a, 1] from t") == "select array[a, ?] from t"
    assert normalize("select * from t where (a, b) in ((1, c))") == (
        "select * from t where (a, b) in ((?, c))"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "select * from t where id = any(array[1, 2, 3])",
        "select * from t where (a, b) in ((1, 2), (3, 4))",
        "select max (x), t (a) from t",
    ],
)
def test_new_collapsing_is_idempotent(sql: str) -> None:
    once = normalize(sql, "postgres")
    assert normalize(once, "postgres") == once


def test_insert_column_list_keeps_space_and_calls_do_not() -> None:
    assert normalize("INSERT INTO s.t(a,b) VALUES (1,2)") == "insert into s.t (a, b) values (?+)"
    assert normalize("select lower (a), count (*) from t") == "select lower(a), count(*) from t"
