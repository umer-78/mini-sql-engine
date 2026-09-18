import pytest

from minisql import Database, Engine, parse
from minisql.tokens import SqlError

PEOPLE = """id,name,city,age,score
1,Ayesha,Lahore,34,88.5
2,Bilal,Karachi,28,71
3,Hamza,Lahore,45,
4,Sana,,19,95
5,Noor,Karachi,52,62.5
"""

PETS = """id,owner_id,name,kind
1,1,Simba,cat
2,1,Rocky,dog
3,2,Pixel,cat
4,5,Mango,parrot
"""


@pytest.fixture()
def run(tmp_path):
    (tmp_path / "people.csv").write_text(PEOPLE, encoding="utf-8")
    (tmp_path / "pets.csv").write_text(PETS, encoding="utf-8")
    engine = Engine(Database.from_directory(tmp_path))

    def execute(sql: str):
        return engine.execute(parse(sql))

    return execute


def one(result):
    """The single value of a one-row, one-column result."""
    assert len(result.rows) == 1 and len(result.columns) == 1
    return result.rows[0][0]


def column(result, name):
    return [row[result.columns.index(name)] for row in result.rows]


# -- projection ---------------------------------------------------------------

def test_star_returns_every_column_with_bare_names(run):
    result = run("SELECT * FROM people")
    assert result.columns == ["id", "name", "city", "age", "score"]
    assert len(result.rows) == 5


def test_named_columns_come_back_in_the_order_asked_for(run):
    result = run("SELECT name, id FROM people")
    assert result.columns == ["name", "id"]
    assert result.rows[0] == ["Ayesha", 1]


def test_an_expression_without_an_alias_is_labelled_by_position(run):
    assert run("SELECT age * 2 FROM people").columns == ["column1"]
    assert run("SELECT age * 2 AS doubled FROM people").columns == ["doubled"]


def test_types_are_inferred_per_column(run):
    result = run("SELECT id, score, name FROM people LIMIT 1")
    assert isinstance(result.rows[0][0], int)
    assert isinstance(result.rows[0][1], float)
    assert isinstance(result.rows[0][2], str)


def test_an_empty_cell_becomes_null(run):
    assert run("SELECT score FROM people WHERE id = 3").rows[0][0] is None
    assert run("SELECT city FROM people WHERE id = 4").rows[0][0] is None


# -- WHERE and NULL -----------------------------------------------------------

def test_where_keeps_only_rows_the_condition_is_true_for(run):
    assert column(run("SELECT name FROM people WHERE age > 30"), "name") == ["Ayesha", "Hamza", "Noor"]


def test_a_null_comparison_is_unknown_so_the_row_is_dropped(run):
    # id 3 has no score. Neither `score > 0` nor `score <= 0` may return it.
    assert len(run("SELECT id FROM people WHERE score > 0").rows) == 4
    assert len(run("SELECT id FROM people WHERE score <= 0").rows) == 0


def test_is_null_is_the_way_to_find_missing_values(run):
    assert one(run("SELECT COUNT(*) FROM people WHERE score IS NULL")) == 1
    assert one(run("SELECT COUNT(*) FROM people WHERE score IS NOT NULL")) == 4


def test_false_and_unknown_is_false_not_unknown(run):
    # age = 99 is false for every row, so no row survives whatever score holds.
    assert run("SELECT id FROM people WHERE age = 99 AND score > 0").rows == []


def test_true_or_unknown_is_true(run):
    assert len(run("SELECT id FROM people WHERE age > 0 OR score > 1000").rows) == 5


def test_in_and_not_in(run):
    assert column(run("SELECT name FROM people WHERE city IN ('Lahore')"), "name") == ["Ayesha", "Hamza"]
    assert column(run("SELECT name FROM people WHERE city NOT IN ('Lahore')"), "name") == ["Bilal", "Noor"]


def test_like_is_case_insensitive_and_understands_percent_and_underscore(run):
    assert column(run("SELECT name FROM people WHERE name LIKE 'a%'"), "name") == ["Ayesha"]
    assert column(run("SELECT name FROM people WHERE name LIKE '_ana'"), "name") == ["Sana"]
    assert len(run("SELECT name FROM people WHERE name NOT LIKE '%a%'").rows) == 1


def test_not_negates_a_whole_condition(run):
    assert column(run("SELECT name FROM people WHERE NOT (age > 30)"), "name") == ["Bilal", "Sana"]


def test_division_by_zero_gives_null_rather_than_crashing(run):
    assert one(run("SELECT age / 0 FROM people LIMIT 1")) is None


def test_arithmetic_on_text_is_refused_with_a_useful_message(run):
    with pytest.raises(SqlError, match="cannot apply"):
        run("SELECT name * 2 FROM people")


# -- aggregates ---------------------------------------------------------------

def test_count_star_counts_rows_and_count_column_skips_nulls(run):
    assert one(run("SELECT COUNT(*) FROM people")) == 5
    assert one(run("SELECT COUNT(score) FROM people")) == 4


def test_sum_avg_min_max_ignore_nulls(run):
    assert one(run("SELECT SUM(score) FROM people")) == pytest.approx(317.0)
    assert one(run("SELECT AVG(score) FROM people")) == pytest.approx(79.25)
    assert one(run("SELECT MIN(score) FROM people")) == pytest.approx(62.5)
    assert one(run("SELECT MAX(score) FROM people")) == pytest.approx(95.0)


def test_count_distinct(run):
    assert one(run("SELECT COUNT(DISTINCT city) FROM people")) == 2


def test_an_aggregate_over_no_rows_is_zero_for_count_and_null_for_the_rest(run):
    assert one(run("SELECT COUNT(*) FROM people WHERE age > 200")) == 0
    assert one(run("SELECT AVG(score) FROM people WHERE age > 200")) is None


def test_group_by_splits_the_rows(run):
    result = run("SELECT city, COUNT(*) AS n FROM people GROUP BY city ORDER BY city")
    assert result.rows == [["Karachi", 2], ["Lahore", 2], [None, 1]]


def test_having_filters_groups_not_rows(run):
    result = run("SELECT city, COUNT(*) n FROM people GROUP BY city HAVING COUNT(*) > 1 ORDER BY city")
    assert column(result, "city") == ["Karachi", "Lahore"]


def test_selecting_an_ungrouped_column_is_refused_with_advice(run):
    with pytest.raises(SqlError, match="not in GROUP BY"):
        run("SELECT city, name, COUNT(*) FROM people GROUP BY city")


def test_an_aggregate_in_where_is_refused_and_points_at_having(run):
    with pytest.raises(SqlError, match="use HAVING"):
        run("SELECT city FROM people WHERE COUNT(*) > 1")


# -- joins --------------------------------------------------------------------

def test_inner_join_keeps_only_matching_rows(run):
    result = run("SELECT p.name, pets.name AS pet FROM people p JOIN pets ON pets.owner_id = p.id ORDER BY pet")
    assert column(result, "pet") == ["Mango", "Pixel", "Rocky", "Simba"]
    assert len(result.rows) == 4


def test_left_join_keeps_unmatched_rows_with_nulls(run):
    result = run(
        "SELECT p.name, pets.name AS pet FROM people p "
        "LEFT JOIN pets ON pets.owner_id = p.id WHERE pets.id IS NULL ORDER BY p.name"
    )
    assert column(result, "p.name") == ["Hamza", "Sana"]
    assert column(result, "pet") == [None, None]


def test_an_ambiguous_bare_column_across_joined_tables_is_reported(run):
    with pytest.raises(SqlError, match="ambiguous"):
        run("SELECT name FROM people JOIN pets ON pets.owner_id = people.id")


def test_qualifying_the_column_resolves_the_ambiguity(run):
    result = run("SELECT people.name FROM people JOIN pets ON pets.owner_id = people.id")
    assert len(result.rows) == 4


def test_table_star_selects_one_side_of_a_join(run):
    result = run("SELECT pets.* FROM people JOIN pets ON pets.owner_id = people.id")
    assert result.columns == ["pets.id", "pets.owner_id", "pets.name", "pets.kind"]


def test_aggregating_over_a_join(run):
    result = run(
        "SELECT p.name, COUNT(pets.id) AS pets FROM people p "
        "LEFT JOIN pets ON pets.owner_id = p.id GROUP BY p.name ORDER BY pets DESC, p.name"
    )
    assert result.rows[0] == ["Ayesha", 2]
    assert result.rows[-1] == ["Sana", 0]


# -- ordering, distinct, limit -------------------------------------------------

def test_order_by_ascending_then_descending(run):
    assert column(run("SELECT name FROM people ORDER BY age"), "name")[0] == "Sana"
    assert column(run("SELECT name FROM people ORDER BY age DESC"), "name")[0] == "Noor"


def test_nulls_sort_last_in_ascending_order(run):
    assert column(run("SELECT score FROM people ORDER BY score"), "score")[-1] is None


def test_order_by_more_than_one_column_is_stable_in_the_order_given(run):
    result = run("SELECT city, age FROM people ORDER BY city, age DESC")
    assert result.rows[:2] == [["Karachi", 52], ["Karachi", 28]]


def test_order_by_can_use_an_output_alias(run):
    result = run("SELECT name, age * 2 AS doubled FROM people ORDER BY doubled DESC LIMIT 1")
    assert result.rows[0] == ["Noor", 104]


def test_distinct_removes_repeats_and_keeps_the_first(run):
    result = run("SELECT DISTINCT city FROM people ORDER BY city")
    assert result.rows == [["Karachi"], ["Lahore"], [None]]


def test_limit_and_offset_page_through_the_rows(run):
    assert column(run("SELECT name FROM people ORDER BY id LIMIT 2"), "name") == ["Ayesha", "Bilal"]
    assert column(run("SELECT name FROM people ORDER BY id LIMIT 2 OFFSET 2"), "name") == ["Hamza", "Sana"]
    assert run("SELECT name FROM people ORDER BY id LIMIT 0").rows == []


# -- errors -------------------------------------------------------------------

def test_an_unknown_table_lists_the_ones_that_exist(run):
    with pytest.raises(SqlError) as error:
        run("SELECT * FROM invoices")
    assert "people" in str(error.value) and "pets" in str(error.value)


def test_an_unknown_column_lists_the_ones_that_exist(run):
    with pytest.raises(SqlError, match="no column 'nickname'"):
        run("SELECT nickname FROM people")


def test_an_unknown_qualified_column_is_reported(run):
    with pytest.raises(SqlError, match="no column"):
        run("SELECT people.nickname FROM people")
