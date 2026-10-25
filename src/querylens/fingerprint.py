"""Query normalization and fingerprinting.

``normalize`` turns a raw SQL statement into a privacy-safe *shape*: comments are removed, every
literal and placeholder becomes ``?``, keywords and identifiers are lowercased, whitespace is
canonicalized and variable-length ``IN (...)`` / ``VALUES (...)`` lists collapse to ``(?+)``.

The work is done by a single left-to-right tokenizer (one master regular expression applied at the
current position, plus small hand-written scanners for nested comments and dollar quotes), so a
``--`` or a quote inside a string literal can never be mistaken for syntax.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Dialect = Literal["generic", "postgres", "mysql"]

# Token kinds.
WORD = "word"  # keyword or bare identifier, lowercased
IDENT = "ident"  # quoted identifier, lowercased
LITERAL = "literal"  # any literal or placeholder, rendered as "?" (or "?+" for a collapsed list)
OP = "op"  # operator such as =, <>, ||, ->>
PUNCT = "punct"  # ( ) , ; [ ] { } . :: :=

#: Keywords after which ``(`` is always preceded by a space and a ``-`` starts a negative number.
KEYWORDS = frozenset(
    [
        "all",
        "and",
        "any",
        "as",
        "between",
        "by",
        "case",
        "distinct",
        "else",
        "exists",
        "from",
        "having",
        "ilike",
        "in",
        "into",
        "is",
        "join",
        "like",
        "limit",
        "not",
        "offset",
        "on",
        "or",
        "over",
        "return",
        "returning",
        "select",
        "set",
        "some",
        "then",
        "union",
        "using",
        "values",
        "when",
        "where",
        "with",
        "within",
    ]
)

_SIMPLE_IDENT = re.compile(r"[^\W\d][\w$]*")
_OP_SPECIAL = frozenset("~!@#%^&|")
_NEGATABLE_AFTER = frozenset({"(", ",", "["})
_COLLAPSE_VALUE_WORDS = frozenset(
    {
        "null",
        "default",
        "true",
        "false",
        "current_timestamp",
        "current_date",
        "current_time",
    }
)

_COMMON_PATTERNS = r"""
    (?P<ws>\s+)
  | (?P<line_comment>--[^\n]*)
  | (?P<block_comment>/\*)
  | (?P<string>@@STRING@@)
  | (?P<backtick>`(?:[^`]|``)*(?:`|\Z))
  | (?P<dollar>\$(?:[^\W\d]\w*)?\$)
  | (?P<param>\$\d+|\?\+(?=\s*\))|\?|:[^\W\d]\w*)
  | (?P<colon>::|:=|:)
  | (?P<number>0[xX][0-9A-Fa-f]+|0[bB][01]+|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<word>[^\W\d][\w$]*)
  | (?P<punct>[(),;\[\]{}.])
"""

# Strings with backslash escapes (MySQL, and the conservative choice for unknown dialects).
_BACKSLASH_STRING = r"""(?:[eEnNbBxX](?='))?'(?:[^'\\]|\\.|'')*(?:'|\Z)"""
# PostgreSQL: backslashes are escapes only inside E'...' strings (standard_conforming_strings).
_POSTGRES_STRING = r"""[eE]'(?:[^'\\]|\\.|'')*(?:'|\Z)|(?:[nNbBxX](?='))?'(?:[^']|'')*(?:'|\Z)"""

_GENERIC_TAIL = r"""
  | (?P<dquote>"(?:[^"]|"")*(?:"|\Z))
  | (?P<op>[+\-*/<>=~!@#%^&|]+)
  | (?P<other>.)
"""
_MYSQL_TAIL = r"""
  | (?P<dstring>"(?:[^"\\]|\\.|"")*(?:"|\Z))
  | (?P<op>[+\-*/<>=~!@%^&|]+)
  | (?P<other>.)
"""


def _compile(string_pattern: str, tail: str, head: str = "") -> re.Pattern[str]:
    body = _COMMON_PATTERNS.replace("@@STRING@@", string_pattern)
    return re.compile(head + body + tail, re.VERBOSE | re.DOTALL)


_TOKEN_RES: dict[Dialect, re.Pattern[str]] = {
    "generic": _compile(_BACKSLASH_STRING, _GENERIC_TAIL),
    "postgres": _compile(_POSTGRES_STRING, _GENERIC_TAIL),
    "mysql": _compile(_BACKSLASH_STRING, _MYSQL_TAIL, head=r"(?P<hash_comment>\#[^\n]*)|"),
}


@dataclass(frozen=True, slots=True)
class Token:
    """One lexical token.

    ``value`` holds the raw literal text for ``LITERAL`` tokens (for example ``'%foo'`` or
    ``5000``). It exists only so that hint rules can inspect literal values in memory; it is never
    rendered.
    """

    kind: str
    text: str
    space_before: bool = False
    value: str | None = None


def tokenize(sql: str, dialect: Dialect = "generic") -> list[Token]:
    """Split ``sql`` into tokens, dropping comments and whitespace."""
    pattern = _TOKEN_RES[dialect]
    tokens: list[Token] = []
    pos, end = 0, len(sql)
    space = False
    while pos < end:
        match = pattern.match(sql, pos)
        assert match is not None  # the final ``other`` alternative matches any character
        group = match.lastgroup
        text = match.group()
        new_pos = match.end()
        if group in ("ws", "line_comment", "hash_comment"):
            space = True
        elif group == "block_comment":
            new_pos = _skip_block_comment(sql, pos, nested=dialect != "mysql")
            space = True
        else:
            token, new_pos = _make_token(group, text, sql, pos, new_pos, tokens, space)
            tokens.append(token)
            space = False
        pos = new_pos
    return tokens


def _make_token(
    group: str | None,
    text: str,
    sql: str,
    start: int,
    end: int,
    previous: Sequence[Token],
    space: bool,
) -> tuple[Token, int]:
    """Build the token for a non-whitespace match, returning it and the next scan position."""
    if group in ("string", "dstring", "number", "param"):
        return Token(LITERAL, "?+" if text == "?+" else "?", space, text), end
    if group == "dollar":
        close = sql.find(text, end)
        stop = len(sql) if close == -1 else close + len(text)
        return Token(LITERAL, "?", space, sql[start:stop]), stop
    if group == "word":
        return Token(WORD, text.lower(), space), end
    if group in ("dquote", "backtick"):
        return _quoted_identifier(text, space), end
    if group == "op":
        return _operator(text, sql, start, previous, space)
    return Token(PUNCT, text, space), end


def _skip_block_comment(sql: str, start: int, *, nested: bool) -> int:
    """Return the position just after the block comment starting at ``start``."""
    depth = 0
    pos = start
    while pos < len(sql):
        if sql.startswith("/*", pos) and (nested or depth == 0):
            depth += 1
            pos += 2
        elif sql.startswith("*/", pos):
            depth -= 1
            pos += 2
            if depth == 0:
                return pos
        else:
            pos += 1
    return len(sql)


def _quoted_identifier(text: str, space: bool) -> Token:
    quote = text[0]
    inner = text[1:-1] if len(text) > 1 and text.endswith(quote) else text[1:]
    inner = inner.replace(quote * 2, quote).lower()
    if _SIMPLE_IDENT.fullmatch(inner) and inner not in KEYWORDS:
        return Token(IDENT, inner, space)
    return Token(IDENT, quote + inner.replace(quote, quote * 2) + quote, space)


def _operator(
    text: str, sql: str, start: int, previous: Sequence[Token], space: bool
) -> tuple[Token, int]:
    """Lex an operator the way PostgreSQL does.

    A run of operator characters is cut before any ``--`` or ``/*`` (they start comments) and a
    trailing ``+``/``-`` is given back unless the run contains one of ``~!@#%^&|``, so ``=-1``
    lexes as ``=`` followed by ``-1``. A ``-`` directly followed by a number becomes part of a
    negative literal when the previous token cannot end an operand.
    """
    for marker in ("--", "/*"):
        cut = text.find(marker)
        if cut > 0:
            text = text[:cut]
    if not _OP_SPECIAL.intersection(text):
        while len(text) > 1 and text[-1] in "+-":
            text = text[:-1]
    end = start + len(text)
    if text == "-" and _starts_operand(previous):
        number = _TOKEN_RES["generic"].match(sql, end)
        if number is not None and number.lastgroup == "number":
            return Token(LITERAL, "?", space, "-" + number.group()), number.end()
    return Token(OP, text, space), end


def _starts_operand(previous: Sequence[Token]) -> bool:
    """True when the next token must begin an operand (so ``-`` is a sign, not subtraction)."""
    if not previous:
        return True
    last = previous[-1]
    if last.kind == OP:
        return True
    if last.kind == PUNCT:
        return last.text in _NEGATABLE_AFTER
    return last.kind == WORD and last.text in KEYWORDS


def collapse_lists(tokens: Sequence[Token]) -> list[Token]:
    """Collapse ``in (?, ?, ...)`` and ``values (...), (...)`` to ``(?+)``."""
    out: list[Token] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        out.append(token)
        i += 1
        if token.kind != WORD or token.text not in ("in", "values"):
            continue
        allowed = _COLLAPSE_VALUE_WORDS if token.text == "values" else frozenset()
        end = _match_literal_tuple(tokens, i, allowed)
        if end is None:
            continue
        if token.text == "values":
            while end < len(tokens) and tokens[end].text == ",":
                next_end = _match_literal_tuple(tokens, end + 1, allowed)
                if next_end is None:
                    break
                end = next_end
        out.extend(
            (
                Token(PUNCT, "(", True),
                Token(LITERAL, "?+"),
                Token(PUNCT, ")"),
            )
        )
        i = end
    return out


def _match_literal_tuple(tokens: Sequence[Token], start: int, words: frozenset[str]) -> int | None:
    """Match ``( item [, item]... )`` where every item is a literal, one of ``words``, or (for
    ``values``) a call without arguments such as ``now()``.

    Returns the index just after the closing parenthesis, or ``None`` if there is no such tuple.
    """
    if start >= len(tokens) or tokens[start].text != "(":
        return None
    i = start + 1
    expect_item = True
    while i < len(tokens):
        token = tokens[i]
        if expect_item:
            if token.kind == LITERAL or (token.kind == WORD and token.text in words):
                pass
            elif words and token.kind == WORD and _is_empty_call(tokens, i):
                i += 2  # skip the "(" and let the common code skip the ")"
            else:
                return None
        elif token.text == ")":
            return i + 1
        elif token.text != ",":
            return None
        expect_item = not expect_item
        i += 1
    return None


def _is_empty_call(tokens: Sequence[Token], index: int) -> bool:
    return (
        index + 2 < len(tokens) and tokens[index + 1].text == "(" and tokens[index + 2].text == ")"
    )


def render(tokens: Sequence[Token]) -> str:
    """Join tokens with canonical spacing."""
    parts: list[str] = []
    previous: Token | None = None
    for token in tokens:
        if previous is not None and _needs_space(previous, token):
            parts.append(" ")
        parts.append(token.text)
        previous = token
    return "".join(parts)


def _needs_space(previous: Token, token: Token) -> bool:
    if token.text in (")", ",", ".", "::", ";", "[", "]") and token.kind == PUNCT:
        return False
    if previous.kind == PUNCT and previous.text in ("(", ".", "::", "["):
        return False
    if token.kind == PUNCT and token.text == "(" and previous.kind in (WORD, IDENT):
        # Function calls keep their original "f(" / "f (" spacing; keywords always get a space.
        return previous.text in KEYWORDS or token.space_before
    return True


def normalize_tokens(tokens: Sequence[Token]) -> str:
    """Render already-tokenized SQL as its normalized form."""
    collapsed = collapse_lists(tokens)
    while collapsed and collapsed[-1].kind == PUNCT and collapsed[-1].text == ";":
        collapsed.pop()
    return render(collapsed)


def normalize(sql: str, dialect: Dialect = "generic") -> str:
    """Return the normalized, literal-free shape of ``sql``.

    ``dialect="mysql"`` additionally treats ``"..."`` as a string literal (MySQL's default
    ``sql_mode``) and ``#`` as a line comment. The function is idempotent:
    ``normalize(normalize(x)) == normalize(x)``.
    """
    return normalize_tokens(tokenize(sql, dialect))


def fingerprint_id(normalized: str) -> str:
    """Return the 12-hex-character fingerprint ID of a normalized query."""
    return hashlib.sha1(normalized.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
