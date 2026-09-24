"""A small SQL engine that runs queries over CSV files."""

from .ast import Delete, Insert, Select, Statement, Union, Update
from .executor import Engine, Result
from .parser import parse
from .storage import Database, Table
from .tokens import SqlError, tokenize

__all__ = [
    "Database", "Delete", "Engine", "Insert", "Result", "Select", "SqlError", "Statement", "Table", "Union", "Update",
    "parse", "run", "tokenize",
]
__version__ = "1.1.0"


def run(sql: str, database: Database) -> Result:
    """Parse and execute one statement."""
    return Engine(database).execute(parse(sql))
