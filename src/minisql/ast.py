"""The shapes the parser produces and the executor walks.

Every node is a frozen dataclass: once a query is parsed, nothing rewrites it in
place, so the plan the executor runs is the plan the parser produced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class Expr:
    """Base class for anything that evaluates to a value for one row."""


@dataclass(frozen=True)
class Literal(Expr):
    value: Any


@dataclass(frozen=True)
class Column(Expr):
    name: str

    @property
    def qualifier(self) -> str | None:
        """The table part of `orders.total`, or None for a bare column."""
        return self.name.split(".", 1)[0] if "." in self.name else None

    @property
    def bare(self) -> str:
        return self.name.split(".", 1)[1] if "." in self.name else self.name


@dataclass(frozen=True)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Unary(Expr):
    op: str
    operand: Expr


@dataclass(frozen=True)
class Aggregate(Expr):
    func: str
    arg: Expr | None = None  # None means COUNT(*)
    distinct: bool = False


@dataclass(frozen=True)
class InList(Expr):
    value: Expr
    items: tuple[Expr, ...]
    negated: bool = False


@dataclass(frozen=True)
class IsNull(Expr):
    value: Expr
    negated: bool = False


@dataclass(frozen=True)
class Like(Expr):
    value: Expr
    pattern: Expr
    negated: bool = False


@dataclass(frozen=True)
class TableRef:
    name: str
    alias: str | None = None

    @property
    def label(self) -> str:
        """What a qualified column must use: the alias if given, else the name."""
        return self.alias or self.name


@dataclass(frozen=True)
class Join:
    table: TableRef
    on: Expr
    kind: str = "inner"  # "inner" or "left"


@dataclass(frozen=True)
class SelectItem:
    expr: Expr | None  # None means '*'
    alias: str | None = None
    qualifier: str | None = None  # for `t.*`

    @property
    def is_star(self) -> bool:
        return self.expr is None


@dataclass(frozen=True)
class OrderItem:
    expr: Expr
    descending: bool = False


@dataclass(frozen=True)
class Select:
    items: tuple[SelectItem, ...]
    source: TableRef
    joins: tuple[Join, ...] = ()
    where: Expr | None = None
    group_by: tuple[Expr, ...] = ()
    having: Expr | None = None
    order_by: tuple[OrderItem, ...] = ()
    limit: int | None = None
    offset: int = 0
    distinct: bool = False
    columns: tuple[str, ...] = field(default=())
