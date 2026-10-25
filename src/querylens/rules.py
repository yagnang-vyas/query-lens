"""Heuristic optimization hints.

Every rule is a pure function over the *tokens* of one raw query (see
:func:`querylens.fingerprint.tokenize`). Token text is already normalized (lowercase, literals
replaced by ``?``); the raw literal is available as ``Token.value`` and is used only by the two
rules that must look at a literal's value (QL003, QL004). A rule returns a boolean, so raw text
never leaves this module.

All hints are heuristics. They look at query text, not at schemas, indexes, table sizes or query
plans, so they can be wrong in both directions.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from querylens.fingerprint import IDENT, LITERAL, OP, PUNCT, WORD, Token
from querylens.models import Hint

#: ``Rows_examined / Rows_sent`` above which QL007 fires.
EXAMINED_PER_SENT_THRESHOLD = 1000
#: ``OFFSET`` values above which QL004 fires.
OFFSET_THRESHOLD = 1000

TokenCheck = Callable[[Sequence[Token]], bool]


@dataclass(frozen=True, slots=True)
class Rule:
    """A hint plus, for query-text rules, the function that detects it."""

    hint: Hint
    check: TokenCheck | None = None


def _is(token: Token, kind: str, text: str) -> bool:
    return token.kind == kind and token.text == text


def _word(token: Token, *words: str) -> bool:
    return token.kind == WORD and token.text in words


def _skip_group(tokens: Sequence[Token], open_index: int) -> int:
    """Return the index just after the parenthesis group that opens at ``open_index``."""
    depth = 0
    for i in range(open_index, len(tokens)):
        if _is(tokens[i], PUNCT, "("):
            depth += 1
        elif _is(tokens[i], PUNCT, ")"):
            depth -= 1
            if depth == 0:
                return i + 1
    return len(tokens)


def _top_level(tokens: Sequence[Token], start: int = 0) -> list[tuple[int, Token]]:
    """Tokens from ``start`` that are not inside any parentheses, with their indexes."""
    out: list[tuple[int, Token]] = []
    depth = 0
    for i in range(start, len(tokens)):
        token = tokens[i]
        if _is(token, PUNCT, "("):
            depth += 1
        elif _is(token, PUNCT, ")"):
            depth -= 1
            if depth < 0:
                break
        elif depth == 0:
            out.append((i, token))
    return out


# --- QL001 -----------------------------------------------------------------------------------


def select_star(tokens: Sequence[Token]) -> bool:
    for i, token in enumerate(tokens):
        if not _word(token, "select") or _inside_exists(tokens, i):
            continue
        previous_item_start = True
        for _, item in _top_level(tokens, i + 1):
            if _word(item, "from") or _is(item, PUNCT, ";"):
                break
            if _is(item, OP, "*") and previous_item_start:
                return True
            previous_item_start = (
                _word(item, "distinct", "all") or _is(item, PUNCT, ",") or _is(item, PUNCT, ".")
            )
    return False


def _inside_exists(tokens: Sequence[Token], select_index: int) -> bool:
    """True for ``exists (select * ...)``, where the select list is irrelevant."""
    return (
        select_index >= 2
        and _is(tokens[select_index - 1], PUNCT, "(")
        and _word(tokens[select_index - 2], "exists")
    )


# --- QL002 -----------------------------------------------------------------------------------


def unfiltered_write(tokens: Sequence[Token]) -> bool:
    if not tokens or not _word(tokens[0], "update", "delete"):
        return False
    return not any(_word(token, "where") for _, token in _top_level(tokens))


# --- QL003 -----------------------------------------------------------------------------------


def leading_wildcard_like(tokens: Sequence[Token]) -> bool:
    for i, token in enumerate(tokens[:-1]):
        if not _word(token, "like", "ilike"):
            continue
        pattern = tokens[i + 1]
        if pattern.kind == LITERAL and _literal_starts_with_wildcard(pattern.value or ""):
            return True
    return False


#: Opening of a string literal: an optional prefix (E, N, B, X), then ', " (MySQL) or $tag$.
_LITERAL_OPENING = re.compile(r"[A-Za-z]*(?:'|\"|\$(?:[^\W\d]\w*)?\$)")


def _literal_starts_with_wildcard(raw: str) -> bool:
    opening = _LITERAL_OPENING.match(raw)
    return opening is not None and raw[opening.end() : opening.end() + 1] == "%"


# --- QL004 -----------------------------------------------------------------------------------


def large_offset(tokens: Sequence[Token]) -> bool:
    for i, token in enumerate(tokens[:-1]):
        if _word(token, "offset") and _exceeds_offset(tokens[i + 1]):
            return True
        # MySQL "LIMIT <offset>, <count>"
        if (
            _word(token, "limit")
            and i + 3 < len(tokens)
            and _is(tokens[i + 2], PUNCT, ",")
            and _exceeds_offset(tokens[i + 1])
        ):
            return True
    return False


def _exceeds_offset(token: Token) -> bool:
    raw = token.value or ""
    return token.kind == LITERAL and raw.isdigit() and int(raw) > OFFSET_THRESHOLD


# --- QL005 -----------------------------------------------------------------------------------

_ORDER_BY_END = frozenset({"limit", "offset", "fetch", "for", "union", "intersect", "except"})


def random_ordering(tokens: Sequence[Token]) -> bool:
    for i, token in enumerate(tokens[:-1]):
        if not (_word(token, "order") and _word(tokens[i + 1], "by")):
            continue
        depth = 0
        for j in range(i + 2, len(tokens) - 1):
            current = tokens[j]
            if _is(current, PUNCT, "("):
                depth += 1
            elif _is(current, PUNCT, ")"):
                depth -= 1
                if depth < 0:
                    break
            elif depth == 0 and (_word(current, *_ORDER_BY_END) or _is(current, PUNCT, ";")):
                break
            if _word(current, "rand", "random") and _is(tokens[j + 1], PUNCT, "("):
                return True
    return False


# --- QL006 -----------------------------------------------------------------------------------

_WRAPPING_FUNCTIONS = frozenset({"lower", "upper", "date", "cast", "coalesce", "extract"})
_COMPARISONS = frozenset({"=", "<>", "!=", "<", ">", "<=", ">=", "<=>"})
_COMPARISON_WORDS = frozenset({"like", "ilike", "in", "between", "is", "not"})
_NOT_COLUMNS = frozenset(
    {
        "year",
        "month",
        "day",
        "hour",
        "minute",
        "second",
        "week",
        "quarter",
        "epoch",
        "dow",
        "doy",
        "current_date",
        "current_time",
        "current_timestamp",
        "null",
        "true",
        "false",
    }
)


def function_on_filtered_column(tokens: Sequence[Token]) -> bool:
    for i, token in enumerate(tokens):
        if not _word(token, "where", "and", "or"):
            continue
        j = i + 1
        while j < len(tokens) and _is(tokens[j], PUNCT, "("):
            j += 1
        if _wraps_column_in_comparison(tokens, j):
            return True
    return False


def _wraps_column_in_comparison(tokens: Sequence[Token], index: int) -> bool:
    if not (
        index + 1 < len(tokens)
        and _word(tokens[index], *_WRAPPING_FUNCTIONS)
        and _is(tokens[index + 1], PUNCT, "(")
    ):
        return False
    end = _skip_group(tokens, index + 1)
    if not _has_column(tokens[index + 2 : end - 1]):
        return False
    after = end
    while after + 1 < len(tokens) and _is(tokens[after], PUNCT, "::"):
        after += 2  # skip a "::type" cast
    if after >= len(tokens):
        return False
    following = tokens[after]
    return (following.kind == OP and following.text in _COMPARISONS) or _word(
        following, *_COMPARISON_WORDS
    )


def _has_column(args: Sequence[Token]) -> bool:
    for i, token in enumerate(args):
        if token.kind not in (WORD, IDENT):
            continue
        previous = args[i - 1] if i > 0 else None
        is_keyword = token.kind == WORD and token.text in ("as", "from", "in", "and", "or", "not")
        is_function = i + 1 < len(args) and _is(args[i + 1], PUNCT, "(")
        is_type = previous is not None and _word(previous, "as")
        is_non_column = token.kind == WORD and token.text in _NOT_COLUMNS
        if not (is_keyword or is_function or is_type or is_non_column):
            return True
    return False


# --- QL008 -----------------------------------------------------------------------------------

_AGGREGATES = frozenset(
    {
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "string_agg",
        "array_agg",
        "group_concat",
        "json_agg",
        "jsonb_agg",
        "bool_and",
        "bool_or",
        "every",
        "stddev",
        "variance",
    }
)


def unbounded_select(tokens: Sequence[Token]) -> bool:
    if not tokens or not _word(tokens[0], "select"):
        return False
    top = [token for _, token in _top_level(tokens)]
    if not any(_word(token, "from") for token in top):
        return False
    if any(_word(token, "where", "limit", "fetch", "top", "group", "having") for token in top):
        return False
    return not any(
        _word(token, *_AGGREGATES) and _is(tokens[i + 1], PUNCT, "(")
        for i, token in enumerate(tokens[:-1])
    )


# --- registry --------------------------------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        Hint(
            "QL001",
            "SELECT *",
            "Heuristic: the select list contains * or table.*, which reads every column and "
            "breaks covering indexes. It cannot know whether you really need all columns.",
        ),
        select_star,
    ),
    Rule(
        Hint(
            "QL002",
            "Unfiltered write",
            "Heuristic: an UPDATE or DELETE has no top-level WHERE clause and touches every row. "
            "It is sometimes intentional (maintenance jobs) and statements starting with WITH "
            "are not inspected.",
        ),
        unfiltered_write,
    ),
    Rule(
        Hint(
            "QL003",
            "Leading-wildcard LIKE",
            "Heuristic: LIKE/ILIKE with a literal pattern starting with %, which usually "
            "prevents B-tree index use. Patterns built at runtime (CONCAT, ||, parameters) are "
            "not detected.",
        ),
        leading_wildcard_like,
    ),
    Rule(
        Hint(
            "QL004",
            "Large OFFSET",
            f"Heuristic: a literal OFFSET (or MySQL LIMIT offset, count) above "
            f"{OFFSET_THRESHOLD}; the database must read and discard all skipped rows. "
            "Offsets passed as parameters are not detected.",
        ),
        large_offset,
    ),
    Rule(
        Hint(
            "QL005",
            "Random ordering",
            "Heuristic: ORDER BY RAND() / RANDOM() sorts the whole result set; the cost grows "
            "with table size even when only a few rows are returned.",
        ),
        random_ordering,
    ),
    Rule(
        Hint(
            "QL006",
            "Function on filtered column",
            "Heuristic: a column is wrapped in LOWER, UPPER, DATE, CAST, COALESCE or EXTRACT "
            "inside a WHERE/AND/OR comparison, which can prevent plain index use. An "
            "expression index may make it fine.",
        ),
        function_on_filtered_column,
    ),
    Rule(
        Hint(
            "QL007",
            "High rows examined",
            "Heuristic (MySQL only): total Rows_examined divided by total Rows_sent exceeds "
            f"{EXAMINED_PER_SENT_THRESHOLD}, suggesting a missing or unused index. Computed "
            "per fingerprint from log counters, not from a query plan.",
        ),
    ),
    Rule(
        Hint(
            "QL008",
            "Unbounded SELECT",
            "Heuristic: a non-aggregate SELECT ... FROM with no WHERE and no LIMIT returns "
            "every row. Fine for small lookup tables; statements starting with WITH are not "
            "inspected.",
        ),
        unbounded_select,
    ),
)

HINTS: dict[str, Hint] = {rule.hint.id: rule.hint for rule in RULES}


def evaluate(tokens: Sequence[Token]) -> frozenset[str]:
    """Return the IDs of all query-text rules triggered by ``tokens``."""
    return frozenset(
        rule.hint.id for rule in RULES if rule.check is not None and rule.check(tokens)
    )


def high_rows_examined(examined_per_sent: float | None) -> bool:
    """QL007: True when the examined-to-sent ratio is known and above the threshold."""
    return examined_per_sent is not None and examined_per_sent > EXAMINED_PER_SENT_THRESHOLD
