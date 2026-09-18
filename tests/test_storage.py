import pytest

from minisql.storage import Database, Table, convert, infer_column_type
from minisql.tokens import SqlError


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["1", "2", "3"], "int"),
        (["1", "", "3"], "int"),
        (["-4", "+5"], "int"),
        (["1.5", "2"], "float"),
        (["0.5"], "float"),
        (["a", "1"], "str"),
        ([], "str"),
        (["", ""], "str"),
        (["04001", "04002"], "str"),
        (["0", "1"], "int"),
    ],
)
def test_column_types_are_inferred_from_every_value(values, expected):
    assert infer_column_type(values) == expected


def test_a_leading_zero_keeps_a_column_as_text():
    # A postcode is not a number: 04001 must not come back as 4001.
    assert infer_column_type(["04001"]) == "str"
    assert convert("04001", "str") == "04001"


def test_an_empty_cell_is_null_whatever_the_column_type():
    assert convert("", "int") is None
    assert convert("", "str") is None


def test_loading_a_csv_reads_the_header_as_columns(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("id,name\n1,Ayesha\n2,Bilal\n", encoding="utf-8")

    table = Table.from_csv(path)

    assert table.name == "t"
    assert table.columns == ["id", "name"]
    assert table.types == {"id": "int", "name": "str"}
    assert len(table) == 2


def test_a_short_row_is_padded_with_nulls(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("a,b,c\n1,2\n", encoding="utf-8")

    assert Table.from_csv(path).rows[0] == {"a": 1, "b": 2, "c": None}


def test_an_empty_file_is_reported_clearly(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    with pytest.raises(SqlError, match="needs a header row"):
        Table.from_csv(path)


def test_duplicate_column_names_are_refused(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("id,id\n1,2\n", encoding="utf-8")

    with pytest.raises(SqlError, match="duplicate column names"):
        Table.from_csv(path)


def test_a_directory_with_no_csv_files_is_reported(tmp_path):
    with pytest.raises(SqlError, match="no .csv files"):
        Database.from_directory(tmp_path)


def test_a_missing_directory_is_reported(tmp_path):
    with pytest.raises(SqlError, match="not a directory"):
        Database.from_directory(tmp_path / "nope")


def test_tables_are_found_whatever_the_case(tmp_path):
    (tmp_path / "People.csv").write_text("id\n1\n", encoding="utf-8")
    database = Database.from_directory(tmp_path)

    assert database.get("people").name == "People"
    assert "PEOPLE" in database
