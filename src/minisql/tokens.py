"""Turns SQL text into tokens.

The tokenizer keeps each token's position in the source so an error can point at
the exact character that caused it, rather than saying "syntax error" and leaving
the reader to find it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class Kind(Enum):
    KEYWORD = auto()
    IDENT = auto()
    NUMBER = auto()
    STRING = auto()
    OPERATOR = auto()
    PUNCT = auto()
    STAR = auto()
    EOF = auto()


KEYWORDS = frozenset({
    "select", "from", "where", "group", "by", "having", "order", "limit", "offset",
    "as", "join", "inner", "left", "on", "and", "or", "not", "null", "is", "in",
    "like", "asc", "desc", "distinct", "true", "false",
    "count", "sum", "avg", "min", "max",
    "case", "when", "then", "else", "end", "union", "all",
    "insert", "into", "values", "update", "set", "delete",
})

# Longest first: '<=' must be matched before '<'.
OPERATORS = ("<>", "!=", "<=", ">=", "=", "<", ">", "+", "-", "*", "/", "%")


@dataclass(frozen=True)
class Token:
    kind: Kind
    text: str
    position: int

    @property
    def value(self) -> str:
        """The token as the parser compares it: keywords are case-insensitive."""
        return self.text.lower() if self.kind is Kind.KEYWORD else self.text

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.kind.name}({self.text!r})"


class SqlError(Exception):
    """A problem in the query, with the position that caused it."""

    def __init__(self, message: str, position: int | None = None, source: str | None = None):
        self.position = position
        self.source = source
        super().__init__(self._render(message))

    def _render(self, message: str) -> str:
        if self.position is None or self.source is None:
            return message
        line_start = self.source.rfind("\n", 0, self.position) + 1
        line_end = self.source.find("\n", self.position)
        line = self.source[line_start : line_end if line_end != -1 else len(self.source)]
        caret = " " * (self.position - line_start) + "^"
        return f"{message}\n  {line}\n  {caret}"


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    length = len(sql)

    while i < length:
        char = sql[i]

        if char.isspace():
            i += 1
            continue

        if char == "-" and sql.startswith("--", i):
            newline = sql.find("\n", i)
            i = length if newline == -1 else newline + 1
            continue

        if char == "'":
            end = i + 1
            chunks: list[str] = []
            while True:
                if end >= length:
                    raise SqlError("unterminated string", i, sql)
                if sql[end] == "'":
                    if sql.startswith("''", end):  # '' is an escaped quote
                        chunks.append("'")
                        end += 2
                        continue
                    break
                chunks.append(sql[end])
                end += 1
            tokens.append(Token(Kind.STRING, "".join(chunks), i))
            i = end + 1
            continue

        if char.isdigit() or (char == "." and i + 1 < length and sql[i + 1].isdigit()):
            end = i
            seen_dot = False
            while end < length and (sql[end].isdigit() or (sql[end] == "." and not seen_dot)):
                seen_dot = seen_dot or sql[end] == "."
                end += 1
            tokens.append(Token(Kind.NUMBER, sql[i:end], i))
            i = end
            continue

        if char.isalpha() or char == "_":
            end = i
            while end < length and (sql[end].isalnum() or sql[end] in "_."):
                end += 1
            word = sql[i:end]
            kind = Kind.KEYWORD if word.lower() in KEYWORDS else Kind.IDENT
            tokens.append(Token(kind, word, i))
            i = end
            continue

        if char == "*":
            tokens.append(Token(Kind.STAR, "*", i))
            i += 1
            continue

        matched = next((op for op in OPERATORS if sql.startswith(op, i)), None)
        if matched:
            tokens.append(Token(Kind.OPERATOR, matched, i))
            i += len(matched)
            continue

        if char in "(),":
            tokens.append(Token(Kind.PUNCT, char, i))
            i += 1
            continue

        raise SqlError(f"unexpected character {char!r}", i, sql)

    tokens.append(Token(Kind.EOF, "", length))
    return tokens
