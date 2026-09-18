"""CSV files as tables.

Types are inferred per column, not per cell: a column is integer only if every
non-empty value in it is an integer. That is what stops a postcode column like
`04001` from being read as the number 4001 in some rows and a string in others.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .tokens import SqlError

Row = dict[str, Any]


def _is_int(text: str) -> bool:
    body = text[1:] if text[:1] in "+-" else text
    if not body.isdigit():
        return False
    # A leading zero means the zero is part of the value — a postcode or an
    # account number, not a number to do arithmetic with.
    return len(body) == 1 or not body.startswith("0")


def _is_float(text: str) -> bool:
    body = text[1:] if text[:1] in "+-" else text
    whole = body.split(".", 1)[0].split("e", 1)[0]
    if len(whole) > 1 and whole.startswith("0"):
        return False  # same reason as _is_int: 04.5 is a label, not a number
    try:
        float(text)
    except ValueError:
        return False
    return True


def infer_column_type(values: list[str]) -> str:
    """Returns 'int', 'float' or 'str' for a column's raw cell values."""
    present = [v for v in values if v != ""]
    if not present:
        return "str"
    if all(_is_int(v) for v in present):
        return "int"
    if all(_is_float(v) for v in present):
        return "float"
    return "str"


def convert(value: str, column_type: str) -> Any:
    if value == "":
        return None
    if column_type == "int":
        return int(value)
    if column_type == "float":
        return float(value)
    return value


@dataclass
class Table:
    name: str
    columns: list[str]
    types: dict[str, str]
    rows: list[Row]

    def __len__(self) -> int:
        return len(self.rows)

    @classmethod
    def from_csv(cls, path: Path, name: str | None = None) -> Table:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            try:
                header = next(reader)
            except StopIteration:
                raise SqlError(f"{path.name} is empty — a table needs a header row") from None
            raw = [row for row in reader if row]

        columns = [h.strip() for h in header]
        if len(set(columns)) != len(columns):
            raise SqlError(f"{path.name} has duplicate column names")

        cells = {
            column: [row[index] if index < len(row) else "" for row in raw]
            for index, column in enumerate(columns)
        }
        types = {column: infer_column_type(values) for column, values in cells.items()}
        rows = [
            {column: convert(cells[column][i], types[column]) for column in columns}
            for i in range(len(raw))
        ]
        return cls(name or path.stem, columns, types, rows)


@dataclass
class Database:
    tables: dict[str, Table]

    @classmethod
    def from_directory(cls, directory: str | Path) -> Database:
        path = Path(directory)
        if not path.is_dir():
            raise SqlError(f"{path} is not a directory")
        tables = {}
        for file in sorted(path.glob("*.csv")):
            table = Table.from_csv(file)
            tables[table.name.lower()] = table
        if not tables:
            raise SqlError(f"no .csv files in {path}")
        return cls(tables)

    def get(self, name: str) -> Table:
        table = self.tables.get(name.lower())
        if table is None:
            known = ", ".join(sorted(self.tables)) or "none"
            raise SqlError(f"no table named {name!r} (available: {known})")
        return table

    def __contains__(self, name: str) -> bool:
        return name.lower() in self.tables
