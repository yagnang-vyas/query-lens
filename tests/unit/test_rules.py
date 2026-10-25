import pytest

from querylens.fingerprint import tokenize
from querylens.rules import HINTS, RULES, evaluate, high_rows_examined


def hints(sql: str) -> set[str]:
    return set(evaluate(tokenize(sql)))


POSITIVE = [
    ("QL001", "select * from t where a = 1"),
    ("QL001", "SELECT t.*, u.id FROM t JOIN u ON t.id = u.t_id"),
    ("QL001", "select distinct * from t where a = 1"),
    ("QL001", "select a, * from t where a = 1"),
    ("QL001", "select a from t where id in (select * from u where b = 1)"),
    ("QL002", "update users set active = false"),
    ("QL002", "DELETE FROM sessions"),
    ("QL002", "update t set a = (select max(b) from u where u.id = 1)"),
    ("QL003", "select a from t where name like '%smith' and b = 1"),
    ("QL003", "select a from t where name ilike E'%smith'"),
    ("QL003", "select a from t where name not like '%'"),
    ("QL004", "select a from t where b = 1 order by id limit 10 offset 5000"),
    ("QL004", "select a from t where b = 1 limit 5000, 10"),
    ("QL005", "select a from t where b = 1 order by rand() limit 1"),
    ("QL005", "select a from t where b = 1 order by random()"),
    ("QL005", "select a from t where b = 1 order by x, RAND(42) desc"),
    ("QL006", "select a from t where lower(email) = 'x@example.com'"),
    ("QL006", "select a from t where b = 1 and date(created_at) = '2026-01-01'"),
    ("QL006", "select a from t where x = 1 or coalesce(a, 0) > 5"),
    ("QL006", "select a from t where (upper(name) = 'A')"),
    ("QL006", "select a from t where cast(id as text) in ('1')"),
    ("QL006", "select a from t where extract(year from created_at) = 2026"),
    ("QL006", "select a from t where lower(name)::text like 'a%'"),
    ("QL008", "select a, b from t"),
    ("QL008", "select a from t join u on t.id = u.t_id"),
]

NEGATIVE = [
    ("QL001", "select a, b from t where a = 1"),
    ("QL001", "select count(*) from t where a = 1"),
    ("QL001", "select a * b from t where a = 1"),
    ("QL001", "select a from t where b = 'select * from x'"),
    ("QL001", "select a from t where exists (select * from u where u.id = t.id)"),
    ("QL001", "select 2*3"),
    ("QL001", "select a from t -- select * from x\n where a = 1"),
    ("QL002", "update users set active = false where id = 1"),
    ("QL002", "delete from t where exists (select 1 from u)"),
    ("QL002", "insert into t values (1) on conflict do update set a = 2"),
    ("QL002", "select 'update t set a = 1'"),
    ("QL003", "select a from t where name like 'smith%'"),
    ("QL003", "select a from t where name like 'sm%ith'"),
    ("QL003", "select a from t where note = '% like %x' and b like c"),
    ("QL003", "select a from t where name like $1"),
    ("QL004", "select a from t where b = 1 limit 10 offset 1000"),
    ("QL004", "select a from t where b = 1 limit 10 offset $1"),
    ("QL004", "select a from t where b = 1 limit 10, 5000"),
    ("QL004", "select 'offset 99999' from t where a = 1"),
    ("QL005", "select random() from t where a = 1"),
    ("QL005", "select a from t where b = 1 order by random_col"),
    ("QL005", "select a from t where b = 1 order by id limit random_limit()"),
    ("QL005", "select a from t where b = 1 order by id for update"),
    ("QL006", "select a from t where email = lower('X')"),
    ("QL006", "select a from t where lower('ABC') = name"),
    ("QL006", "select lower(email) from t where id = 1"),
    ("QL006", "select a from t where created_at > now() - interval '1 day'"),
    ("QL006", "select a from t where coalesce(1, 2) = 1"),
    ("QL006", "select a from t where extract(year from now()) = 2026"),
    ("QL006", "select a from t where lower(name)"),
    ("QL008", "select a from t where b = 1"),
    ("QL008", "select a from t limit 10"),
    ("QL008", "select count(*) from t"),
    ("QL008", "select b, max(a) from t group by b"),
    ("QL008", "select now()"),
    ("QL008", "update t set a = 1"),
    ("QL008", "explain select a from t"),
]


@pytest.mark.parametrize(("rule", "sql"), POSITIVE)
def test_rule_triggers(rule: str, sql: str) -> None:
    assert rule in hints(sql)


@pytest.mark.parametrize(("rule", "sql"), NEGATIVE)
def test_rule_does_not_trigger(rule: str, sql: str) -> None:
    assert rule not in hints(sql)


def test_every_rule_has_positive_and_negative_cases() -> None:
    ids = {rule.hint.id for rule in RULES if rule.check is not None}
    assert ids == {r for r, _ in POSITIVE} == {r for r, _ in NEGATIVE}


def test_rule_metadata_is_transparent_about_being_a_heuristic() -> None:
    assert list(HINTS) == [f"QL00{i}" for i in range(1, 9)]
    for hint in HINTS.values():
        assert hint.title
        assert "heuristic" in hint.description.lower()


def test_ql007_threshold() -> None:
    assert high_rows_examined(1000.5)
    assert not high_rows_examined(1000.0)
    assert not high_rows_examined(None)
