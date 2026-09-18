"""Checks the shipped sample data, so the README's numbers stay true."""


def test_the_four_tables_are_loaded(database):
    assert sorted(database.tables) == ["customers", "order_items", "orders", "products"]


def test_row_counts(database):
    assert len(database.get("customers")) == 25
    assert len(database.get("products")) == 15
    assert len(database.get("orders")) == 60
    assert len(database.get("order_items")) == 153


def test_prices_and_quantities_are_numeric(database):
    assert database.get("products").types["price"] == "int"
    assert database.get("order_items").types["quantity"] == "int"


def test_cancelled_orders_have_no_shipping_date(query):
    result = query(
        "SELECT COUNT(*) FROM orders WHERE status = 'cancelled' AND shipped_on IS NOT NULL"
    )
    assert result.rows[0][0] == 0


def test_every_order_belongs_to_a_customer_that_exists(query):
    orphans = query(
        "SELECT COUNT(*) FROM orders o LEFT JOIN customers c ON c.id = o.customer_id "
        "WHERE c.id IS NULL"
    )
    assert orphans.rows[0][0] == 0


def test_every_order_item_points_at_a_real_product(query):
    orphans = query(
        "SELECT COUNT(*) FROM order_items i LEFT JOIN products p ON p.id = i.product_id "
        "WHERE p.id IS NULL"
    )
    assert orphans.rows[0][0] == 0


def test_revenue_by_category_covers_every_category(query):
    result = query(
        "SELECT p.category, SUM(i.quantity * i.unit_price) AS revenue "
        "FROM order_items i JOIN products p ON p.id = i.product_id "
        "GROUP BY p.category ORDER BY revenue DESC"
    )
    assert len(result.rows) == 5
    revenues = [row[1] for row in result.rows]
    assert revenues == sorted(revenues, reverse=True)
    assert all(value > 0 for value in revenues)


def test_two_customers_have_no_recorded_city(query):
    assert query("SELECT COUNT(*) FROM customers WHERE city IS NULL").rows[0][0] == 2
