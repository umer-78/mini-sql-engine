import pytest

from minisql.tokens import Kind, SqlError, tokenize


def kinds(sql):
    return [t.kind for t in tokenize(sql)[:-1]]


def texts(sql):
    return [t.text for t in tokenize(sql)[:-1]]


def test_keywords_are_recognised_whatever_their_case():
    assert kinds("SELECT select SeLeCt") == [Kind.KEYWORD] * 3


def test_identifiers_keep_their_case():
    assert texts("SELECT CustomerId FROM Orders") == ["SELECT", "CustomerId", "FROM", "Orders"]


def test_qualified_names_stay_one_token():
    assert texts("o.customer_id") == ["o.customer_id"]


def test_two_character_operators_beat_one_character_ones():
    assert texts("a <= b and c <> d and e >= f") == ["a", "<=", "b", "and", "c", "<>", "d", "and", "e", ">=", "f"]


def test_strings_use_doubled_quotes_to_escape():
    tokens = tokenize("'it''s here'")
    assert tokens[0].kind is Kind.STRING
    assert tokens[0].text == "it's here"


def test_numbers_may_have_a_decimal_point():
    assert texts("1 2.5 .75") == ["1", "2.5", ".75"]


def test_comments_run_to_the_end_of_the_line():
    assert texts("SELECT 1 -- everything here is ignored\nFROM t") == ["SELECT", "1", "FROM", "t"]


def test_an_unterminated_string_points_at_where_it_opened():
    with pytest.raises(SqlError) as error:
        tokenize("SELECT 'oops FROM t")
    assert "unterminated string" in str(error.value)
    assert "^" in str(error.value)


def test_an_unexpected_character_is_named():
    with pytest.raises(SqlError, match="unexpected character"):
        tokenize("SELECT # FROM t")


def test_the_stream_always_ends_with_eof():
    assert tokenize("").pop().kind is Kind.EOF
