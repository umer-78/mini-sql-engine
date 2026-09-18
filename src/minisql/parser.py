"""A recursive-descent parser for the subset of SQL this engine runs.

Precedence is expressed by the call chain rather than by a table: `_or` calls
`_and` calls `_not` calls `_comparison` calls `_sum` calls `_product` calls
`_unary` calls `_primary`. Reading the functions top to bottom reads the
precedence from loosest to tightest.
"""

from __future__ import annotations

from .ast import (
    Aggregate,
    Binary,
    Column,
    Expr,
    InList,
    IsNull,
    Join,
    Like,
    Literal,
    OrderItem,
    Select,
    SelectItem,
    TableRef,
    Unary,
)
from .tokens import Kind, SqlError, Token, tokenize

AGGREGATES = frozenset({"count", "sum", "avg", "min", "max"})
COMPARISONS = frozenset({"=", "<>", "!=", "<", "<=", ">", ">="})


class Parser:
    def __init__(self, sql: str):
        self.sql = sql
        self.tokens = tokenize(sql)
        self.index = 0

    # -- token helpers -----------------------------------------------------

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.current
        self.index += 1
        return token

    def at(self, *values: str) -> bool:
        return self.current.value.lower() in values if self.current.kind is not Kind.EOF else False

    def accept(self, *values: str) -> Token | None:
        if self.at(*values):
            return self.advance()
        return None

    def expect(self, *values: str) -> Token:
        if self.at(*values):
            return self.advance()
        found = "end of query" if self.current.kind is Kind.EOF else repr(self.current.text)
        wanted = " or ".join(repr(v) for v in values)
        raise SqlError(f"expected {wanted}, found {found}", self.current.position, self.sql)

    def expect_name(self, what: str) -> str:
        if self.current.kind is not Kind.IDENT:
            found = "end of query" if self.current.kind is Kind.EOF else repr(self.current.text)
            raise SqlError(f"expected a {what}, found {found}", self.current.position, self.sql)
        return self.advance().text

    # -- statement ---------------------------------------------------------

    def parse(self) -> Select:
        self.expect("select")
        distinct = self.accept("distinct") is not None
        items = self._select_items()

        self.expect("from")
        source = self._table_ref()
        joins = self._joins()

        where = self._expression() if self.accept("where") else None

        group_by: list[Expr] = []
        if self.accept("group"):
            self.expect("by")
            group_by = self._expression_list()

        having = self._expression() if self.accept("having") else None

        order_by: list[OrderItem] = []
        if self.accept("order"):
            self.expect("by")
            while True:
                expr = self._expression()
                descending = False
                if self.accept("desc"):
                    descending = True
                else:
                    self.accept("asc")
                order_by.append(OrderItem(expr, descending))
                if not self.accept(","):
                    break

        limit = None
        offset = 0
        if self.accept("limit"):
            limit = self._non_negative_int("LIMIT")
        if self.accept("offset"):
            offset = self._non_negative_int("OFFSET")

        if self.current.kind is not Kind.EOF:
            raise SqlError(
                f"unexpected {self.current.text!r} after the end of the query",
                self.current.position,
                self.sql,
            )

        if having is not None and not group_by:
            raise SqlError("HAVING needs a GROUP BY")

        return Select(
            items=tuple(items),
            source=source,
            joins=tuple(joins),
            where=where,
            group_by=tuple(group_by),
            having=having,
            order_by=tuple(order_by),
            limit=limit,
            offset=offset,
            distinct=distinct,
        )

    def _non_negative_int(self, what: str) -> int:
        token = self.current
        if token.kind is not Kind.NUMBER or "." in token.text:
            raise SqlError(f"{what} needs a whole number", token.position, self.sql)
        self.advance()
        return int(token.text)

    def _select_items(self) -> list[SelectItem]:
        items: list[SelectItem] = []
        while True:
            if self.current.kind is Kind.STAR:
                self.advance()
                items.append(SelectItem(None))
            elif (
                self.current.kind is Kind.IDENT
                and self.current.text.endswith(".")
                and self.tokens[self.index + 1].kind is Kind.STAR
            ):
                # `pets.*` arrives as IDENT('pets.') followed by STAR, because the
                # tokenizer stops an identifier at the '*'.
                qualifier = self.advance().text[:-1]
                self.advance()
                items.append(SelectItem(None, qualifier=qualifier))
            else:
                expr = self._expression()
                alias = None
                if self.accept("as"):
                    alias = self.expect_name("column alias")
                elif self.current.kind is Kind.IDENT:
                    alias = self.advance().text
                items.append(SelectItem(expr, alias))
            if not self.accept(","):
                return items

    def _table_ref(self) -> TableRef:
        name = self.expect_name("table name")
        alias = None
        if self.accept("as"):
            alias = self.expect_name("table alias")
        elif self.current.kind is Kind.IDENT:
            alias = self.advance().text
        return TableRef(name, alias)

    def _joins(self) -> list[Join]:
        joins: list[Join] = []
        while True:
            kind = "inner"
            if self.accept("left"):
                kind = "left"
                self.accept("inner")  # tolerate LEFT OUTER-style noise words
            elif self.accept("inner"):
                kind = "inner"
            elif not self.at("join"):
                return joins
            self.expect("join")
            table = self._table_ref()
            self.expect("on")
            joins.append(Join(table, self._expression(), kind))

    # -- expressions -------------------------------------------------------

    def _expression_list(self) -> list[Expr]:
        items = [self._expression()]
        while self.accept(","):
            items.append(self._expression())
        return items

    def _expression(self) -> Expr:
        return self._or()

    def _or(self) -> Expr:
        left = self._and()
        while self.accept("or"):
            left = Binary("or", left, self._and())
        return left

    def _and(self) -> Expr:
        left = self._not()
        while self.accept("and"):
            left = Binary("and", left, self._not())
        return left

    def _not(self) -> Expr:
        if self.accept("not"):
            return Unary("not", self._not())
        return self._comparison()

    def _comparison(self) -> Expr:
        left = self._sum()

        if self.accept("is"):
            negated = self.accept("not") is not None
            self.expect("null")
            return IsNull(left, negated)

        negated = False
        if self.at("not") and self.tokens[self.index + 1].value.lower() in {"in", "like"}:
            self.advance()
            negated = True

        if self.accept("in"):
            self.expect("(")
            items = self._expression_list()
            self.expect(")")
            return InList(left, tuple(items), negated)

        if self.accept("like"):
            return Like(left, self._sum(), negated)

        if negated:  # pragma: no cover - unreachable, the lookahead above guards it
            raise SqlError("NOT must be followed by IN or LIKE here", self.current.position, self.sql)

        if self.current.kind is Kind.OPERATOR and self.current.text in COMPARISONS:
            op = self.advance().text
            return Binary("<>" if op == "!=" else op, left, self._sum())

        return left

    def _sum(self) -> Expr:
        left = self._product()
        while self.current.kind is Kind.OPERATOR and self.current.text in {"+", "-"}:
            op = self.advance().text
            left = Binary(op, left, self._product())
        return left

    def _product(self) -> Expr:
        left = self._unary()
        while (self.current.kind is Kind.OPERATOR and self.current.text in {"/", "%"}) or self.current.kind is Kind.STAR:
            op = self.advance().text
            left = Binary(op, left, self._unary())
        return left

    def _unary(self) -> Expr:
        if self.current.kind is Kind.OPERATOR and self.current.text == "-":
            self.advance()
            return Unary("-", self._unary())
        return self._primary()

    def _primary(self) -> Expr:
        token = self.current

        if token.kind is Kind.NUMBER:
            self.advance()
            return Literal(float(token.text) if "." in token.text else int(token.text))

        if token.kind is Kind.STRING:
            self.advance()
            return Literal(token.text)

        if self.accept("null"):
            return Literal(None)

        if self.at("true", "false"):
            return Literal(self.advance().value.lower() == "true")

        if token.kind is Kind.KEYWORD and token.value.lower() in AGGREGATES:
            return self._aggregate()

        if token.kind is Kind.IDENT:
            self.advance()
            return Column(token.text)

        if self.accept("("):
            inner = self._expression()
            self.expect(")")
            return inner

        found = "end of query" if token.kind is Kind.EOF else repr(token.text)
        raise SqlError(f"expected a value, found {found}", token.position, self.sql)

    def _aggregate(self) -> Expr:
        func = self.advance().value.lower()
        self.expect("(")

        if func == "count" and self.current.kind is Kind.STAR:
            self.advance()
            self.expect(")")
            return Aggregate("count")

        distinct = self.accept("distinct") is not None
        arg = self._expression()
        self.expect(")")
        return Aggregate(func, arg, distinct)


def parse(sql: str) -> Select:
    return Parser(sql).parse()
