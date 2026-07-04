from sync.notifier import _build_body, _build_subject


def test_subject_only_new_singular():
    assert _build_subject(1, 0) == "[PYTHON] 1 producto nuevo"


def test_subject_only_new_plural():
    assert _build_subject(3, 0) == "[PYTHON] 3 productos nuevos"


def test_subject_only_changed_singular():
    assert _build_subject(0, 1) == "[PYTHON] 1 producto actualizado"


def test_subject_only_changed_plural():
    assert _build_subject(0, 4) == "[PYTHON] 4 productos actualizados"


def test_subject_both_singular_and_singular():
    assert _build_subject(1, 1) == "[PYTHON] 1 nuevo, 1 actualizado"


def test_subject_both_plural_new_and_singular_changed():
    assert _build_subject(2, 1) == "[PYTHON] 2 nuevos, 1 actualizado"


def test_subject_both_singular_new_and_plural_changed():
    assert _build_subject(1, 3) == "[PYTHON] 1 nuevo, 3 actualizados"


def test_body_renders_only_nuevos_section_when_nothing_changed():
    body = _build_body([{"name": "MOBI", "price": "400"}], [])

    assert body == "Nuevos:\n- MOBI ($400)"


def test_body_omits_empty_price_parentheses():
    body = _build_body([{"name": "MOBI", "price": ""}], [])

    assert "($)" not in body
    assert body == "Nuevos:\n- MOBI"


def test_body_renders_only_actualizados_section_when_nothing_new():
    changed = [
        {
            "product": {"id": 301, "name": "MOBI", "price": "500", "image": "img.jpg"},
            "row": 5,
            "changes": {"Precio": ("400", "500")},
        }
    ]

    body = _build_body([], changed)

    assert body == "Actualizados:\n- MOBI: Precio $400 → $500"


def test_body_describes_image_change_without_raw_url():
    changed = [
        {
            "product": {"id": 303, "name": "MOBI", "price": "400", "image": "new.jpg"},
            "row": 7,
            "changes": {
                "Imagen": ("https://example.com/old.jpg", "https://example.com/new.jpg")
            },
        }
    ]

    body = _build_body([], changed)

    assert body == "Actualizados:\n- MOBI: Imagen actualizada"
    assert "example.com" not in body


def test_body_joins_multiple_field_changes_on_one_line():
    changed = [
        {
            "product": {"id": 305, "name": "MOBI", "price": "500", "image": "new.jpg"},
            "row": 9,
            "changes": {
                "Precio": ("400", "500"),
                "Imagen": ("old.jpg", "new.jpg"),
            },
        }
    ]

    body = _build_body([], changed)

    assert body == "Actualizados:\n- MOBI: Precio $400 → $500, Imagen actualizada"


def test_body_describes_name_change_using_new_name_as_bullet_label():
    """Judgment call (spec left this wording undefined): show old -> new like
    Precio does, and use the NEW name as the bullet label since that's the
    row's current identity going forward.
    """
    changed = [
        {
            "product": {"id": 302, "name": "MOBI PRO", "price": "400", "image": "img.jpg"},
            "row": 6,
            "changes": {"Producto": ("MOBI", "MOBI PRO")},
        }
    ]

    body = _build_body([], changed)

    assert body == "Actualizados:\n- MOBI PRO: Producto MOBI → MOBI PRO"


def test_body_renders_both_sections_when_new_and_changed():
    new = [{"name": "Brand New", "price": "300"}]
    changed = [
        {
            "product": {"id": 301, "name": "MOBI", "price": "500", "image": "img.jpg"},
            "row": 5,
            "changes": {"Precio": ("400", "500")},
        }
    ]

    body = _build_body(new, changed)

    assert body == (
        "Nuevos:\n- Brand New ($300)\n\nActualizados:\n- MOBI: Precio $400 → $500"
    )
