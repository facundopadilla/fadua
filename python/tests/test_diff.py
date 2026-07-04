from sync.diff import classify_products


def test_classify_returns_empty_when_nothing_new_or_changed():
    products = [
        {"id": 101, "name": "Product A", "price": "100", "image": "img-a.jpg"},
    ]
    existing_by_id = {
        "101": {"row": 2, "Producto": "Product A", "Precio": "100", "Imagen": "img-a.jpg"},
    }

    new, changed = classify_products(products, existing_by_id)

    assert new == []
    assert changed == []


def test_classify_returns_all_products_as_new_when_none_exist():
    products = [
        {"id": 201, "name": "Product C"},
        {"id": 202, "name": "Product D"},
    ]

    new, changed = classify_products(products, {})

    assert new == products
    assert changed == []


def test_classify_detects_price_change():
    products = [
        {"id": 301, "name": "MOBI", "price": "500", "image": "img.jpg"},
    ]
    existing_by_id = {
        "301": {"row": 5, "Producto": "MOBI", "Precio": "400", "Imagen": "img.jpg"},
    }

    new, changed = classify_products(products, existing_by_id)

    assert new == []
    assert changed == [
        {"product": products[0], "row": 5, "changes": {"Precio": ("400", "500")}}
    ]


def test_classify_detects_name_change():
    products = [
        {"id": 302, "name": "MOBI PRO", "price": "400", "image": "img.jpg"},
    ]
    existing_by_id = {
        "302": {"row": 6, "Producto": "MOBI", "Precio": "400", "Imagen": "img.jpg"},
    }

    new, changed = classify_products(products, existing_by_id)

    assert new == []
    assert changed == [
        {"product": products[0], "row": 6, "changes": {"Producto": ("MOBI", "MOBI PRO")}}
    ]


def test_classify_detects_image_change():
    products = [
        {"id": 303, "name": "MOBI", "price": "400", "image": "new.jpg"},
    ]
    existing_by_id = {
        "303": {"row": 7, "Producto": "MOBI", "Precio": "400", "Imagen": "old.jpg"},
    }

    new, changed = classify_products(products, existing_by_id)

    assert new == []
    assert changed == [
        {"product": products[0], "row": 7, "changes": {"Imagen": ("old.jpg", "new.jpg")}}
    ]


def test_classify_excludes_unchanged_product_from_changed():
    products = [
        {"id": 304, "name": "MOBI", "price": "400", "image": "img.jpg"},
    ]
    existing_by_id = {
        "304": {"row": 8, "Producto": "MOBI", "Precio": "400", "Imagen": "img.jpg"},
    }

    new, changed = classify_products(products, existing_by_id)

    assert new == []
    assert changed == []


def test_classify_detects_multiple_field_changes_on_one_product():
    products = [
        {"id": 305, "name": "MOBI", "price": "500", "image": "new.jpg"},
    ]
    existing_by_id = {
        "305": {"row": 9, "Producto": "MOBI", "Precio": "400", "Imagen": "old.jpg"},
    }

    new, changed = classify_products(products, existing_by_id)

    assert new == []
    assert changed == [
        {
            "product": products[0],
            "row": 9,
            "changes": {
                "Precio": ("400", "500"),
                "Imagen": ("old.jpg", "new.jpg"),
            },
        }
    ]


def test_classify_handles_mixed_batch_of_new_changed_and_unchanged():
    products = [
        {"id": 401, "name": "New Product", "price": "100", "image": "n.jpg"},
        {"id": 402, "name": "MOBI", "price": "500", "image": "img.jpg"},
        {"id": 403, "name": "Unchanged", "price": "200", "image": "u.jpg"},
    ]
    existing_by_id = {
        "402": {"row": 10, "Producto": "MOBI", "Precio": "400", "Imagen": "img.jpg"},
        "403": {"row": 11, "Producto": "Unchanged", "Precio": "200", "Imagen": "u.jpg"},
    }

    new, changed = classify_products(products, existing_by_id)

    assert new == [products[0]]
    assert changed == [
        {"product": products[1], "row": 10, "changes": {"Precio": ("400", "500")}}
    ]


def test_classify_normalizes_int_product_id_against_string_sheet_keys():
    """WooCommerce returns `id` as int; existing_by_id keys always come from
    the sheet as str (via read_existing_rows). A naive `str(id) in existing_by_id`
    still works, but the *values* comparison must also normalize types, or an
    already-synced product could be misdetected as new across this boundary.
    """
    products = [
        {"id": 101, "name": "MOBI", "price": "400", "image": "img.jpg"},
        {"id": 999, "name": "Brand New Product"},
    ]
    existing_by_id = {
        "101": {"row": 2, "Producto": "MOBI", "Precio": "400", "Imagen": "img.jpg"},
    }

    new, changed = classify_products(products, existing_by_id)

    assert new == [{"id": 999, "name": "Brand New Product"}]
    assert changed == []
