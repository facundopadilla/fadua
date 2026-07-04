from sync.notifier import _build_body, _build_subject


def test_subject_agrees_in_number_for_a_single_product():
    # The demo publishes exactly one product, so this is the subject FADUA reads.
    assert _build_subject(1) == "[PYTHON] 1 producto nuevo sincronizado"


def test_subject_agrees_in_number_for_multiple_products():
    assert _build_subject(3) == "[PYTHON] 3 productos nuevos sincronizados"


def test_body_omits_empty_price_parentheses():
    body = _build_body([{"name": "MOBI", "price": ""}])
    assert "MOBI" in body
    assert "($)" not in body


def test_body_shows_price_when_present():
    body = _build_body([{"name": "MOBI", "price": "400"}])
    assert "MOBI ($400)" in body
