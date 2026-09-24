"""INSERT, UPDATE, DELETE, UNION and CASE, each against a throwaway copy of a table."""

import pytest

from minisql import Database, Engine, parse
from minisql.tokens import SqlError

PEOPLE = """id,name,city,age,score
1,Ayesha,Lahore,34,88.5
2,Bilal,Karachi,28,71.0
3,Hamza,Lahore,45,
4,Sana,,19,95.0
"""

STAFF = """id,name,city
10,Zara,Lahore
11,Bilal,Karachi
"""


@pytest.fixture()
def db(tmp_path):
    (tmp_path / "people.csv").write_text(PEOPLE, encoding="utf-8")
    (tmp_path / "staff.csv").write_text(STAFF, encoding="utf-8")
    (tmp_path / "empty.csv").write_text("id,label\n", encoding="utf-8")
    database = Database.from_directory(tmp_path)
    database.path = tmp_path
    return database


@pytest.fixture()
def run(db):
    engine = Engine(db)
    return lambda sql: engine.execute(parse(sql))


def values(result):
    return [row[0] for row in result.rows]


# -- INSERT ---------------------------------------------------------------

def test_insert_named_columns_leaves_the_rest_null(run):
    assert run("INSERT INTO people (id, name) VALUES (5, 'Noor')").rows == [[1]]
    row = run("SELECT city, age FROM people WHERE id = 5").rows
    assert row == [[None, None]]


def test_insert_several_rows_in_table_order(run):
    assert run("INSERT INTO people VALUES (5, 'Noor', 'Quetta', 52, 62.5), (6, 'Omar', NULL, 1 + 1, 3)").rows == [[2]]
    assert run("SELECT age, score FROM people WHERE id = 6").rows == [[2, 3.0]]  # 3 widened to the float column
    assert run("SELECT COUNT(*) FROM people").rows == [[6]]


def test_insert_from_select(run):
    run("INSERT INTO people (id, name, city) SELECT id, name, city FROM staff WHERE city = 'Lahore'")
    assert values(run("SELECT name FROM people WHERE id = 10")) == ["Zara"]


def test_insert_rejects_the_wrong_type_and_writes_nothing(run):
    with pytest.raises(SqlError, match="holds whole numbers"):
        run("INSERT INTO people (id, name) VALUES (7, 'Ok'), ('eight', 'Bad')")
    assert run("SELECT COUNT(*) FROM people").rows == [[4]]  # the valid first row was not kept either


def test_insert_number_into_text_column_suggests_quotes(run):
    with pytest.raises(SqlError, match="put it in quotes"):
        run("INSERT INTO people (id, name) VALUES (7, 42)")


def test_insert_checks_counts_and_names(run):
    with pytest.raises(SqlError, match="has 2 value"):
        run("INSERT INTO people (id) VALUES (7, 'x')")
    with pytest.raises(SqlError, match="no column 'nickname'"):
        run("INSERT INTO people (id, nickname) VALUES (7, 'x')")
    with pytest.raises(SqlError, match="same column twice"):
        run("INSERT INTO people (id, id) VALUES (7, 8)")
    with pytest.raises(SqlError, match="no column 'age'"):
        run("INSERT INTO people (id) VALUES (age)")  # VALUES has no row to read from


def test_an_empty_table_takes_the_type_of_its_first_value(run, db):
    run("INSERT INTO empty VALUES (1, 'first')")
    assert db.get("empty").types == {"id": "int", "label": "str"}
    with pytest.raises(SqlError):
        run("INSERT INTO empty VALUES ('two', 'second')")


# -- UPDATE ---------------------------------------------------------------

def test_update_with_where_and_expression(run):
    assert run("UPDATE people SET age = age + 1 WHERE city = 'Lahore'").rows == [[2]]
    assert values(run("SELECT age FROM people ORDER BY id")) == [35, 28, 46, 19]


def test_update_sees_old_values_in_every_set(run):
    run("UPDATE people SET name = city, city = name WHERE id = 1")  # a swap needs the pre-update row
    assert run("SELECT name, city FROM people WHERE id = 1").rows == [["Lahore", "Ayesha"]]


def test_update_type_error_is_atomic(run):
    with pytest.raises(SqlError, match="does not fit"):
        run("UPDATE people SET age = score")  # 88.5 is not a whole number
    assert values(run("SELECT age FROM people ORDER BY id")) == [34, 28, 45, 19]


def test_update_where_unknown_touches_nothing(run):
    assert run("UPDATE people SET name = 'x' WHERE city = NULL").rows == [[0]]


def test_update_can_set_null_and_use_case(run):
    run("UPDATE people SET city = CASE WHEN city IS NULL THEN 'Unknown' ELSE city END")
    assert values(run("SELECT city FROM people WHERE id = 4")) == ["Unknown"]
    run("UPDATE people SET score = NULL WHERE id = 1")
    assert values(run("SELECT score FROM people WHERE id = 1")) == [None]


# -- DELETE ---------------------------------------------------------------

def test_delete_with_where(run):
    assert run("DELETE FROM people WHERE age < 30").rows == [[2]]
    assert values(run("SELECT name FROM people ORDER BY id")) == ["Ayesha", "Hamza"]


def test_delete_everything(run):
    assert run("DELETE FROM staff").rows == [[2]]
    assert run("SELECT COUNT(*) FROM staff").rows == [[0]]


def test_aggregates_are_rejected_in_writes(run):
    with pytest.raises(SqlError, match="aggregate"):
        run("DELETE FROM people WHERE COUNT(*) > 1")
    with pytest.raises(SqlError, match="aggregate"):
        run("UPDATE people SET age = MAX(age)")


# -- saving ----------------------------------------------------------------

def test_changes_are_saved_back_to_csv_and_read_the_same(run, db):
    run("INSERT INTO people VALUES (5, 'O''Neil, Jr', NULL, 60, 70.0)")
    run("DELETE FROM staff WHERE id = 10")
    assert db.save(db.path) == ["people", "staff"]
    again = Database.from_directory(db.path)
    assert again.get("people").types == db.get("people").types
    assert again.get("people").rows == db.get("people").rows
    assert len(again.get("staff").rows) == 1
    assert db.changed == set()


# -- UNION -----------------------------------------------------------------

def test_union_removes_duplicates_union_all_keeps_them(run):
    union = run("SELECT name FROM people UNION SELECT name FROM staff")
    assert sorted(values(union)) == ["Ayesha", "Bilal", "Hamza", "Sana", "Zara"]
    everything = run("SELECT name FROM people UNION ALL SELECT name FROM staff")
    assert len(everything.rows) == 6


def test_union_order_and_limit_apply_to_the_whole_result(run):
    result = run("SELECT name, city FROM people UNION SELECT name, city FROM staff ORDER BY name DESC LIMIT 2")
    assert result.columns == ["name", "city"]
    assert values(result) == ["Zara", "Sana"]
    by_position = run("SELECT id FROM people UNION ALL SELECT id FROM staff ORDER BY 1 DESC LIMIT 1")
    assert values(by_position) == [11]


def test_union_checks_column_counts_and_order_names(run):
    with pytest.raises(SqlError, match="returns 2 column"):
        run("SELECT name FROM people UNION SELECT name, city FROM staff")
    with pytest.raises(SqlError, match="must name an output column"):
        run("SELECT name FROM people UNION SELECT name FROM staff ORDER BY age")


# -- CASE ------------------------------------------------------------------

def test_searched_case_with_else(run):
    result = run("SELECT name, CASE WHEN age >= 40 THEN 'senior' WHEN age >= 25 THEN 'mid' ELSE 'junior' END AS band FROM people ORDER BY id")
    assert [row[1] for row in result.rows] == ["mid", "mid", "senior", "junior"]


def test_simple_case_and_null_never_matches(run):
    result = run("SELECT CASE city WHEN 'Lahore' THEN 1 WHEN NULL THEN 2 END FROM people ORDER BY id")
    assert values(result) == [1, None, 1, None]


def test_case_inside_an_aggregate(run):
    result = run("SELECT SUM(CASE WHEN city = 'Lahore' THEN 1 ELSE 0 END) AS lahore FROM people")
    assert result.rows == [[2]]


def test_case_needs_a_when(run):
    with pytest.raises(SqlError, match="at least one WHEN"):
        run("SELECT CASE ELSE 1 END FROM people")


def test_saving_keeps_the_files_line_endings(tmp_path):
    (tmp_path / "t.csv").write_bytes(b'id,name\r\n1,"say ""hi"""\r\n')
    database = Database.from_directory(tmp_path)
    Engine(database).execute(parse("INSERT INTO t VALUES (2, 'b')"))
    database.save(tmp_path)
    assert (tmp_path / "t.csv").read_bytes() == b'id,name\r\n1,"say ""hi"""\r\n2,b\r\n'
