"""A small SQL engine that runs queries over CSV files."""

from .ast import Select
from .executor import Engine, Result
from .parser import parse
from .storage import Database, Table
from .tokens import SqlError, tokenize

__all__ = ["Database", "Engine", "Result", "Select", "SqlError", "Table", "parse", "run", "tokenize"]
__version__ = "1.0.0"


def run(sql: str, database: Database) -> Result:
    """Parse and execute one query."""
    return Engine(database).execute(parse(sql))
