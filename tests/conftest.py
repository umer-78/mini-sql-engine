import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from minisql import Database, Engine  # noqa: E402


@pytest.fixture(scope="session")
def database() -> Database:
    return Database.from_directory(ROOT / "data")


@pytest.fixture()
def engine(database: Database) -> Engine:
    return Engine(database)


@pytest.fixture()
def query(engine: Engine):
    from minisql import parse

    def run(sql: str):
        return engine.execute(parse(sql))

    return run
