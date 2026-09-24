"""Runs a parsed query against a database.

NULL follows SQL's three-valued logic, which is the part people expect to be
wrong: `NULL = NULL` is unknown, not true; `NULL AND false` is false, not
unknown; and a row is kept by WHERE only when the condition is *true*, never
when it is unknown.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .ast import (
    Aggregate,
    Binary,
    Case,
    Column,
    Delete,
    Expr,
    InList,
    Insert,
    IsNull,
    Like,
    Literal,
    Select,
    Statement,
    Unary,
    Union,
    Update,
)
from .storage import Database, Row, Table
from .tokens import SqlError

NUMBER = (int, float)


@dataclass
class Projected:
    """One output row, kept beside the input row it came from.

    ORDER BY may name a column that is not in the SELECT list, so the source row
    has to survive projection — otherwise `ORDER BY age` on `SELECT name` would
    silently sort by nothing at all.
    """

    out: Row
    source: Row
    groups: dict[int, Any]


@dataclass
class Result:
    columns: list[str]
    rows: list[list[Any]]

    def __len__(self) -> int:
        return len(self.rows)

    def dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row, strict=False)) for row in self.rows]


class Scope:
    """Maps the names a query may use to the keys a joined row actually has."""

    def __init__(self) -> None:
        self.qualified: list[str] = []
        self._bare: dict[str, list[str]] = {}

    def add_table(self, label: str, columns: Iterable[str]) -> None:
        for column in columns:
            key = f"{label}.{column}"
            self.qualified.append(key)
            self._bare.setdefault(column.lower(), []).append(key)

    def resolve(self, name: str) -> str:
        if "." in name:
            for key in self.qualified:
                if key.lower() == name.lower():
                    return key
            raise SqlError(f"no column {name!r}")
        matches = self._bare.get(name.lower(), [])
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise SqlError(f"no column {name!r} (columns: {', '.join(self.qualified)})")
        raise SqlError(f"column {name!r} is ambiguous — it is in {' and '.join(matches)}")


def _truthy(value: Any) -> bool:
    """A row survives a filter only when the condition is true, not unknown."""
    return value is True or (value is not None and value is not False and bool(value))


def _compare(op: str, left: Any, right: Any) -> Any:
    if left is None or right is None:
        return None  # unknown, not false
    if isinstance(left, NUMBER) and isinstance(right, NUMBER) and not isinstance(left, bool) and not isinstance(right, bool):
        pass
    elif type(left) is not type(right):
        left, right = str(left), str(right)
    try:
        return {
            "=": left == right,
            "<>": left != right,
            "<": left < right,
            "<=": left <= right,
            ">": left > right,
            ">=": left >= right,
        }[op]
    except TypeError:  # pragma: no cover - the coercion above makes this unreachable
        raise SqlError(f"cannot compare {left!r} with {right!r}") from None


def _arithmetic(op: str, left: Any, right: Any) -> Any:
    if left is None or right is None:
        return None
    if not isinstance(left, NUMBER) or not isinstance(right, NUMBER):
        if op == "+" and isinstance(left, str) and isinstance(right, str):
            raise SqlError("use a string function to join text; '+' is arithmetic only")
        raise SqlError(f"cannot apply {op!r} to {left!r} and {right!r}")
    if op in {"/", "%"} and right == 0:
        return None  # division by zero yields NULL rather than crashing the query
    return {
        "+": lambda: left + right,
        "-": lambda: left - right,
        "*": lambda: left * right,
        "/": lambda: left / right,
        "%": lambda: left % right,
    }[op]()


def _like(value: Any, pattern: Any) -> Any:
    if value is None or pattern is None:
        return None
    regex = "^" + "".join(
        ".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in str(pattern)
    ) + "$"
    return re.match(regex, str(value), re.IGNORECASE) is not None


def evaluate(expr: Expr, row: Row, scope: Scope, groups: dict[int, Any] | None = None) -> Any:
    if isinstance(expr, Literal):
        return expr.value

    if isinstance(expr, Column):
        if groups is not None and expr.name in row:  # a projected alias in ORDER BY
            return row[expr.name]
        return row.get(scope.resolve(expr.name))

    if isinstance(expr, Aggregate):
        if groups is None or id(expr) not in groups:
            raise SqlError(f"{expr.func.upper()} is only allowed where aggregates are computed")
        return groups[id(expr)]

    if isinstance(expr, Unary):
        if expr.op == "not":
            inner = evaluate(expr.operand, row, scope, groups)
            return None if inner is None else not _truthy(inner)
        value = evaluate(expr.operand, row, scope, groups)
        return None if value is None else -value

    if isinstance(expr, Binary):
        if expr.op == "and":
            left = evaluate(expr.left, row, scope, groups)
            if left is not None and not _truthy(left):
                return False  # false AND unknown is false
            right = evaluate(expr.right, row, scope, groups)
            if right is not None and not _truthy(right):
                return False
            return None if left is None or right is None else True
        if expr.op == "or":
            left = evaluate(expr.left, row, scope, groups)
            if _truthy(left):
                return True  # true OR unknown is true
            right = evaluate(expr.right, row, scope, groups)
            if _truthy(right):
                return True
            return None if left is None or right is None else False

        left = evaluate(expr.left, row, scope, groups)
        right = evaluate(expr.right, row, scope, groups)
        if expr.op in {"=", "<>", "<", "<=", ">", ">="}:
            return _compare(expr.op, left, right)
        return _arithmetic(expr.op, left, right)

    if isinstance(expr, IsNull):
        value = evaluate(expr.value, row, scope, groups)
        return (value is not None) if expr.negated else (value is None)

    if isinstance(expr, InList):
        value = evaluate(expr.value, row, scope, groups)
        if value is None:
            return None
        found = any(
            _compare("=", value, evaluate(item, row, scope, groups)) is True for item in expr.items
        )
        return not found if expr.negated else found

    if isinstance(expr, Case):
        if expr.operand is None:
            for condition, value in expr.whens:
                if _truthy(evaluate(condition, row, scope, groups)):
                    return evaluate(value, row, scope, groups)
        else:
            subject = evaluate(expr.operand, row, scope, groups)
            for candidate, value in expr.whens:
                # NULL never matches a WHEN, not even `WHEN NULL`: = with NULL is unknown.
                if _compare("=", subject, evaluate(candidate, row, scope, groups)) is True:
                    return evaluate(value, row, scope, groups)
        return None if expr.default is None else evaluate(expr.default, row, scope, groups)

    if isinstance(expr, Like):
        result = _like(evaluate(expr.value, row, scope, groups), evaluate(expr.pattern, row, scope, groups))
        if result is None:
            return None
        return not result if expr.negated else result

    raise SqlError(f"cannot evaluate {type(expr).__name__}")  # pragma: no cover


def collect_aggregates(expr: Expr | None, found: list[Aggregate]) -> list[Aggregate]:
    if expr is None:
        return found
    if isinstance(expr, Aggregate):
        found.append(expr)
        return found
    for child in _children(expr):
        collect_aggregates(child, found)
    return found


def _children(expr: Expr) -> list[Expr]:
    if isinstance(expr, Binary):
        return [expr.left, expr.right]
    if isinstance(expr, Unary):
        return [expr.operand]
    if isinstance(expr, (IsNull,)):
        return [expr.value]
    if isinstance(expr, Like):
        return [expr.value, expr.pattern]
    if isinstance(expr, InList):
        return [expr.value, *expr.items]
    if isinstance(expr, Aggregate):
        return [expr.arg] if expr.arg is not None else []
    if isinstance(expr, Case):
        parts = [] if expr.operand is None else [expr.operand]
        for condition, value in expr.whens:
            parts += [condition, value]
        return parts + ([] if expr.default is None else [expr.default])
    return []


def _aggregate_value(agg: Aggregate, rows: list[Row], scope: Scope) -> Any:
    if agg.arg is None:
        return len(rows)

    values = [evaluate(agg.arg, row, scope) for row in rows]
    values = [v for v in values if v is not None]  # aggregates skip NULLs, as SQL does
    if agg.distinct:
        values = list(dict.fromkeys(values))

    if agg.func == "count":
        return len(values)
    if not values:
        return None
    if agg.func == "min":
        return min(values)
    if agg.func == "max":
        return max(values)
    if not all(isinstance(v, NUMBER) for v in values):
        raise SqlError(f"{agg.func.upper()} needs numbers")
    if agg.func == "sum":
        return sum(values)
    return sum(values) / len(values)


def _sort_key(value: Any) -> tuple[int, Any]:
    """NULLs sort last in ascending order; mixed types sort by type then value."""
    if value is None:
        return (3, "")
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, NUMBER):
        return (0, value)
    return (1, str(value))


class Engine:
    def __init__(self, database: Database):
        self.db = database

    def execute(self, statement: Statement) -> Result:
        if isinstance(statement, Union):
            return self._union(statement)
        if isinstance(statement, Insert):
            return self._insert(statement)
        if isinstance(statement, Update):
            return self._update(statement)
        if isinstance(statement, Delete):
            return self._delete(statement)
        return self._select(statement)

    def _select(self, query: Select) -> Result:
        scope = Scope()
        rows = self._from(query, scope)

        if query.where is not None:
            if collect_aggregates(query.where, []):
                raise SqlError("WHERE cannot use an aggregate — use HAVING")
            rows = [row for row in rows if _truthy(evaluate(query.where, row, scope))]

        aggregates = collect_aggregates(query.having, [])
        for item in query.items:
            collect_aggregates(item.expr, aggregates)
        for order in query.order_by:
            collect_aggregates(order.expr, aggregates)

        if query.group_by or aggregates:
            projected = self._grouped(query, rows, scope, aggregates)
        else:
            projected = self._plain(query, rows, scope)

        return self._finish(query, projected, scope)

    # -- FROM and JOIN -----------------------------------------------------

    def _from(self, query: Select, scope: Scope) -> list[Row]:
        base = self.db.get(query.source.name)
        label = query.source.label
        scope.add_table(label, base.columns)
        rows = [{f"{label}.{c}": row[c] for c in base.columns} for row in base.rows]

        for join in query.joins:
            table = self.db.get(join.table.name)
            join_label = join.table.label
            scope.add_table(join_label, table.columns)
            right_rows = [{f"{join_label}.{c}": row[c] for c in table.columns} for row in table.rows]
            blanks = {f"{join_label}.{c}": None for c in table.columns}

            combined: list[Row] = []
            for left in rows:
                matched = False
                for right in right_rows:
                    merged = {**left, **right}
                    if _truthy(evaluate(join.on, merged, scope)):
                        combined.append(merged)
                        matched = True
                if not matched and join.kind == "left":
                    combined.append({**left, **blanks})
            rows = combined

        return rows

    # -- projection --------------------------------------------------------

    def _output_columns(self, query: Select, scope: Scope) -> list[tuple[str, Expr | None, str | None]]:
        columns: list[tuple[str, Expr | None, str | None]] = []
        for index, item in enumerate(query.items, start=1):
            if item.is_star:
                keys = [
                    key for key in scope.qualified
                    if item.qualifier is None or key.split(".", 1)[0].lower() == item.qualifier.lower()
                ]
                if not keys:
                    raise SqlError(f"no table named {item.qualifier!r} in this query")
                for key in keys:
                    # A single-table query shows bare names (`id`, not `people.id`).
                    # As soon as there is a join, every expanded column is qualified:
                    # a mix of the two reads as a bug, and two tables with an `id`
                    # column would otherwise produce two columns of the same name.
                    label = key if query.joins else key.split(".", 1)[1]
                    columns.append((label, Column(key), None))
                continue
            name = item.alias or self._label(item.expr, index)
            columns.append((name, item.expr, item.alias))
        return columns

    @staticmethod
    def _label(expr: Expr | None, index: int) -> str:
        if isinstance(expr, Column):
            return expr.name
        if isinstance(expr, Aggregate):
            inner = "*" if expr.arg is None else Engine._label(expr.arg, index)
            return f"{expr.func}({inner})"
        return f"column{index}"

    def _plain(self, query: Select, rows: list[Row], scope: Scope) -> list[Projected]:
        columns = self._output_columns(query, scope)
        return [
            Projected(
                {name: evaluate(expr, row, scope) for name, expr, _ in columns if expr is not None},
                row,
                {},
            )
            for row in rows
        ]

    def _grouped(self, query: Select, rows: list[Row], scope: Scope, aggregates: list[Aggregate]) -> list[Projected]:
        if query.group_by:
            buckets: dict[tuple, list[Row]] = {}
            for row in rows:
                key = tuple(evaluate(expr, row, scope) for expr in query.group_by)
                buckets.setdefault(key, []).append(row)
            grouped = list(buckets.items())
        else:
            # No GROUP BY but an aggregate is used: the whole table is one group,
            # and an empty table still produces one row (COUNT(*) = 0).
            grouped = [((), rows)]

        grouped_keys = {self._group_key(expr) for expr in query.group_by}
        columns = self._output_columns(query, scope)

        for name, expr, _ in columns:
            if expr is None or collect_aggregates(expr, []):
                continue
            if self._group_key(expr) not in grouped_keys:
                raise SqlError(
                    f"{name!r} is not in GROUP BY and is not an aggregate — "
                    "add it to GROUP BY or wrap it in one"
                )

        output_names = {name for name, _, _ in columns}
        for order in query.order_by:
            expr = order.expr
            if collect_aggregates(expr, []):
                continue
            if isinstance(expr, Column) and expr.name in output_names:
                continue
            if self._group_key(expr) not in grouped_keys:
                raise SqlError(
                    f"ORDER BY {self._label(expr, 0)!r} is not in GROUP BY and is not an aggregate"
                )

        out: list[Projected] = []
        for _, members in grouped:
            values = {id(agg): _aggregate_value(agg, members, scope) for agg in aggregates}
            representative = members[0] if members else {}

            if query.having is not None and not _truthy(
                evaluate(query.having, representative, scope, values)
            ):
                continue

            out.append(Projected(
                {
                    name: evaluate(expr, representative, scope, values)
                    for name, expr, _ in columns
                    if expr is not None
                },
                representative,
                values,
            ))
        return out

    @staticmethod
    def _group_key(expr: Expr) -> str:
        return repr(expr).lower()

    # -- DISTINCT, ORDER BY, LIMIT ----------------------------------------

    def _finish(self, query: Select, projected: list[Projected], scope: Scope) -> Result:
        columns = list(projected[0].out.keys()) if projected else [
            name for name, expr, _ in self._output_columns(query, scope) if expr is not None
        ]

        if query.distinct:
            seen: dict[tuple, Projected] = {}
            for row in projected:
                seen.setdefault(tuple(row.out.get(c) for c in columns), row)
            projected = list(seen.values())

        # Sorted last key first: Python's sort is stable, so the earlier ORDER BY
        # terms end up deciding and the later ones break their ties.
        for order in reversed(query.order_by):
            projected.sort(
                key=lambda row, o=order: _sort_key(self._order_value(o.expr, row, scope)),
                reverse=order.descending,
            )

        if query.offset:
            projected = projected[query.offset :]
        if query.limit is not None:
            projected = projected[: query.limit]

        return Result(columns, [[row.out.get(c) for c in columns] for row in projected])

    def _order_value(self, expr: Expr, row: Projected, scope: Scope) -> Any:
        if isinstance(expr, Column) and expr.name in row.out:
            return row.out[expr.name]
        if isinstance(expr, Aggregate):
            label = self._label(expr, 0)
            if label in row.out:
                return row.out[label]
        try:
            return evaluate(expr, row.source, scope, row.groups)
        except SqlError as error:
            raise SqlError(f"ORDER BY {self._label(expr, 0)}: {error}") from None

    # -- UNION -------------------------------------------------------------

    def _union(self, union: Union) -> Result:
        results = [self._select(select) for select in union.selects]
        width = len(results[0].columns)
        for number, result in enumerate(results[1:], start=2):
            if len(result.columns) != width:
                raise SqlError(
                    f"UNION: SELECT {number} returns {len(result.columns)} column(s), the first returns {width}"
                )

        rows = list(results[0].rows)
        for keep_all, result in zip(union.keep_all, results[1:], strict=True):
            rows.extend(result.rows)
            if not keep_all:  # UNION removes duplicates from everything so far
                rows = list({tuple(row): row for row in reversed(rows)}.values())[::-1]

        columns = results[0].columns
        for order in reversed(union.order_by):
            index = self._union_column(order.expr, columns)
            rows.sort(key=lambda row, i=index: _sort_key(row[i]), reverse=order.descending)

        if union.offset:
            rows = rows[union.offset :]
        if union.limit is not None:
            rows = rows[: union.limit]
        return Result(list(columns), [list(row) for row in rows])

    @staticmethod
    def _union_column(expr: Expr, columns: list[str]) -> int:
        if isinstance(expr, Column):
            for index, name in enumerate(columns):
                if name.lower() == expr.name.lower():
                    return index
        if isinstance(expr, Literal) and isinstance(expr.value, int) and not isinstance(expr.value, bool) \
                and 1 <= expr.value <= len(columns):
            return expr.value - 1
        raise SqlError(
            f"ORDER BY after UNION must name an output column ({', '.join(columns)}) or its position"
        )

    # -- INSERT, UPDATE, DELETE -------------------------------------------
    #
    # Each statement checks every row before changing any: a type error on the
    # fifth VALUES row leaves the table exactly as it was, not half written.

    @staticmethod
    def _column_name(table: Table, name: str) -> str:
        bare = name.split(".", 1)[1] if "." in name and name.split(".", 1)[0].lower() == table.name.lower() else name
        for column in table.columns:
            if column.lower() == bare.lower():
                return column
        raise SqlError(f"table {table.name!r} has no column {name!r} (columns: {', '.join(table.columns)})")

    @staticmethod
    def _coerce(table: Table, column: str, value: Any) -> Any:
        """Fits a value to the column's type, or explains why it does not fit."""
        if value is None:
            return None
        if isinstance(value, bool):
            value = int(value)
        kind = table.types[column]
        # A column with no values yet (a new, empty table) takes the first type it is given.
        if all(row[column] is None for row in table.rows):
            kind = "int" if isinstance(value, int) else "float" if isinstance(value, float) else "str"
            table.types[column] = kind
        if kind == "int":
            if isinstance(value, int):
                return value
            if isinstance(value, float) and value.is_integer():
                return int(value)
        elif kind == "float":
            if isinstance(value, NUMBER):
                return float(value)
        elif isinstance(value, str):
            return value
        names = {"int": "whole numbers", "float": "numbers", "str": "text"}
        hint = " — put it in quotes to store it as text" if kind == "str" else ""
        raise SqlError(f"column {table.name}.{column} holds {names[kind]}; {value!r} does not fit{hint}")

    def _insert(self, insert: Insert) -> Result:
        table = self.db.get(insert.table)
        columns = [self._column_name(table, name) for name in insert.columns] or list(table.columns)
        if len(set(columns)) != len(columns):
            raise SqlError("INSERT names the same column twice")

        if insert.select is not None:
            source = self.execute(insert.select)
            if len(source.columns) != len(columns):
                raise SqlError(f"INSERT expects {len(columns)} value(s) per row; the SELECT returns {len(source.columns)}")
            values = source.rows
        else:
            values = []
            for number, exprs in enumerate(insert.rows, start=1):
                if len(exprs) != len(columns):
                    raise SqlError(f"VALUES row {number} has {len(exprs)} value(s); expected {len(columns)}")
                values.append([evaluate(expr, {}, Scope()) for expr in exprs])

        new_rows = []
        for row_values in values:
            row: Row = dict.fromkeys(table.columns)
            for column, value in zip(columns, row_values, strict=True):
                row[column] = self._coerce(table, column, value)
            new_rows.append(row)

        table.rows.extend(new_rows)
        if new_rows:
            self.db.changed.add(table.name.lower())
        return Result(["inserted"], [[len(new_rows)]])

    def _single_table(self, name: str, where: Expr | None) -> tuple[Table, Scope, list[tuple[Row, Row]]]:
        """The rows of one table that WHERE keeps, each beside its qualified form."""
        table = self.db.get(name)
        scope = Scope()
        scope.add_table(table.name, table.columns)
        if where is not None and collect_aggregates(where, []):
            raise SqlError("WHERE cannot use an aggregate")
        matches = []
        for row in table.rows:
            qualified = {f"{table.name}.{c}": row[c] for c in table.columns}
            if where is None or _truthy(evaluate(where, qualified, scope)):
                matches.append((row, qualified))
        return table, scope, matches

    def _update(self, update: Update) -> Result:
        table, scope, matches = self._single_table(update.table, update.where)
        targets = [(self._column_name(table, name), expr) for name, expr in update.assignments]
        if len({column for column, _ in targets}) != len(targets):
            raise SqlError("UPDATE sets the same column twice")
        for _, expr in targets:
            if collect_aggregates(expr, []):
                raise SqlError("SET cannot use an aggregate")

        # Every SET expression sees the row as it was before this statement.
        changes = [
            (row, {column: self._coerce(table, column, evaluate(expr, qualified, scope)) for column, expr in targets})
            for row, qualified in matches
        ]
        for row, new_values in changes:
            row.update(new_values)
        if changes:
            self.db.changed.add(table.name.lower())
        return Result(["updated"], [[len(changes)]])

    def _delete(self, delete: Delete) -> Result:
        table, _, matches = self._single_table(delete.table, delete.where)
        doomed = {id(row) for row, _ in matches}
        table.rows[:] = [row for row in table.rows if id(row) not in doomed]
        if doomed:
            self.db.changed.add(table.name.lower())
        return Result(["deleted"], [[len(doomed)]])
