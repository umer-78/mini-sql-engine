import pytest

from minisql import parse
from minisql.ast import Aggregate, Binary, Column, InList, IsNull, Like, Literal, Unary
from minisql.tokens import SqlError


def test_select_star_from_one_table():
    query = parse("SELECT * FROM customers")
    assert query.items[0].is_star
    assert query.source.name == "customers"
    assert query.source.alias is None


def test_table_and_column_aliases_both_forms():
    explicit = parse("SELECT name AS who FROM customers AS c")
    implicit = parse("SELECT name who FROM customers c")
    assert explicit.items[0].alias == "who" == implicit.items[0].alias
    assert explicit.source.alias == "c" == implicit.source.alias


def test_and_binds_tighter_than_or():
    query = parse("SELECT * FROM t WHERE a = 1 OR b = 2 AND c = 3")
    assert query.where.op == "or"
    assert query.where.right.op == "and"


def test_multiplication_binds_tighter_than_addition():
    query = parse("SELECT a + b * c FROM t")
    expr = query.items[0].expr
    assert expr.op == "+"
    assert expr.right.op == "*"


def test_parentheses_override_precedence():
    query = parse("SELECT (a + b) * c FROM t")
    assert query.items[0].expr.op == "*"
    assert query.items[0].expr.left.op == "+"


def test_comparison_operators_are_normalised():
    assert parse("SELECT * FROM t WHERE a != 1").where.op == "<>"
    assert parse("SELECT * FROM t WHERE a <> 1").where.op == "<>"


def test_not_in_and_not_like_attach_to_the_right_node():
    not_in = parse("SELECT * FROM t WHERE city NOT IN ('a', 'b')").where
    assert isinstance(not_in, InList) and not_in.negated and len(not_in.items) == 2

    not_like = parse("SELECT * FROM t WHERE name NOT LIKE 'A%'").where
    assert isinstance(not_like, Like) and not_like.negated


def test_is_null_and_is_not_null():
    assert isinstance(parse("SELECT * FROM t WHERE a IS NULL").where, IsNull)
    assert parse("SELECT * FROM t WHERE a IS NOT NULL").where.negated is True


def test_count_star_has_no_argument_but_other_aggregates_do():
    star = parse("SELECT COUNT(*) FROM t").items[0].expr
    summed = parse("SELECT SUM(total) FROM t").items[0].expr
    assert isinstance(star, Aggregate) and star.arg is None
    assert isinstance(summed, Aggregate) and isinstance(summed.arg, Column)


def test_count_distinct_is_kept():
    assert parse("SELECT COUNT(DISTINCT city) FROM t").items[0].expr.distinct is True


def test_joins_carry_their_kind_and_condition():
    query = parse("SELECT * FROM a JOIN b ON b.id = a.id LEFT JOIN c ON c.id = a.id")
    assert [j.kind for j in query.joins] == ["inner", "left"]
    assert isinstance(query.joins[0].on, Binary)


def test_order_by_defaults_to_ascending():
    query = parse("SELECT * FROM t ORDER BY a, b DESC, c ASC")
    assert [o.descending for o in query.order_by] == [False, True, False]


def test_limit_and_offset():
    query = parse("SELECT * FROM t LIMIT 10 OFFSET 20")
    assert (query.limit, query.offset) == (10, 20)


def test_negative_numbers_parse_as_a_unary_minus():
    assert isinstance(parse("SELECT -a FROM t").items[0].expr, Unary)


def test_literals_keep_their_python_types():
    items = parse("SELECT 1, 2.5, 'x', NULL, true FROM t").items
    assert [i.expr.value for i in items] == [1, 2.5, "x", None, True]
    assert isinstance(items[0].expr, Literal)


def test_having_without_group_by_is_refused():
    with pytest.raises(SqlError, match="HAVING needs a GROUP BY"):
        parse("SELECT COUNT(*) FROM t HAVING COUNT(*) > 1")


def test_a_missing_from_is_reported_with_the_position():
    with pytest.raises(SqlError) as error:
        parse("SELECT a, b customers")
    assert "expected 'from'" in str(error.value)
    assert "^" in str(error.value)


def test_trailing_junk_is_reported():
    with pytest.raises(SqlError, match="after the end of the query"):
        parse("SELECT * FROM t WHERE a = 1 nonsense nonsense")


def test_limit_must_be_a_whole_number():
    with pytest.raises(SqlError, match="LIMIT needs a whole number"):
        parse("SELECT * FROM t LIMIT 2.5")


def test_an_empty_query_says_what_was_expected():
    with pytest.raises(SqlError, match="expected SELECT, INSERT, UPDATE or DELETE"):
        parse("")
