from sync.diff import find_new_products


def test_no_new_products_when_all_ids_already_exist():
    products = [
        {"id": 101, "name": "Product A"},
        {"id": 102, "name": "Product B"},
    ]
    existing_ids = {"101", "102"}

    result = find_new_products(products, existing_ids)

    assert result == []


def test_all_products_are_new_when_none_exist():
    products = [
        {"id": 201, "name": "Product C"},
        {"id": 202, "name": "Product D"},
    ]
    existing_ids = set()

    result = find_new_products(products, existing_ids)

    assert result == products


def test_returns_only_the_products_not_already_in_existing_ids():
    products = [
        {"id": 301, "name": "Product E"},
        {"id": 302, "name": "Product F"},
        {"id": 303, "name": "Product G"},
    ]
    existing_ids = {"301", "303"}

    result = find_new_products(products, existing_ids)

    assert result == [{"id": 302, "name": "Product F"}]


def test_normalizes_int_product_ids_against_string_existing_ids():
    """WooCommerce returns `id` as int; gspread reads sheet IDs back as str.

    A naive `product["id"] not in existing_ids` breaks silently across this
    type boundary (int 101 is not `in` a set of {"101"}), incorrectly
    re-adding products that already exist in the sheet. The function must
    normalize both sides (e.g. via str()) before comparing.
    """
    products = [
        {"id": 101, "name": "Product A"},
        {"id": 999, "name": "Brand New Product"},
    ]
    existing_ids = {"101", "202"}

    result = find_new_products(products, existing_ids)

    assert result == [{"id": 999, "name": "Brand New Product"}]
