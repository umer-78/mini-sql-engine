import pytest

from minisql.cli import main, split_statements
from minisql.executor import Result
from minisql.format import as_csv, as_json, as_table, render


@pytest.fixture()
def data_dir(tmp_path):
    (tmp_path / "people.csv").write_text("id,name,score\n1,Ayesha,88.5\n2,Bilal,\n", encoding="utf-8")
    return str(tmp_path)


def test_one_query_prints_a_table_and_exits_zero(data_dir, capsys):
    assert main([data_dir, "-c", "SELECT name FROM people ORDER BY id"]) == 0

    out = capsys.readouterr().out
    assert "Ayesha" in out and "Bilal" in out
    assert "2 rows" in out


def test_csv_output(data_dir, capsys):
    main([data_dir, "-c", "SELECT id, name FROM people ORDER BY id", "--format", "csv"])

    assert capsys.readouterr().out.strip().splitlines() == ["id,name", "1,Ayesha", "2,Bilal"]


def test_json_output_is_a_list_of_objects(data_dir, capsys):
    import json

    main([data_dir, "-c", "SELECT id, score FROM people ORDER BY id", "--format", "json"])

    assert json.loads(capsys.readouterr().out) == [{"id": 1, "score": 88.5}, {"id": 2, "score": None}]


def test_a_bad_query_exits_one_and_explains_on_stderr(data_dir, capsys):
    assert main([data_dir, "-c", "SELECT FROM"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err


def test_a_missing_directory_exits_two(tmp_path, capsys):
    assert main([str(tmp_path / "nope"), "-c", "SELECT 1 FROM t"]) == 2
    assert "error:" in capsys.readouterr().err


def test_a_sql_file_runs_every_statement(data_dir, tmp_path, capsys):
    script = tmp_path / "queries.sql"
    script.write_text(
        "SELECT COUNT(*) AS n FROM people;\nSELECT name FROM people WHERE id = 1;\n",
        encoding="utf-8",
    )

    assert main([data_dir, "-f", str(script)]) == 0

    out = capsys.readouterr().out
    assert "n" in out and "Ayesha" in out


def test_statements_split_on_semicolons_outside_strings():
    assert split_statements("SELECT 1; SELECT 2") == ["SELECT 1", "SELECT 2"]
    assert split_statements("SELECT ';' FROM t") == ["SELECT ';' FROM t"]
    assert split_statements("  ;;  ") == []


def test_null_renders_as_the_word_null_not_as_none():
    assert render(None) == "NULL"
    assert render(True) == "true"
    assert render(12.0) == "12"
    assert render(12.5) == "12.5"


def test_a_long_cell_is_clipped_rather_than_breaking_the_table():
    result = Result(["note"], [["x" * 100]])

    line = as_table(result, max_width=20).splitlines()[3]
    assert "…" in line
    assert len(line) <= 26


def test_an_empty_result_still_prints_its_header():
    text = as_table(Result(["id", "name"], []))

    assert "id" in text and "name" in text
    assert "0 rows" in text


def test_one_row_is_not_pluralised():
    assert as_table(Result(["id"], [[1]])).endswith("1 row")


def test_csv_writes_an_empty_field_for_null():
    assert as_csv(Result(["a", "b"], [[1, None]])) == "a,b\n1,\n"


def test_json_is_indented_and_keyed_by_column():
    assert '"a": 1' in as_json(Result(["a"], [[1]]))


def test_piped_input_runs_dot_commands_as_well_as_sql(data_dir, capsys, monkeypatch):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(".tables\nSELECT COUNT(*) AS n FROM people;\n"))

    assert main([data_dir]) == 0

    out = capsys.readouterr().out
    assert "people" in out          # from .tables
    assert "| n " in out            # the query's column header
    assert "| 2 " in out            # the COUNT(*)


def test_a_final_query_without_a_semicolon_still_runs(data_dir, capsys, monkeypatch):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("SELECT name FROM people WHERE id = 1"))

    assert main([data_dir]) == 0
    assert "Ayesha" in capsys.readouterr().out


def test_an_unknown_dot_command_is_reported(data_dir, capsys, monkeypatch):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(".nope\n"))

    main([data_dir])
    assert "unknown command" in capsys.readouterr().err


def test_the_format_dot_command_switches_output(data_dir, capsys, monkeypatch):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(".format csv\nSELECT id FROM people ORDER BY id;\n"))

    main([data_dir])
    assert capsys.readouterr().out.strip().splitlines() == ["id", "1", "2"]


def test_a_failed_query_from_piped_input_exits_one(data_dir, capsys, monkeypatch):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("SELECT nope FROM people;\n"))

    assert main([data_dir]) == 1


def test_writes_are_kept_only_with_save(tmp_path, capsys):
    from minisql.cli import main

    (tmp_path / "t.csv").write_text("id,name\n1,a\n", encoding="utf-8")
    assert main([str(tmp_path), "-c", "INSERT INTO t VALUES (2, 'b')"]) == 0
    assert "not saved" in capsys.readouterr().err
    assert (tmp_path / "t.csv").read_text(encoding="utf-8") == "id,name\n1,a\n"

    assert main([str(tmp_path), "--save", "-c", "INSERT INTO t VALUES (2, 'b')"]) == 0
    assert "saved t" in capsys.readouterr().err
    assert (tmp_path / "t.csv").read_text(encoding="utf-8") == "id,name\n1,a\n2,b\n"


def test_shell_save_command(tmp_path, monkeypatch, capsys):
    import io

    from minisql.cli import main

    (tmp_path / "t.csv").write_text("id,name\n1,a\n", encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO("DELETE FROM t WHERE id = 1;\n.save\n"))
    assert main([str(tmp_path)]) == 0
    assert "saved t" in capsys.readouterr().err
    assert (tmp_path / "t.csv").read_text(encoding="utf-8") == "id,name\n"
