"""Turns a Result into something readable in a terminal, or into CSV/JSON."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from .executor import Result


def render(value: Any) -> str:
    if value is None:
        return "NULL"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float):
        # Trim 12.0 to 12 but leave 12.5 alone, so money columns stay readable.
        return f"{value:.10g}"
    return str(value)


def as_table(result: Result, max_width: int = 40) -> str:
    if not result.columns:
        return "(no columns)"

    cells = [[render(v) for v in row] for row in result.rows]
    clipped = [
        [c if len(c) <= max_width else c[: max_width - 1] + "…" for c in row] for row in cells
    ]
    widths = [
        max(len(column), *(len(row[i]) for row in clipped)) if clipped else len(column)
        for i, column in enumerate(result.columns)
    ]

    line = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [line, "| " + " | ".join(c.ljust(w) for c, w in zip(result.columns, widths, strict=False)) + " |", line]
    out += ["| " + " | ".join(c.ljust(w) for c, w in zip(row, widths, strict=False)) + " |" for row in clipped]
    out.append(line)
    out.append(f"{len(result.rows)} row" + ("" if len(result.rows) == 1 else "s"))
    return "\n".join(out)


def as_csv(result: Result) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(result.columns)
    writer.writerows([["" if v is None else v for v in row] for row in result.rows])
    return buffer.getvalue()


def as_json(result: Result) -> str:
    return json.dumps(result.dicts(), indent=2, ensure_ascii=False, default=str)
