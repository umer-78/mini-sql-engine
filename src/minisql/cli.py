"""The `minisql` command: one query, a file of queries, or an interactive shell."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .executor import Engine, Result
from .format import as_csv, as_json, as_table
from .parser import parse
from .storage import Database
from .tokens import SqlError

DOT_HELP = """Shell commands:
  .tables            list the tables
  .schema [table]    show columns and inferred types
  .format table|csv|json
  .help              this text
  .quit              leave
Anything else is run as SQL. A query may span lines; finish it with ';'."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="minisql",
        description="Run SQL queries against a directory of CSV files.",
    )
    parser.add_argument("directory", help="directory holding the .csv files")
    parser.add_argument("-c", "--command", help="run one query and exit")
    parser.add_argument("-f", "--file", help="run every query in a .sql file and exit")
    parser.add_argument(
        "--format", choices=["table", "csv", "json"], default="table", help="output format"
    )
    parser.add_argument("--version", action="version", version=f"minisql {__version__}")
    return parser


def format_result(result: Result, style: str) -> str:
    return {"table": as_table, "csv": as_csv, "json": as_json}[style](result).rstrip("\n")


def run_sql(engine: Engine, sql: str, style: str, out) -> bool:
    """Runs one query. Returns False if it failed, having reported why."""
    try:
        print(format_result(engine.execute(parse(sql)), style), file=out)
    except SqlError as error:
        print(f"error: {error}", file=sys.stderr)
        return False
    return True


def split_statements(text: str) -> list[str]:
    """Splits on semicolons that are not inside a quoted string."""
    statements: list[str] = []
    current: list[str] = []
    in_string = False
    for char in text:
        if char == "'":
            in_string = not in_string
        if char == ";" and not in_string:
            statements.append("".join(current))
            current = []
            continue
        current.append(char)
    statements.append("".join(current))
    return [s.strip() for s in statements if s.strip()]


def shell(engine: Engine, database: Database, style: str, prompt: bool = True) -> int:
    """The read-run loop, used both interactively and for piped input.

    Piped input goes through the same loop rather than a separate code path, so
    `echo '.tables' | minisql data` behaves exactly like typing it.
    """
    if prompt:
        print(f"minisql {__version__} — {len(database.tables)} table(s) loaded. '.help' for help.")
    buffer: list[str] = []
    failed = False

    while True:
        try:
            line = input("... " if buffer else "sql> ") if prompt else input()
        except (EOFError, KeyboardInterrupt):
            if prompt:
                print()
            break

        stripped = line.strip()
        if not buffer and stripped.startswith("."):
            if stripped in {".quit", ".exit"}:
                return 0
            style = handle_dot(stripped, database, style)
            continue

        buffer.append(line)
        joined = "\n".join(buffer)
        if ";" not in joined and prompt:
            continue

        buffer = []
        for statement in split_statements(joined):
            failed = not run_sql(engine, statement, style, sys.stdout) or failed

    # A trailing query with no closing semicolon still runs.
    for statement in split_statements("\n".join(buffer)):
        failed = not run_sql(engine, statement, style, sys.stdout) or failed

    return 1 if failed else 0


def handle_dot(command: str, database: Database, style: str) -> str:
    parts = command.split()

    if parts[0] == ".tables":
        for name in sorted(database.tables):
            table = database.tables[name]
            print(f"  {table.name:<14} {len(table.rows):>5} rows  {len(table.columns)} columns")
    elif parts[0] == ".schema":
        names = [parts[1]] if len(parts) > 1 else sorted(database.tables)
        for name in names:
            try:
                table = database.get(name)
            except SqlError as error:
                print(f"error: {error}", file=sys.stderr)
                continue
            print(f"  {table.name}")
            for column in table.columns:
                print(f"    {column:<16} {table.types[column]}")
    elif parts[0] == ".format" and len(parts) > 1 and parts[1] in {"table", "csv", "json"}:
        return parts[1]
    elif parts[0] == ".help":
        print(DOT_HELP)
    else:
        print(f"unknown command {parts[0]!r} — try .help", file=sys.stderr)

    return style


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        database = Database.from_directory(args.directory)
    except SqlError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    engine = Engine(database)

    if args.command:
        return 0 if run_sql(engine, args.command, args.format, sys.stdout) else 1

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
        ok = True
        for statement in split_statements(text):
            ok = run_sql(engine, statement, args.format, sys.stdout) and ok
            print()
        return 0 if ok else 1

    return shell(engine, database, args.format, prompt=sys.stdin.isatty())
